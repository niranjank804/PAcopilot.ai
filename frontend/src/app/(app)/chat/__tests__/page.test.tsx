/**
 * AI Chat — the highest-behaviour surface in the app.
 *
 * Tested from the user's side: what they type, what they see arrive, and
 * what happens when the stream fails. The streaming transport is the only
 * thing stubbed, because it is the network; the component's own state
 * machine is exercised for real.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

// vi.mock is hoisted above ordinary top-level code, so anything the
// factory closes over has to be created by vi.hoisted.
const mocks = vi.hoisted(() => {
  class FakeApiError extends Error {
    constructor(
      public status: number,
      public code: string,
      message: string,
    ) {
      super(message);
    }
  }

  return {
    FakeApiError,
    streamRequest: vi.fn(),
    apiRequest: vi.fn(),
    toastError: vi.fn(),
  };
});

const { streamRequest, apiRequest, toastError, FakeApiError } = mocks;

vi.mock("@/lib/api-client", () => ({
  ApiError: mocks.FakeApiError,
  apiRequest: mocks.apiRequest,
  streamRequest: mocks.streamRequest,
  uploadRequest: vi.fn(),
  registerTokenAccessors: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { error: mocks.toastError, success: vi.fn() },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/chat",
}));

import ChatPage from "../page";

/** Turn a list of events into the async iterable the page consumes. */
function streamOf(events: unknown[]) {
  return (async function* () {
    for (const event of events) {
      yield event;
    }
  })();
}

const DONE = {
  type: "done",
  conversation_id: "c1",
  message_id: "m1",
  usage: { input_tokens: 10, output_tokens: 5 },
  model: "claude-opus-4-8",
};

function renderChat() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ChatPage />
    </QueryClientProvider>,
  );
}

async function sendMessage(user: ReturnType<typeof userEvent.setup>, text: string) {
  const box = screen.getByPlaceholderText(/ask about cubes/i);
  await user.type(box, text);
  await user.keyboard("{Enter}");
}

beforeEach(() => {
  vi.clearAllMocks();
  // Agents and conversations lists; the page tolerates empty ones.
  apiRequest.mockResolvedValue([]);
});

describe("sending a message", () => {
  it("shows the user's message and the streamed reply", async () => {
    const user = userEvent.setup();

    streamRequest.mockReturnValue(
      streamOf([
        { type: "text_delta", text: "Sales " },
        { type: "text_delta", text: "cube has 4 dimensions." },
        DONE,
      ]),
    );

    renderChat();
    await sendMessage(user, "describe the sales cube");

    expect(await screen.findByText("describe the sales cube")).toBeInTheDocument();

    // Deltas accumulate into one message rather than replacing each other.
    await waitFor(() =>
      expect(
        screen.getByText(/Sales cube has 4 dimensions\./),
      ).toBeInTheDocument(),
    );
  });

  it("does not send an empty message", async () => {
    const user = userEvent.setup();
    renderChat();

    const box = screen.getByPlaceholderText(/ask about cubes/i);
    await user.click(box);
    await user.keyboard("{Enter}");

    expect(streamRequest).not.toHaveBeenCalled();
  });

  it("does not send whitespace only", async () => {
    const user = userEvent.setup();
    renderChat();

    await sendMessage(user, "   ");

    expect(streamRequest).not.toHaveBeenCalled();
  });

  it("clears the input once sent", async () => {
    const user = userEvent.setup();
    streamRequest.mockReturnValue(streamOf([DONE]));

    renderChat();
    await sendMessage(user, "hello");

    await waitFor(() =>
      expect(screen.getByPlaceholderText(/ask about cubes/i)).toHaveValue(""),
    );
  });
});

describe("while streaming", () => {
  it("locks the composer so a second message cannot be started", async () => {
    const user = userEvent.setup();

    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });

    streamRequest.mockReturnValue(
      (async function* () {
        yield { type: "text_delta", text: "working" };
        await gate;
        yield DONE;
      })(),
    );

    renderChat();
    await sendMessage(user, "first");

    await screen.findByText(/working/);

    // This is the behaviour the user actually meets: the composer is
    // disabled, so there is no way to start a second request from the UI.
    // (send() also guards on isStreaming, but that guard is unreachable
    // through the interface — a test that typed into the box would pass
    // whether or not it existed, which is why this asserts the disabled
    // state instead.)
    expect(screen.getByPlaceholderText(/ask about cubes/i)).toBeDisabled();

    release();

    await waitFor(() =>
      expect(screen.getByPlaceholderText(/ask about cubes/i)).toBeEnabled(),
    );
  });
});

describe("tool execution", () => {
  it("shows each tool the agent runs", async () => {
    const user = userEvent.setup();

    streamRequest.mockReturnValue(
      streamOf([
        { type: "tool_call", tool_name: "get_cube", tool_status: "success" },
        { type: "tool_call", tool_name: "execute_mdx", tool_status: "success" },
        { type: "text_delta", text: "Revenue was 42." },
        DONE,
      ]),
    );

    renderChat();
    await sendMessage(user, "what was revenue");

    expect(await screen.findByText(/get_cube/)).toBeInTheDocument();
    expect(screen.getByText(/execute_mdx/)).toBeInTheDocument();
  });
});

describe("when the stream fails", () => {
  it("surfaces a server-sent error event to the user", async () => {
    const user = userEvent.setup();

    streamRequest.mockReturnValue(
      streamOf([{ type: "error", message: "The model is unavailable." }]),
    );

    renderChat();
    await sendMessage(user, "hello");

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("The model is unavailable."),
    );

    // The message is shown in place, not only as a toast that vanishes.
    expect(
      await screen.findByText("The model is unavailable."),
    ).toBeInTheDocument();
  });

  it("recovers so the next message can still be sent", async () => {
    const user = userEvent.setup();

    streamRequest.mockReturnValueOnce(
      (async function* () {
        yield { type: "text_delta", text: "partial" };
        throw new FakeApiError(500, "SERVER_ERROR", "Upstream died.");
      })(),
    );

    renderChat();
    await sendMessage(user, "first");

    await waitFor(() => expect(toastError).toHaveBeenCalled());

    // isStreaming must be cleared in `finally`, or the box locks forever.
    streamRequest.mockReturnValueOnce(streamOf([{ type: "text_delta", text: "ok" }, DONE]));
    await sendMessage(user, "second");

    expect(streamRequest).toHaveBeenCalledTimes(2);
  });
});

describe("agent selection", () => {
  it("sends no agent and disables tools in plain chat", async () => {
    const user = userEvent.setup();
    streamRequest.mockReturnValue(streamOf([DONE]));

    renderChat();
    await sendMessage(user, "hello");

    const body = streamRequest.mock.calls[0][1] as Record<string, unknown>;

    expect(body.agent).toBeUndefined();
    expect(body.enable_tools).toBe(false);
  });
});

// ======================================================================
// Voice
//
// The property worth testing is not that audio works — it is that voice
// is not a second, less-governed way into the assistant. The transcript
// lands in the same composer and goes out through the same
// `streamRequest`, so RBAC, tool permissions, approval gates and audit
// logging are inherited. These tests pin that, plus the state machine
// and the browser-support gate.
// ======================================================================

/** A controllable stand-in for the Web Speech API. */
function installSpeech({ supported = true } = {}) {
  const instances: Record<string, unknown>[] = [];

  class FakeRecognition {
    lang = "";
    continuous = false;
    interimResults = false;
    onresult: ((event: unknown) => void) | null = null;
    onerror: ((event: unknown) => void) | null = null;
    onend: (() => void) | null = null;
    started = false;

    constructor() {
      instances.push(this as unknown as Record<string, unknown>);
    }

    start() {
      this.started = true;
    }

    stop() {
      this.started = false;
      this.onend?.();
    }
  }

  const utterances: string[] = [];
  const synthesis = {
    speak: vi.fn((utterance: { text: string }) => {
      utterances.push(utterance.text);
    }),
    cancel: vi.fn(),
  };

  vi.stubGlobal("SpeechRecognition", supported ? FakeRecognition : undefined);
  vi.stubGlobal("webkitSpeechRecognition", undefined);
  vi.stubGlobal("speechSynthesis", synthesis);
  vi.stubGlobal(
    "SpeechSynthesisUtterance",
    class {
      text: string;
      lang = "";
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(text: string) {
        this.text = text;
      }
    },
  );

  return {
    /** The recognition object the page constructed. */
    get recognition() {
      return instances[instances.length - 1] as unknown as FakeRecognition;
    },
    utterances,
    synthesis,
  };
}

describe("voice", () => {
  it("hides the mic where the browser has no recognition", async () => {
    // Firefox and Safari. Offering a dead button is worse than offering
    // nothing.
    installSpeech({ supported: false });

    renderChat();

    await waitFor(() =>
      expect(screen.getByPlaceholderText(/ask about cubes/i)).toBeInTheDocument(),
    );

    expect(
      screen.queryByRole("button", { name: /voice input/i }),
    ).not.toBeInTheDocument();
  });

  it("offers the mic where recognition exists", async () => {
    installSpeech();

    renderChat();

    expect(
      await screen.findByRole("button", { name: /start voice input/i }),
    ).toBeInTheDocument();
  });

  it("puts the transcript in the composer for review rather than sending it", async () => {
    // Auto-sending what a speech recogniser *thought* it heard would
    // put an unreviewed instruction into a governed system.
    const speech = installSpeech();
    const user = userEvent.setup();

    renderChat();

    await user.click(
      await screen.findByRole("button", { name: /start voice input/i }),
    );

    speech.recognition.onresult?.({
      results: { length: 1, 0: { 0: { transcript: "list the sales cubes" } } },
    });

    await waitFor(() =>
      expect(screen.getByPlaceholderText(/ask about cubes/i)).toHaveValue(
        "list the sales cubes",
      ),
    );

    expect(streamRequest).not.toHaveBeenCalled();
  });

  it("sends a spoken question through the same path as a typed one", async () => {
    // The governance claim, asserted rather than asserted-in-prose: one
    // transport, so one set of permission and audit checks.
    const speech = installSpeech();
    const user = userEvent.setup();

    streamRequest.mockReturnValue(
      streamOf([{ type: "text_delta", text: "Four cubes." }, DONE]),
    );

    renderChat();

    await user.click(
      await screen.findByRole("button", { name: /start voice input/i }),
    );

    speech.recognition.onresult?.({
      results: { length: 1, 0: { 0: { transcript: "how many cubes" } } },
    });

    await waitFor(() =>
      expect(screen.getByPlaceholderText(/ask about cubes/i)).toHaveValue(
        "how many cubes",
      ),
    );

    await user.keyboard("{Enter}");

    await waitFor(() => expect(streamRequest).toHaveBeenCalledTimes(1));

    const [path, body] = streamRequest.mock.calls[0];

    expect(path).toBe("/ai/chat/stream");
    expect((body as { message: string }).message).toBe("how many cubes");
    // No voice flag, no alternate endpoint, nothing the backend could
    // treat differently.
    expect(body).not.toHaveProperty("voice");
  });

  it("speaks the answer to a spoken question", async () => {
    const speech = installSpeech();
    const user = userEvent.setup();

    streamRequest.mockReturnValue(
      streamOf([{ type: "text_delta", text: "The **Sales** cube." }, DONE]),
    );

    renderChat();

    await user.click(
      await screen.findByRole("button", { name: /start voice input/i }),
    );
    speech.recognition.onresult?.({
      results: { length: 1, 0: { 0: { transcript: "which cube" } } },
    });
    await waitFor(() =>
      expect(screen.getByPlaceholderText(/ask about cubes/i)).toHaveValue(
        "which cube",
      ),
    );
    await user.keyboard("{Enter}");

    await waitFor(() => expect(speech.synthesis.speak).toHaveBeenCalled());

    // Markdown is stripped before speaking — "star star Sales star star"
    // is what happens otherwise.
    expect(speech.utterances[0]).toBe("The Sales cube.");
  });

  it("stays silent for a typed question", async () => {
    // Audio nobody asked for is worse than no audio.
    const speech = installSpeech();
    const user = userEvent.setup();

    streamRequest.mockReturnValue(
      streamOf([{ type: "text_delta", text: "Four cubes." }, DONE]),
    );

    renderChat();

    await waitFor(() =>
      expect(screen.getByPlaceholderText(/ask about cubes/i)).toBeInTheDocument(),
    );
    await sendMessage(user, "how many cubes");

    await waitFor(() => expect(streamRequest).toHaveBeenCalled());

    expect(speech.synthesis.speak).not.toHaveBeenCalled();
  });

  it("explains a blocked microphone instead of saying to try again", async () => {
    // "Try again" sends someone in a loop when the browser is the thing
    // refusing.
    const speech = installSpeech();
    const user = userEvent.setup();

    renderChat();

    await user.click(
      await screen.findByRole("button", { name: /start voice input/i }),
    );

    speech.recognition.onerror?.({ error: "not-allowed" });

    await waitFor(() =>
      expect(screen.getByText(/microphone access is blocked/i)).toBeInTheDocument(),
    );
  });
});

describe("long, tool-using answers", () => {
  // Reported: an answer showed "I'll read the process definition.Let me
  // trace how it's wired into the model." and nothing more, while the
  // full explanation had been saved on the server.

  it("says what it is doing while the answer is still coming", async () => {
    const user = userEvent.setup();

    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });

    streamRequest.mockReturnValue(
      (async function* () {
        yield { type: "start", conversation_id: "c1" };
        yield { type: "text_delta", text: "Let me trace it." };
        yield { type: "tool_call", tool_name: "find_dependents", tool_status: "error" };
        await gate;
        yield DONE;
      })(),
    );

    renderChat();
    await sendMessage(user, "explain IT_Load Data");

    expect(
      await screen.findByText(/find_dependents could not run — continuing/),
    ).toBeInTheDocument();

    release();

    await waitFor(() =>
      expect(screen.queryByText(/continuing/)).not.toBeInTheDocument(),
    );
  });

  it("separates the narration of one tool round from the next", async () => {
    const user = userEvent.setup();

    streamRequest.mockReturnValue(
      streamOf([
        { type: "text_delta", text: "I'll read the process definition." },
        { type: "tool_call", tool_name: "get_process", tool_status: "success" },
        { type: "text_delta", text: "Let me trace how it's wired." },
        DONE,
      ]),
    );

    renderChat();
    await sendMessage(user, "explain");

    // Two paragraphs, not "definition.Let me".
    expect(
      await screen.findByText("I'll read the process definition."),
    ).toBeInTheDocument();
    expect(screen.getByText("Let me trace how it's wired.")).toBeInTheDocument();
    expect(screen.queryByText(/definition\.Let/)).not.toBeInTheDocument();
  });

  it("says so when the connection drops, and can reload the saved answer", async () => {
    const user = userEvent.setup();

    streamRequest.mockReturnValue(
      streamOf([
        { type: "start", conversation_id: "c42" },
        { type: "text_delta", text: "Let me trace it." },
        // No "done": the connection ended here.
      ]),
    );

    renderChat();
    await sendMessage(user, "explain IT_Load Data");

    expect(
      await screen.findByText(/connection dropped before this answer finished/),
    ).toBeInTheDocument();
    expect(toastError).toHaveBeenCalledWith(
      "The connection dropped before the answer finished.",
    );

    apiRequest.mockImplementation(async (path: string) =>
      path === "/ai/conversations/c42/messages"
        ? [
            { id: "u1", role: "user", content: "explain IT_Load Data" },
            { id: "a1", role: "assistant", content: "IT_Load Data loads Project.csv." },
          ]
        : [],
    );

    await user.click(screen.getByRole("button", { name: "Reload conversation" }));

    expect(
      await screen.findByText("IT_Load Data loads Project.csv."),
    ).toBeInTheDocument();
  });
});
