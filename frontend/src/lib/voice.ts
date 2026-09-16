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
    (markdown: string) => {
      const synthesis = window.speechSynthesis;

      if (!synthesis || mutedRef.current) return;

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
    stopSpeaking,
    toggleMuted,
  };
}
