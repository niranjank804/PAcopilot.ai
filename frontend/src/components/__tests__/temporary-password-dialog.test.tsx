/**
 * The Super Admin's one-time password: generated on request with a reason
 * for the audit log, shown exactly once, copyable.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiRequest = vi.fn();
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

import { ApiError } from "@/lib/api-client";

import { TemporaryPasswordDialog } from "../temporary-password-dialog";

const issued = {
  id: "u1",
  username: "vamshi",
  temporary_password: "abcde-fghjk-mnpqr",
  expires_at: "2026-11-01T10:00:00Z",
};

function renderDialog(onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TemporaryPasswordDialog person={{ id: "u1", name: "Vamshi E" }} onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("TemporaryPasswordDialog", () => {
  it("asks for a reason, generates once, and shows the password with its expiry", async () => {
    apiRequest.mockResolvedValueOnce(issued);
    const user = userEvent.setup();
    renderDialog();

    expect(screen.getByText("Temporary password for Vamshi E")).toBeInTheDocument();
    expect(screen.queryByTestId("temporary-password")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText(/Reason/), "asked by phone");
    await user.click(screen.getByRole("button", { name: "Generate password" }));

    await waitFor(() => expect(screen.getByTestId("temporary-password")).toHaveTextContent("abcde-fghjk-mnpqr"));
    expect(apiRequest).toHaveBeenCalledWith("/admin/platform/users/u1/temporary-password", {
      method: "POST",
      body: { reason: "asked by phone" },
    });
    expect(screen.getByText(/shown only now/)).toBeInTheDocument();
    expect(screen.getByText("vamshi")).toBeInTheDocument();
  });

  it("copies the password to the clipboard", async () => {
    apiRequest.mockResolvedValueOnce(issued);
    // user-event installs its own clipboard stub on setup; watch that one.
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText");
    renderDialog();

    await user.click(screen.getByRole("button", { name: "Generate password" }));
    await screen.findByTestId("temporary-password");
    await user.click(screen.getByRole("button", { name: "Copy" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("abcde-fghjk-mnpqr"));
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("shows the server's refusal and keeps the form", async () => {
    apiRequest.mockRejectedValueOnce(new ApiError(422, "VALIDATION_ERROR", "Reactivate (or approve) the account first."));
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("button", { name: "Generate password" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Reactivate (or approve) the account first."));
    expect(screen.queryByTestId("temporary-password")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate password" })).toBeInTheDocument();
  });

  it("Done closes it", async () => {
    apiRequest.mockResolvedValueOnce(issued);
    const user = userEvent.setup();
    const onClose = renderDialog();

    await user.click(screen.getByRole("button", { name: "Generate password" }));
    await screen.findByTestId("temporary-password");
    await user.click(screen.getByRole("button", { name: "Done" }));

    expect(onClose).toHaveBeenCalled();
  });
});
