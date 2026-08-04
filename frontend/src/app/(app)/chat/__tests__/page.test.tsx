/**
 * AI Chat — the highest-behaviour surface in the app.
 *
 * Tested from the user's side: what they type, what they see arrive, and
 * what happens when the stream fails. The streaming transport is the only
 * thing stubbed, because it is the network; the component's own state
 * machine is exercised for real.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
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
