/**
 * Settings — profile and organization editing.
 *
 * Closes QA finding F2, where both surfaces read "isn't available yet".
 * The cases worth pinning are the permission ones: a Viewer has no
 * organization.read, so a 403 must read as "you don't have permission"
 * rather than as a broken page.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
    apiRequest: vi.fn(),
    toastSuccess: vi.fn(),
    toastError: vi.fn(),
    user: {
      id: "u-1",
      username: "admin",
      email: "admin@example.com",
      first_name: "Admin",
      last_name: "User",
      is_active: true,
    },
  };
});

vi.mock("@/lib/api-client", () => ({
  ApiError: mocks.FakeApiError,
  apiRequest: mocks.apiRequest,
  registerTokenAccessors: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: mocks.toastSuccess, error: mocks.toastError },
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: mocks.user, isLoading: false }),
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: "system", setTheme: vi.fn() }),
}));

import SettingsPage from "../page";

const ORGANIZATION = {
  id: "org-1",
  name: "Acme Planning",
  code: "acme",
  domain: "acme.example",
  is_active: true,
  plan: "free",
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <SettingsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.apiRequest.mockReset();
  mocks.toastSuccess.mockReset();
  mocks.toastError.mockReset();
});

describe("Profile editing", () => {
  it("is seeded from the signed-in user", async () => {
    mocks.apiRequest.mockResolvedValue(ORGANIZATION);

    renderPage();

    expect(await screen.findByLabelText(/first name/i)).toHaveValue("Admin");
    expect(screen.getByLabelText(/last name/i)).toHaveValue("User");
  });

  it("saves a renamed profile", async () => {
    mocks.apiRequest.mockResolvedValue(ORGANIZATION);

    const user = userEvent.setup();

    renderPage();

    const first = await screen.findByLabelText(/first name/i);
    await user.clear(first);
    await user.type(first, "Niranjan");

    await user.click(screen.getAllByRole("button", { name: /^save$/i })[0]);

    await waitFor(() =>
      expect(mocks.apiRequest).toHaveBeenCalledWith(
        "/users/me",
        expect.objectContaining({
          method: "PATCH",
          body: expect.objectContaining({ first_name: "Niranjan" }),
        }),
      ),
    );
  });

  it("cannot be submitted unchanged", async () => {
    // Avoids a pointless write and an audit row for a no-op.
    mocks.apiRequest.mockResolvedValue(ORGANIZATION);

    renderPage();

    await screen.findByLabelText(/first name/i);

    expect(screen.getAllByRole("button", { name: /^save$/i })[0]).toBeDisabled();
  });

  it("cannot be submitted with a blank name", async () => {
    mocks.apiRequest.mockResolvedValue(ORGANIZATION);

    const user = userEvent.setup();

    renderPage();

    await user.clear(await screen.findByLabelText(/first name/i));

    expect(screen.getAllByRole("button", { name: /^save$/i })[0]).toBeDisabled();
  });

  it("surfaces a save failure", async () => {
    mocks.apiRequest.mockImplementation((path: string) => {
      if (path === "/users/organization") return Promise.resolve(ORGANIZATION);

      return Promise.reject(
        new mocks.FakeApiError(422, "VALIDATION_ERROR", "That name is invalid."),
      );
    });

    const user = userEvent.setup();

    renderPage();

    const first = await screen.findByLabelText(/first name/i);
    await user.clear(first);
    await user.type(first, "X");

    await user.click(screen.getAllByRole("button", { name: /^save$/i })[0]);

    await waitFor(() =>
      expect(mocks.toastError).toHaveBeenCalledWith("That name is invalid."),
    );
  });
});

describe("Organization settings", () => {
  it("shows the organization and its read-only fields", async () => {
    mocks.apiRequest.mockResolvedValue(ORGANIZATION);

    renderPage();

    expect(await screen.findByDisplayValue("Acme Planning")).toBeInTheDocument();
    // code and plan are shown but not editable — code is a stable
    // identifier referenced elsewhere.
    expect(screen.getByText("acme")).toBeInTheDocument();
    expect(screen.getByText("free")).toBeInTheDocument();
    expect(screen.queryByLabelText(/^code$/i)).not.toBeInTheDocument();
  });

  it("saves a renamed organization", async () => {
    mocks.apiRequest.mockResolvedValue(ORGANIZATION);

    const user = userEvent.setup();

    renderPage();

    const name = await screen.findByDisplayValue("Acme Planning");
    await user.clear(name);
    await user.type(name, "Acme Group");

    const buttons = screen.getAllByRole("button", { name: /^save$/i });
    await user.click(buttons[buttons.length - 1]);

    await waitFor(() =>
      expect(mocks.apiRequest).toHaveBeenCalledWith(
        "/users/organization",
        expect.objectContaining({
          method: "PATCH",
          body: expect.objectContaining({ name: "Acme Group" }),
        }),
      ),
    );
  });

  it("explains a permission refusal rather than looking broken", async () => {
    // A Viewer has no organization.read. A 403 is the expected answer,
    // not a fault, and must not read as an error page.
    mocks.apiRequest.mockRejectedValue(
      new mocks.FakeApiError(403, "PERMISSION_DENIED", "Missing permission"),
    );

    renderPage();

    expect(
      await screen.findByText(/don't have permission to view organization/i),
    ).toBeInTheDocument();
  });

  it("does not claim the feature is unavailable any more", async () => {
    // The exact string QA reported. Its return would be a regression.
    mocks.apiRequest.mockResolvedValue(ORGANIZATION);

    const { container } = renderPage();

    await screen.findByDisplayValue("Acme Planning");

    expect(container.textContent).not.toMatch(/aren't available yet/i);
    expect(container.textContent).not.toMatch(/isn't available yet/i);
  });
});
