/**
 * Hands-free turn-taking: one source of truth for whose turn it is.
 *
 *   listening → (utterance final) → processing → (answer arrives) →
 *   speaking → (speech done) → restarting → listening …
 *
 * It owns no browser API. The chat page wires it to useVoice (microphone,
 * speech) and to `send` (the same chat request typed messages use, so the
 * conversation, task memory, permissions and approvals are shared). That
 * keeps every rule here testable with fake timers:
 *
 * - the microphone is never open while the assistant speaks (it would hear
 *   itself), and reopens only after speech finishes;
 * - one utterance is sent at most once, and nothing is sent while an answer
 *   is still being produced;
 * - silence or a lost microphone PAUSES the conversation with a message —
 *   it never turns hands-free off by itself — and restarts are bounded;
 * - a tab going to the background pauses it.
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
  startListening: () => void;
  stopListening: () => void;
  stopSpeaking: () => void;
  submit: (text: string) => void;
  onChange: (state: TurnState, message: string | null) => void;
}

/** Saying one of these ends hands-free instead of being sent. */
export const STOP_PHRASE = /^(stop|stop listening|that's all|thats all|goodbye|bye|thank you,? that's all)[.!]?$/i;

export const SILENT_LIMIT = 3;
export const RESTART_DELAY_MS = 400;
/** A listening session that hears nothing at all for this long is treated
 *  as silence. Chrome sometimes leaves the recogniser open indefinitely in
 *  a quiet room (seen live: over 70 s), showing "Listening" to nobody. */
export const LISTEN_TIMEOUT_MS = 15000;
export const ERROR_RETRY_DELAYS_MS = [500, 1000, 2000];
/** The same words again this soon are the browser repeating itself. */
export const DUPLICATE_WINDOW_MS = 3000;

export const PAUSED_SILENCE = "Voice paused — I didn't hear anything. Tap the headphones button to resume.";
export const PAUSED_LOST =
  "I lost the voice connection. Your conversation is still saved. Tap the headphones button to continue.";
export const PAUSED_BLOCKED =
  "Voice paused — the microphone is blocked. Allow it in your browser's site settings, then tap the headphones button.";
export const PAUSED_HIDDEN = "Voice paused while the tab was in the background. Tap the headphones button to resume.";

export class HandsFreeTurns {
  state: TurnState = "idle";
  message: string | null = null;
  private enabled = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private watchdog: ReturnType<typeof setTimeout> | null = null;
  private silent = 0;
  private errors = 0;
  private failedAnswers = 0;
  private answering = false;
  private lastSent: { text: string; at: number } | null = null;
  /** Milliseconds from the utterance being submitted to each later step
   *  of that turn — measured, for the console, never estimated. */
  timings: Record<string, number> = {};
  private turnStart = 0;

  constructor(private readonly io: HandsFreeIO, private readonly now: () => number = () => Date.now()) {}

  get isOn(): boolean {
    return this.enabled;
  }

  private set(state: TurnState, message: string | null = null) {
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

  /** Open the microphone now, with a watchdog for a session that never
   *  reports anything. */
  private listen() {
    this.set("listening");
    this.io.startListening();
    this.armWatchdog();
  }

  private armWatchdog() {
    this.clearWatchdog();
    this.watchdog = setTimeout(() => {
      this.watchdog = null;
      if (!this.enabled || this.state !== "listening") return;
      // Close it ourselves and count it as silence. The session's own late
      // end is then ignored, because we are no longer "listening".
      this.silent += 1;
      this.io.stopListening();
      if (this.silent >= SILENT_LIMIT) return this.pause(PAUSED_SILENCE);
      this.listenAfter(RESTART_DELAY_MS);
    }, LISTEN_TIMEOUT_MS);
  }

  /** Words are arriving: the speaker is mid-sentence, keep listening. */
  onHeard() {
    if (this.enabled && this.state === "listening") this.armWatchdog();
  }

  /** Open the microphone after `delay`; any earlier pending restart is
   *  replaced, so there is never more than one. */
  private listenAfter(delay: number) {
    this.clearTimer();
    this.set("restarting");
    this.timer = setTimeout(() => {
      this.timer = null;
      if (!this.enabled || this.answering || this.state === "paused") return;
      this.mark("listening_again");
      this.listen();
    }, delay);
  }

  private mark(step: string) {
    if (this.turnStart && !(step in this.timings)) this.timings[step] = this.now() - this.turnStart;
  }

  private pause(message: string) {
    this.clearTimer();
    this.io.stopListening();
    this.set("paused", message);
  }

  enable() {
    this.enabled = true;
    this.silent = 0;
    this.errors = 0;
    if (this.answering) {
      this.set("processing");
      return;
    }
    this.clearTimer();
    this.listen();
  }

  disable() {
    this.enabled = false;
    this.clearTimer();
    this.io.stopListening();
    this.io.stopSpeaking();
    this.set("idle");
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

  /** The microphone stopped with everything it heard. Only counts while
   *  this controller is listening: a session it closed itself (to think or
   *  speak) ending late must not start a turn. */
  onFinal(text: string) {
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
    this.turnStart = this.now();
    this.timings = {};
    this.answering = true;
    this.set("processing");
    this.io.submit(said);
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
    const delay = ERROR_RETRY_DELAYS_MS[this.errors];
    this.errors += 1;
    if (delay === undefined) return this.pause(PAUSED_LOST);
    this.listenAfter(delay);
  }

  /** A request this controller did not submit (typed) has started. */
  onAnswerStarted() {
    this.answering = true;
    this.clearTimer();
    if (this.enabled && this.state !== "paused") {
      this.io.stopListening();
      this.set("processing");
    }
  }

  /** Speech of the answer has begun. */
  onSpeaking() {
    if (!this.enabled || this.state === "paused") return;
    this.mark("speech_started");
    this.clearTimer();
    this.io.stopListening();
    this.set("speaking");
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

  /** Every queued sentence has played. */
  onSpeechDone() {
    if (!this.enabled || this.answering || this.state === "paused") return;
    this.listenAfter(RESTART_DELAY_MS);
  }

  /** The tab went to the background: no hidden open microphone. */
  onHidden() {
    if (!this.enabled || this.state === "paused") return;
    this.io.stopSpeaking();
    this.pause(PAUSED_HIDDEN);
  }

  dispose() {
    this.clearTimer();
  }
}
