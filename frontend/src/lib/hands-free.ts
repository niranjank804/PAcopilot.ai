/**
 * Hands-free turn-taking: one source of truth for whose turn it is.
 *
 *   (greeting spoken) → listening → (utterance final) → processing →
 *   (answer arrives) → speaking → (speech done) → restarting → listening …
 *
 * It owns no browser API. The chat page wires it to useVoice (microphone,
 * speech) and to `send` (the same chat request typed messages use, so the
 * conversation, task memory, permissions and approvals are shared). That
 * keeps every rule here testable with fake timers:
 *
 * - the microphone is never open while the assistant speaks (it would hear
 *   itself), and reopens only after speech has actually finished — not when
 *   the text has finished streaming;
 * - one utterance is sent at most once, and nothing is sent while an answer
 *   is still being produced;
 * - events from a microphone session this controller already closed are
 *   ignored, so a late "end" cannot start a turn;
 * - silence, a lost microphone, a microphone that will not start, failed
 *   answers or a hidden tab PAUSE the conversation with a message — it never
 *   turns hands-free off by itself — and every restart is bounded;
 * - there is never more than one pending restart timer.
 *
 * Barge-in by voice is not offered: the browser's speech recognition cannot
 * tell the user's voice from the assistant's own audio, so listening during
 * playback would capture the answer as a question. Interrupting is a tap
 * (interrupt()): speech stops and the microphone opens at once.
 */

export type TurnState =
  | "idle"
  | "listening"
  | "processing"
  | "speaking"
  | "restarting"
  | "paused"
  | "error";

export interface HandsFreeIO {
  /** Open the microphone. `false` when it could not be started. */
  startListening: () => boolean | void;
  stopListening: () => void;
  stopSpeaking: () => void;
  /** Speak `text`; `false` when nothing will be spoken (muted, unsupported). */
  speak?: (text: string) => boolean;
  submit: (text: string) => void;
  onChange: (state: TurnState, message: string | null) => void;
}

/** Saying one of these ends hands-free instead of being sent. */
export const STOP_PHRASE = /^(stop|stop listening|that's all|thats all|goodbye|bye|thank you,? that's all)[.!]?$/i;

export const GREETING = "Hi. I'm listening. What would you like to work on?";

export const SILENT_LIMIT = 3;
export const RESTART_DELAY_MS = 400;
/** A listening session that hears nothing at all for this long is treated
 *  as silence. Chrome sometimes leaves the recogniser open indefinitely in
 *  a quiet room (seen live: over 70 s), showing "Listening" to nobody. */
export const LISTEN_TIMEOUT_MS = 15000;
export const ERROR_RETRY_DELAYS_MS = [500, 1000, 2000];
/** The same words again this soon are the browser repeating itself. */
export const DUPLICATE_WINDOW_MS = 3000;

export const RECONNECTING = "Reconnecting to the microphone…";
export const PAUSED_SILENCE = "Voice paused — I didn't hear anything. Tap the headphones button to resume.";
export const PAUSED_LOST =
  "I lost the voice connection. Your conversation is still saved. Tap the headphones button to continue.";
export const PAUSED_BLOCKED =
  "Voice paused — the microphone is blocked. Allow it in your browser's site settings, then tap the headphones button.";
export const PAUSED_HIDDEN = "Voice paused while the tab was in the background. Tap the headphones button to resume.";
export const PAUSED_BY_USER = "Voice paused. Tap the headphones button to resume.";

/** Steps of one spoken turn, in milliseconds from the moment speech ended
 *  (or, when the browser did not say, from the submission). */
export type TurnTimings = Partial<
  Record<
    | "transcript_final"
    | "submitted"
    | "first_token"
    | "answer_done"
    | "speech_started"
    | "speech_done"
    | "listening_again",
    number
  >
>;

export class HandsFreeTurns {
  state: TurnState = "idle";
  message: string | null = null;
  private enabled = false;
  private disposed = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private watchdog: ReturnType<typeof setTimeout> | null = null;
  private silent = 0;
  private errors = 0;
  private failedAnswers = 0;
  private answering = false;
  private lastSent: { text: string; at: number } | null = null;
  /** Measured, for the console; never estimated. */
  timings: TurnTimings = {};
  private turnStart = 0;

  constructor(private readonly io: HandsFreeIO, private readonly now: () => number = () => Date.now()) {}

  get isOn(): boolean {
    return this.enabled;
  }

  private set(state: TurnState, message: string | null = null) {
    if (this.disposed) return;
    this.state = state;
    this.message = message;
    this.io.onChange(state, message);
  }

  private clearTimer() {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.clearWatchdog();
  }

  private clearWatchdog() {
    if (this.watchdog !== null) {
      clearTimeout(this.watchdog);
      this.watchdog = null;
    }
  }

  /** Open the microphone now. A recogniser that will not start is retried
   *  with growing delays, then the conversation pauses — the state never
   *  says "listening" over a microphone that is not. */
  private listen() {
    this.set("listening");
    if (this.io.startListening() === false) {
      this.set("error");
      return this.retryAfterError();
    }
    this.armWatchdog();
  }

  private retryAfterError() {
    const delay = ERROR_RETRY_DELAYS_MS[this.errors];
    this.errors += 1;
    if (delay === undefined) return this.pause(PAUSED_LOST);
    this.listenAfter(delay, RECONNECTING);
  }

  private armWatchdog() {
    this.clearWatchdog();
    this.watchdog = setTimeout(() => {
      this.watchdog = null;
      if (!this.enabled || this.state !== "listening") return;
      // Close it ourselves and count it as silence. The session's own late
      // end is then ignored, because we are no longer "listening".
      this.silent += 1;
      if (this.silent >= SILENT_LIMIT) return this.pause(PAUSED_SILENCE);
      this.listenAfter(RESTART_DELAY_MS);
      this.io.stopListening();
    }, LISTEN_TIMEOUT_MS);
  }

  /** Words are arriving: the speaker is mid-sentence, keep listening. */
  onHeard() {
    if (this.enabled && this.state === "listening") this.armWatchdog();
  }

  /** Open the microphone after `delay`; any earlier pending restart is
   *  replaced, so there is never more than one. */
  private listenAfter(delay: number, note: string | null = null) {
    this.clearTimer();
    this.set("restarting", note);
    this.timer = setTimeout(() => {
      this.timer = null;
      if (!this.enabled || this.answering || this.state === "paused") return;
      this.mark("listening_again");
      this.listen();
    }, delay);
  }

  private mark(step: keyof TurnTimings) {
    if (this.turnStart && !(step in this.timings)) this.timings[step] = this.now() - this.turnStart;
  }

  /** State first, then the microphone: a session that reports its end
   *  the moment it is stopped must find the controller already paused. */
  private pause(message: string) {
    this.clearTimer();
    this.set("paused", message);
    this.io.stopListening();
  }

  /** Turn hands-free on. With a greeting, it is spoken first and the
   *  microphone opens when it has finished; a greeting that cannot be
   *  spoken (muted, unsupported) is skipped. */
  enable(greeting?: string) {
    this.enabled = true;
    this.silent = 0;
    this.errors = 0;
    this.failedAnswers = 0;
    if (this.answering) {
      this.set("processing");
      return;
    }
    this.clearTimer();
    this.io.stopListening();
    if (greeting && this.io.speak?.(greeting)) {
      this.set("speaking");
      return;
    }
    this.listen();
  }

  disable() {
    this.enabled = false;
    this.clearTimer();
    this.io.stopListening();
    this.io.stopSpeaking();
    this.set("idle");
  }

  /** Tap to pause: the microphone and any speech stop; hands-free stays on. */
  pauseByUser() {
    if (!this.enabled) return;
    this.io.stopSpeaking();
    this.pause(PAUSED_BY_USER);
  }

  /** Tap to resume after a pause (or to retry after an error). */
  resume() {
    if (!this.enabled) return this.enable();
    this.silent = 0;
    this.errors = 0;
    this.failedAnswers = 0;
    if (this.answering) return this.set("processing");
    this.clearTimer();
    this.listen();
  }

  /** Tap while the assistant speaks: stop it and listen now. */
  interrupt() {
    if (!this.enabled) return;
    this.io.stopSpeaking();
    this.clearTimer();
    this.listen();
  }

  /**
   * The microphone stopped with everything it heard. Only counts while
   * this controller is listening: a session it closed itself (to think or
   * speak) ending late must not start a turn. `speechEndedAt` is the
   * browser's own mark of when the speaker stopped, for the timings.
   */
  onFinal(text: string, speechEndedAt?: number) {
    if (!this.enabled || this.state !== "listening") return;
    const said = text.trim();
    if (!said) return this.listenAfter(RESTART_DELAY_MS);
    this.silent = 0;
    this.errors = 0;
    if (STOP_PHRASE.test(said)) return this.disable();
    // Never a second request while one is being answered.
    if (this.answering) return;
    const at = this.now();
    if (this.lastSent && this.lastSent.text.toLowerCase() === said.toLowerCase() && at - this.lastSent.at < DUPLICATE_WINDOW_MS) {
      return this.listenAfter(RESTART_DELAY_MS);
    }
    this.lastSent = { text: said, at };
    this.clearWatchdog();
    this.turnStart = speechEndedAt ?? at;
    this.timings = {};
    this.mark("transcript_final");
    this.answering = true;
    this.set("processing");
    this.io.submit(said);
    this.mark("submitted");
  }

  onNoSpeech() {
    if (!this.enabled || this.state !== "listening") return;
    this.silent += 1;
    if (this.silent >= SILENT_LIMIT) return this.pause(PAUSED_SILENCE);
    this.listenAfter(RESTART_DELAY_MS);
  }

  onError(code: string) {
    if (!this.enabled || (this.state !== "listening" && this.state !== "restarting")) return;
    if (code === "not-allowed" || code === "service-not-allowed") return this.pause(PAUSED_BLOCKED);
    // "aborted" is our own stop; nothing to recover.
    if (code === "aborted") return;
    this.retryAfterError();
  }

  /** A request this controller did not submit (typed) has started. */
  onAnswerStarted() {
    this.answering = true;
    this.clearTimer();
    if (this.enabled && this.state !== "paused") {
      this.set("processing");
      this.io.stopListening();
    }
  }

  /** The first words of the answer have arrived. */
  onFirstToken() {
    this.mark("first_token");
  }

  /** Speech of the answer (or of the greeting) has begun. */
  onSpeaking() {
    if (!this.enabled || this.state === "paused") return;
    this.mark("speech_started");
    this.clearTimer();
    this.set("speaking");
    this.io.stopListening();
  }

  /**
   * The answer finished arriving (or failed, or was stopped).
   * `stillSpeaking`: its last sentences are still playing; listening
   * resumes from onSpeechDone instead.
   */
  onAnswerDone(stillSpeaking: boolean, failed = false) {
    this.answering = false;
    this.mark("answer_done");
    if (!this.enabled || this.state === "paused") return;
    // Answers that fail in a row (network, server) pause rather than loop;
    // one that arrives resets the count.
    this.failedAnswers = failed ? this.failedAnswers + 1 : 0;
    if (failed && this.failedAnswers > ERROR_RETRY_DELAYS_MS.length) return this.pause(PAUSED_LOST);
    if (stillSpeaking) return this.set("speaking");
    this.listenAfter(RESTART_DELAY_MS);
  }

  /** Every queued sentence has played, or playback was cancelled. Only a
   *  turn that is actually in "speaking" moves on: pauses between the
   *  sentences of a streaming answer fire this too, and are ignored. */
  onSpeechDone() {
    if (!this.enabled || this.answering || this.state !== "speaking") return;
    this.mark("speech_done");
    this.listenAfter(RESTART_DELAY_MS);
  }

  /** The tab went to the background: no hidden open microphone. */
  onHidden() {
    if (!this.enabled || this.state === "paused") return;
    this.io.stopSpeaking();
    this.pause(PAUSED_HIDDEN);
  }

  /** Unmount: no timer fires and no late callback changes anything. */
  dispose() {
    this.clearTimer();
    this.enabled = false;
    this.disposed = true;
  }
}
