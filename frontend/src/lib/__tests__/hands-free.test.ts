/**
 * Hands-free turn-taking — UNIT tests with a fake microphone, fake speech
 * and fake timers. They prove the controller's rules, not that a real
 * browser's speech recognition behaves; that needs a live microphone.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DUPLICATE_WINDOW_MS,
  ERROR_RETRY_DELAYS_MS,
  HandsFreeTurns,
  PAUSED_BLOCKED,
  PAUSED_HIDDEN,
  PAUSED_LOST,
  PAUSED_SILENCE,
  RESTART_DELAY_MS,
  SILENT_LIMIT,
  type TurnState,
} from "../hands-free";

let clock = 0;

function setup() {
  const io = {
    listening: false,
    speaking: false,
    starts: 0,
    submitted: [] as string[],
    states: [] as TurnState[],
    startListening: vi.fn(() => {
      // The real useVoice never opens the mic over speech; this fake makes
      // overlapping a test failure instead.
      expect(io.speaking).toBe(false);
      io.listening = true;
      io.starts += 1;
    }),
    stopListening: vi.fn(() => {
      io.listening = false;
    }),
    stopSpeaking: vi.fn(() => {
      io.speaking = false;
    }),
    submit: vi.fn((text: string) => io.submitted.push(text)),
    onChange: vi.fn((state: TurnState) => io.states.push(state)),
  };
  const turns = new HandsFreeTurns(io, () => clock);
  return { io, turns };
}

/** One full turn: the answer streams, is spoken, speech ends. */
function answer(io: ReturnType<typeof setup>["io"], turns: HandsFreeTurns) {
  io.speaking = true;
  turns.onSpeaking();
  turns.onAnswerDone(true);
  io.speaking = false;
  turns.onSpeechDone();
}

beforeEach(() => {
  vi.useFakeTimers();
  clock = 0;
});
afterEach(() => vi.useRealTimers());

describe("hands-free turn-taking (fake browser)", () => {
  it("speak → submitted → answer spoken → listening again, with no Send", () => {
    const { io, turns } = setup();
    turns.enable();
    expect(turns.state).toBe("listening");

    turns.onFinal("Why did Actual Allocation fail?");
    expect(io.submitted).toEqual(["Why did Actual Allocation fail?"]);
    expect(turns.state).toBe("processing");

    io.speaking = true;
    turns.onSpeaking();
    expect(io.listening).toBe(false); // never open while speaking
    expect(turns.state).toBe("speaking");

    turns.onAnswerDone(true);
    expect(turns.state).toBe("speaking");
    io.speaking = false;
    turns.onSpeechDone();
    expect(turns.state).toBe("restarting");
    vi.advanceTimersByTime(RESTART_DELAY_MS);
    expect(turns.state).toBe("listening");
    expect(io.starts).toBe(2);
  });

  it("sends one utterance once: repeats, finals during an answer and empty speech are dropped", () => {
    const { io, turns } = setup();
    turns.enable();
    turns.onFinal("fix it");
    turns.onFinal("fix it"); // the browser firing twice while answering
    turns.onFinal("something else"); // the answer is still coming
    expect(io.submitted).toEqual(["fix it"]);

    answer(io, turns);
    vi.advanceTimersByTime(RESTART_DELAY_MS);
    clock += 500;
    turns.onFinal("fix it"); // same words again within the window: a repeat
    expect(io.submitted).toEqual(["fix it"]);
    vi.advanceTimersByTime(RESTART_DELAY_MS);

    turns.onFinal("   ");
    expect(io.submitted).toEqual(["fix it"]);
    clock += DUPLICATE_WINDOW_MS;
    vi.advanceTimersByTime(RESTART_DELAY_MS);
    turns.onFinal("fix it");
    expect(io.submitted).toEqual(["fix it", "fix it"]); // later, a real second request
  });

  it("never stacks restart timers", () => {
    const { io, turns } = setup();
    turns.enable();
    turns.onNoSpeech();
    turns.onSpeechDone();
    turns.onNoSpeech();
    vi.advanceTimersByTime(RESTART_DELAY_MS * 5);
    expect(io.starts).toBe(2); // enable + one restart
  });

  it("silence pauses with a message instead of turning off, and a tap resumes", () => {
    const { io, turns } = setup();
    turns.enable();
    for (let i = 0; i < SILENT_LIMIT; i++) {
      turns.onNoSpeech();
      vi.advanceTimersByTime(RESTART_DELAY_MS);
    }
    expect(turns.state).toBe("paused");
    expect(turns.message).toBe(PAUSED_SILENCE);
    expect(turns.isOn).toBe(true);
    expect(io.listening).toBe(false);

    turns.resume();
    expect(turns.state).toBe("listening");
  });

  it("a lost microphone retries with growing delays, then pauses", () => {
    const { io, turns } = setup();
    turns.enable();
    for (const delay of ERROR_RETRY_DELAYS_MS) {
      turns.onError("network");
      vi.advanceTimersByTime(delay - 1);
      expect(turns.state).toBe("restarting");
      vi.advanceTimersByTime(1);
      expect(turns.state).toBe("listening");
    }
    turns.onError("network");
    expect(turns.state).toBe("paused");
    expect(turns.message).toBe(PAUSED_LOST);
    expect(io.starts).toBe(1 + ERROR_RETRY_DELAYS_MS.length);
  });

  it("a blocked microphone pauses at once with how to fix it", () => {
    const { turns } = setup();
    turns.enable();
    turns.onError("not-allowed");
    expect(turns.message).toBe(PAUSED_BLOCKED);
  });

  it("a failed answer hands the turn back, and repeated failures pause", () => {
    const { io, turns } = setup();
    turns.enable();
    for (let i = 0; i < ERROR_RETRY_DELAYS_MS.length; i++) {
      turns.onFinal(`question ${i}`);
      turns.onAnswerDone(false, true);
      vi.advanceTimersByTime(RESTART_DELAY_MS);
      expect(turns.state).toBe("listening");
    }
    turns.onFinal("one more");
    turns.onAnswerDone(false, true);
    expect(turns.state).toBe("paused");
    expect(io.submitted).toHaveLength(ERROR_RETRY_DELAYS_MS.length + 1);
  });

  it("interrupt stops speech and listens immediately", () => {
    const { io, turns } = setup();
    turns.enable();
    turns.onFinal("why");
    io.speaking = true;
    turns.onSpeaking();
    turns.onAnswerDone(true);
    turns.interrupt();
    expect(io.stopSpeaking).toHaveBeenCalled();
    expect(turns.state).toBe("listening");
    expect(io.listening).toBe(true);
  });

  it("the stop phrase ends hands-free and is not sent", () => {
    const { io, turns } = setup();
    turns.enable();
    turns.onFinal("Stop.");
    expect(turns.isOn).toBe(false);
    expect(turns.state).toBe("idle");
    expect(io.submitted).toEqual([]);
  });

  it("a typed question during hands-free closes the microphone until it is answered", () => {
    const { io, turns } = setup();
    turns.enable();
    turns.onAnswerStarted();
    expect(io.listening).toBe(false);
    expect(turns.state).toBe("processing");
    turns.onSpeechDone(); // pauses between streamed sentences hand nothing back
    vi.advanceTimersByTime(RESTART_DELAY_MS);
    expect(turns.state).toBe("processing");
    turns.onAnswerDone(false);
    vi.advanceTimersByTime(RESTART_DELAY_MS);
    expect(turns.state).toBe("listening");
  });

  it("a hidden tab pauses", () => {
    const { io, turns } = setup();
    turns.enable();
    turns.onHidden();
    expect(turns.message).toBe(PAUSED_HIDDEN);
    expect(io.listening).toBe(false);
  });
});

describe("turn timings (fake clock)", () => {
  it("measures submit → speech → answer done → listening again", () => {
    const { io, turns } = setup();
    turns.enable();
    clock = 1000;
    turns.onFinal("why did it fail");
    clock = 1900;
    io.speaking = true;
    turns.onSpeaking();
    clock = 2500;
    turns.onAnswerDone(true);
    clock = 4000;
    io.speaking = false;
    turns.onSpeechDone();
    clock = 4400;
    vi.advanceTimersByTime(RESTART_DELAY_MS);
    expect(turns.timings).toEqual({ speech_started: 900, answer_done: 1500, listening_again: 3400 });
  });
});

describe("listening watchdog (fake clock)", () => {
  it("treats a session that reports nothing as silence, then pauses", async () => {
    const { LISTEN_TIMEOUT_MS } = await import("../hands-free");
    const { io, turns } = setup();
    turns.enable();
    vi.advanceTimersByTime(LISTEN_TIMEOUT_MS);
    expect(io.stopListening).toHaveBeenCalled();
    turns.onNoSpeech(); // the closed session's late end: ignored
    vi.advanceTimersByTime(RESTART_DELAY_MS);
    expect(turns.state).toBe("listening");
    vi.advanceTimersByTime(LISTEN_TIMEOUT_MS + RESTART_DELAY_MS);
    vi.advanceTimersByTime(LISTEN_TIMEOUT_MS);
    expect(turns.state).toBe("paused");
    expect(turns.message).toBe(PAUSED_SILENCE);
  });

  it("words arriving keep the microphone open", async () => {
    const { LISTEN_TIMEOUT_MS } = await import("../hands-free");
    const { io, turns } = setup();
    turns.enable();
    vi.advanceTimersByTime(LISTEN_TIMEOUT_MS - 100);
    turns.onHeard();
    vi.advanceTimersByTime(LISTEN_TIMEOUT_MS - 100);
    expect(io.stopListening).not.toHaveBeenCalled();
    expect(turns.state).toBe("listening");
  });
});
