// The Web Speech API's SpeechRecognition interface is not part of
// TypeScript's standard DOM lib (it's non-standard/vendor-prefixed) — this
// declares just enough of it for the AI Chat voice-input mic button.
// Support: Chrome/Edge (webkitSpeechRecognition), not Firefox/Safari as of
// this writing — always feature-detect before use.

interface SpeechRecognitionResultEvent extends Event {
  resultIndex: number;
  results: {
    length: number;
    [index: number]: {
      isFinal: boolean;
      [index: number]: { transcript: string };
    };
  };
}

interface SpeechRecognitionErrorEvent extends Event {
  error: string;
}

interface SpeechRecognition extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  onresult: ((event: SpeechRecognitionResultEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
}

interface Window {
  SpeechRecognition?: new () => SpeechRecognition;
  webkitSpeechRecognition?: new () => SpeechRecognition;
}
