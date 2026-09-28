import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));

vi.mock("@/lib/api-client", () => ({
  ApiError: class extends Error {},
  apiRequest: mocks.apiRequest,
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { GatewaysPanel } from "../gateways-panel";

const GATEWAY = {
  id: "g1", name: "Head office", online: true, last_seen_at: new Date().toISOString(),
  version: "1.0.0", hostname: "TM1SRV", created_at: "", connection_count: 2,
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <GatewaysPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => mocks.apiRequest.mockReset());

describe("gateways", () => {
  it("lists gateways with whether they are online", async () => {
    mocks.apiRequest.mockResolvedValue([GATEWAY]);
    renderPanel();

    expect(await screen.findByText("Head office")).toBeInTheDocument();
    expect(screen.getByText("online")).toBeInTheDocument();
    expect(screen.getByText(/TM1SRV · v1.0.0 · seen just now · 2 connection/)).toBeInTheDocument();
  });

  it("shows the key once, inside the exact commands to install it", async () => {
    const user = userEvent.setup();
    mocks.apiRequest.mockImplementation(async (path: string, options?: { method?: string }) =>
      options?.method === "POST"
        ? { gateway: { ...GATEWAY, online: false }, key: "pagw_abc.1.secret", server_url: "https://api.example.com" }
        : [],
    );
    renderPanel();

    await user.click(await screen.findByRole("button", { name: /add gateway/i }));
    await user.type(screen.getByLabelText("Name"), "Head office");
    await user.click(screen.getByRole("button", { name: /create gateway/i }));

    await waitFor(() =>
      expect(
        screen.getByText(
          "pa-copilot-gateway.exe setup --server https://api.example.com --key pagw_abc.1.secret --allow localhost:8010",
        ),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("pa-copilot-gateway.exe install")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /pa-copilot-gateway.exe/ })).toHaveAttribute(
      "href",
      "/downloads/pa-copilot-gateway.exe",
    );
  });
});
