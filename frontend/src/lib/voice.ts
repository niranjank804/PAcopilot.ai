"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Voice for the AI assistant: speech in, speech out.
 *
 * **This is not a second AI.** Speech-to-text fills the same composer
 * the keyboard fills, and the result is sent through the same
 * `sendMessage` path as typed text. So authentication, organization
 * scoping, RBAC, tool permissions, human-approval gates, audit logging
 * and usage accounting are not re-implemented here — they are
 * inherited, because nothing about the request differs once the words
 * exist. A voice request that asks to delete a process meets exactly
 * the approval gate a typed one meets.
 *
 * That property is structural rather than promised, which is the point:
 * there is no voice-specific code path that could drift from the text
 * one and quietly skip a check.
 *
 * **Why the browser rather than a cloud provider.** Both halves use the
 * Web Speech API, so audio never leaves the machine. For a product
 * whose users dictate questions about their employer's financial
 * planning data, "the recording was never uploaded" is a materially
 * better answer than a data-processing agreement. It also costs
 * nothing, needs no API key, and adds no failure mode to a deployment
 * that has already been taken down twice by an exhausted balance.
 *
 * The trade-off is real and worth stating: recognition quality is the
 * browser's, and support is Chrome/Edge only — Firefox and Safari have
 * no `SpeechRecognition`. `isSupported` is false there and the UI hides
 * rather than offering something broken. If server-side recognition is
 * ever wanted for quality or coverage, it belongs behind the same
 * `start`/`stop`/`speak` surface this hook already exposes; nothing in
 * the chat page would change.
 */

export type VoiceState =
  | "idle"
  | "requesting-permission"
  | "listening"
  | "speaking"
  | "error";

/**
 * Markdown stripped for the ear.
 *
 * The assistant writes Markdown, and a speech synthesiser reads it
 * literally: "star star Revenue star star" for `**Revenue**`, every
 * pipe of a table, every backtick of a code block. Code is skipped
 * outright rather than spelled out, because `CellPutN(0, 'Sales', ...)`
 * as audio is noise, and the text of it is on screen anyway.
 */
export function speakableText(markdown: string): string {
  return (
    markdown
      // Fenced code: announce, don't recite.
      .replace(/```[\s\S]*?```/g, " Code block shown on screen. ")
      .replace(/`([^`]+)`/g, "$1")
      // Images before links — an image is `![alt](url)` and would
      // otherwise leave a stray "!".
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/^#{1,6}\s+/gm, "")
      .replace(/(\*\*|__)(.*?)\1/g, "$2")
      .replace(/(\*|_)(.*?)\1/g, "$2")
      .replace(/^>\s?/gm, "")
      .replace(/^\s*[-*+]\s+/gm, "")
      .replace(/^\s*\d+\.\s+/gm, "")
      // Table pipes and rules read as punctuation soup.
      .replace(/^\s*\|.*\|\s*$/gm, (row) =>
        row.replace(/\|/g, " ").replace(/^[\s-]+$/, ""),
      )
      .replace(/^\s*([-*_]\s*){3,}$/gm, "")
      .replace(/\n{2,}/g, ". ")
      .replace(/\s+/g, " ")
      .trim()
  );
}


/**
 * The next whole sentence that is safe to speak, given how much of the
 * stream has already been spoken.
 *
 * Audio used to wait for the entire answer. With a tool-using model an
 * answer takes seconds, while its first sentence is ready almost
 * immediately — so the user sat in silence watching text appear. This
 * lets speech follow the stream instead, which is the one real latency
 * win available without changing provider: `speechSynthesis` queues
 * utterances natively, so successive sentences play back to back.
 *
 * Only *completed* sentences are returned. Speaking a half-sentence
 * would force a pause mid-clause, which sounds worse than waiting.
 *
 * An unterminated code fence holds everything back: mid-fence text
 * would otherwise be spoken as prose before the stripper could see the
 * closing marks and skip it.
 */
export function nextSpeakableChunk(
  fullText: string,
  alreadyConsumed: number,
): { text: string; consumedTo: number } | null {
  const pending = fullText.slice(alreadyConsumed);

  if (!pending.trim()) return null;

  // An odd number of fences means one is still open.
  if ((fullText.slice(0, alreadyConsumed + pending.length).match(/```/g) ?? []).length % 2 === 1) {
    return null;
  }

  // Last sentence-ending punctuation followed by a space or the end of
  // what has arrived. Anything after it is still being written.
  const boundary = /[.!?](?=\s|$)/g;
  let end = -1;
  let match: RegExpExecArray | null;

  while ((match = boundary.exec(pending)) !== null) {
    end = match.index + 1;
  }

  if (end === -1) return null;

  const text = speakableText(pending.slice(0, end));

  // The slice may have been pure markup — a heading, a table row.
  // Consume it regardless so it is not re-examined forever.
  return { text, consumedTo: alreadyConsumed + end };
}

/** Longest utterance we will start. */
const MAX_SPEAK_CHARS = 4000;

export function useVoice(options: {
  /** Called with the final transcript. */
  onTranscript: (text: string) => void;
}) {
  const { onTranscript } = options;

  const [state, setState] = useState<VoiceState>("idle");
  // Both flags in one object, set once: the effect then triggers a
  // single render instead of two, and one disable directive covers it.
  // Neither can be known before mount — `window` does not exist during
  // server rendering.
  const [support, setSupport] = useState({ listen: false, speak: false });
  const [isMuted, setIsMuted] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const recognitionRef = useRef<SpeechRecognition | null>(null);
  // Held in a ref as well as state: the recognition callbacks are bound
  // once on mount and would otherwise close over the first `isMuted`
  // forever.
  const mutedRef = useRef(false);
  // How much of the streaming answer has already been queued for
  // speech. Reset per answer, so a new reply never re-speaks the old.
  const spokenUpToRef = useRef(0);
  const onTranscriptRef = useRef(onTranscript);

  useEffect(() => {
    onTranscriptRef.current = onTranscript;
  }, [onTranscript]);

  useEffect(() => {
    mutedRef.current = isMuted;
  }, [isMuted]);

  useEffect(() => {
    const Ctor = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    const canSpeak = typeof window.speechSynthesis !== "undefined";

    if (!Ctor) {
      // Firefox and Safari: no recognition, but synthesis still works,
      // so spoken answers remain available to a typed question.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSupport({ listen: false, speak: canSpeak });
      return;
    }

    const recognition = new Ctor();
    recognition.lang = "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onresult = (event) => {
      const transcript = event.results[event.results.length - 1][0].transcript;

      setState("idle");
      onTranscriptRef.current(transcript);
    };

    recognition.onerror = (event) => {
      // `not-allowed` is a denied permission prompt, not a failure to
      // hear — telling someone to "try again" when the browser is
      // blocking the microphone sends them in a loop.
      setState("error");
      setErrorMessage(
        event.error === "not-allowed" || event.error === "service-not-allowed"
          ? "Microphone access is blocked. Allow it in your browser's site settings, then try again."
          : event.error === "no-speech"
            ? "Didn't catch anything — try again."
            : "Couldn't hear that — try again.",
      );
    };

    recognition.onend = () =>
      setState((current) => (current === "error" ? current : "idle"));

    recognitionRef.current = recognition;
    setSupport({ listen: true, speak: canSpeak });

    return () => {
      recognition.onresult = null;
      recognition.onerror = null;
      recognition.onend = null;
      try {
        recognition.stop();
      } catch {
        // Already stopped; nothing to unwind.
      }
      window.speechSynthesis?.cancel();
    };
  }, []);

  const stopSpeaking = useCallback(() => {
    window.speechSynthesis?.cancel();
    // Interrupting abandons the rest of this answer rather than
    // resuming it on the next delta.
    spokenUpToRef.current = Number.MAX_SAFE_INTEGER;
    setState((current) => (current === "speaking" ? "idle" : current));
  }, []);

  const start = useCallback(() => {
    const recognition = recognitionRef.current;

    if (!recognition) return;

    // Dictating over the assistant's own voice would feed it back into
    // the microphone.
    window.speechSynthesis?.cancel();

    setErrorMessage(null);
    // The browser may prompt; the label has to admit that rather than
    // claiming to be listening while a dialog is up.
    setState("requesting-permission");

    try {
      recognition.start();
      setState("listening");
    } catch {
      // start() throws if already started — recover to a truthful state
      // rather than leaving the button stuck.
      setState("idle");
    }
  }, []);

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
    setState("idle");
  }, []);

  const speak = useCallback(
    // `explicit`: the person pressed a read-aloud button, so the mute —
    // which silences answers read out automatically — does not apply.
    (markdown: string, options?: { explicit?: boolean }) => {
      const synthesis = window.speechSynthesis;

      if (!synthesis || (mutedRef.current && !options?.explicit)) return;

      const text = speakableText(markdown).slice(0, MAX_SPEAK_CHARS);

      if (!text) return;

      // Without this, a second answer queues behind the first and the
      // user hears a stale one.
      synthesis.cancel();

      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = "en-US";
      utterance.onend = () =>
        setState((current) => (current === "speaking" ? "idle" : current));
      utterance.onerror = () =>
        setState((current) => (current === "speaking" ? "idle" : current));

      setState("speaking");
      synthesis.speak(utterance);
    },
    [],
  );

  /** Speak whole sentences as a streamed answer arrives.
   *
   * Deliberately does NOT cancel first, unlike `speak`: cancelling
   * between sentences would cut off the one currently playing. The
   * browser queues utterances, which is what makes following a stream
   * possible without a streaming-capable provider.
   */
  const speakStreaming = useCallback(
    (fullText: string, options?: { final?: boolean }) => {
    const synthesis = window.speechSynthesis;

    if (!synthesis || mutedRef.current) return;

    for (;;) {
      const chunk = nextSpeakableChunk(fullText, spokenUpToRef.current);

      if (!chunk) break;

      spokenUpToRef.current = chunk.consumedTo;

      if (!chunk.text) continue;

      const utterance = new SpeechSynthesisUtterance(
        chunk.text.slice(0, MAX_SPEAK_CHARS),
      );
      utterance.lang = "en-US";
      utterance.onend = () =>
        setState((current) => (current === "speaking" ? "idle" : current));

      setState("speaking");
      synthesis.speak(utterance);
    }

    // The last sentence of an answer often has no trailing space, and
    // a model may end without punctuation at all — so on the final
    // call whatever is left is spoken regardless of a boundary. Without
    // this the closing words are silently dropped.
    if (options?.final) {
      const remainder = speakableText(fullText.slice(spokenUpToRef.current));

      spokenUpToRef.current = fullText.length;

      if (remainder) {
        const utterance = new SpeechSynthesisUtterance(
          remainder.slice(0, MAX_SPEAK_CHARS),
        );
        utterance.lang = "en-US";
        utterance.onend = () =>
          setState((current) => (current === "speaking" ? "idle" : current));

        setState("speaking");
        synthesis.speak(utterance);
      }
    }
  },
    [],
  );

  /** Start of a new answer: forget what was spoken for the last one. */
  const resetStream = useCallback(() => {
    spokenUpToRef.current = 0;
  }, []);

  const toggleMuted = useCallback(() => {
    setIsMuted((previous) => {
      if (!previous) window.speechSynthesis?.cancel();
      return !previous;
    });
  }, []);

  return {
    state,
    isSupported: support.listen,
    canSpeak: support.speak,
    isMuted,
    errorMessage,
    start,
    stop,
    speak,
    speakStreaming,
    resetStream,
    stopSpeaking,
    toggleMuted,
  };
}
