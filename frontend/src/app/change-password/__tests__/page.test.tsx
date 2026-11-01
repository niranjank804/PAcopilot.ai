/**
 * The forced password change after a temporary password from the Super
 * Admin: the form posts the change, then signs the person in again with
 * the new password (the change ended every session) and moves them on.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
}));

const adoptSession = vi.fn();
const logout = vi.fn();
const useAuth = vi.fn();
vi.mock("@/lib/auth-context", () => ({ useAuth: () => useAuth() }));

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

const apiRequest = vi.fn();
vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiRequest: (...args: unknown[]) => apiRequest(...args),
}));

import { ApiError } from "@/lib/api-client";

import ChangePasswordPage from "../page";

const SESSION = { access_token: "a", refresh_token: "r", token_type: "bearer" };

async function fillAndSubmit(current: string, next: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Temporary password"), current);
  await user.type(screen.getByLabelText("New password"), next);
  await user.type(screen.getByLabelText("Confirm new password"), next);
  await user.click(screen.getByRole("button", { name: "Set password and continue" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuth.mockReturnValue({
    isLoading: false,
    isAuthenticated: true,
    user: { username: "vamshi", must_change_password: true },
    adoptSession,
    logout,
  });
});

describe("choosing a password after a temporary one", () => {
  it("explains why, posts the change, continues with the new session and moves on", async () => {
    apiRequest.mockResolvedValueOnce(SESSION);
    adoptSession.mockResolvedValueOnce(undefined);
    render(<ChangePasswordPage />);

    expect(screen.getByText("Choose your password")).toBeInTheDocument();
    expect(screen.getByText(/gave you a temporary password/)).toBeInTheDocument();

    await fillAndSubmit("abcde-fghjk-mnpqr", "Chosen-by-me-2026");

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(apiRequest).toHaveBeenCalledWith("/auth/change-password", {
      method: "POST",
      body: { current_password: "abcde-fghjk-mnpqr", new_password: "Chosen-by-me-2026" },
    });
    expect(adoptSession).toHaveBeenCalledWith(SESSION);
    expect(toast.success).toHaveBeenCalled();
  });

  it("shows the server's reason when the temporary password is wrong", async () => {
    apiRequest.mockRejectedValueOnce(new ApiError(422, "VALIDATION_ERROR", "The current password is not right."));
    render(<ChangePasswordPage />);

    await fillAndSubmit("wrong-wrong-wrong", "Chosen-by-me-2026");

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("The current password is not right."));
    expect(adoptSession).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
  });

  it("falls back to the login page when the new session cannot be used", async () => {
    apiRequest.mockResolvedValueOnce(SESSION);
    adoptSession.mockRejectedValueOnce(new Error("network"));
    render(<ChangePasswordPage />);

    await fillAndSubmit("abcde-fghjk-mnpqr", "Chosen-by-me-2026");

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(logout).toHaveBeenCalled();
  });

  it("sends a signed-out visitor to login", () => {
    useAuth.mockReturnValue({ isLoading: false, isAuthenticated: false, user: null, adoptSession, logout });
    const { container } = render(<ChangePasswordPage />);

    expect(replace).toHaveBeenCalledWith("/login");
    expect(container).toBeEmptyDOMElement();
  });
});
