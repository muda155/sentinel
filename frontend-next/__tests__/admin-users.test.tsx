import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { vi as viLocale } from "@/lib/locales/vi";

const mocks = vi.hoisted(() => ({
  users: vi.fn(), createUser: vi.fn(), deleteUser: vi.fn(),
  auth: { token: "t", user: { username: "admin", role: "admin" }, hydrated: true, isAdmin: true },
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    api: { users: mocks.users, createUser: mocks.createUser, deleteUser: mocks.deleteUser },
    ApiError: actual.ApiError,
  };
});
vi.mock("@/lib/auth", () => ({ useAuth: () => mocks.auth }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import AdminUsersPage from "@/app/admin/users/page";

const row = (over = {}) => ({
  user_id: 1, username: "admin", role: "admin", created_at: "2026-01-01T00:00:00Z", ...over,
});

describe("AdminUsersPage", () => {
  beforeEach(() => {
    mocks.users.mockReset(); mocks.createUser.mockReset(); mocks.deleteUser.mockReset();
    mocks.auth.isAdmin = true;
    mocks.auth.user = { username: "admin", role: "admin" };
    mocks.auth.hydrated = true;
    mocks.auth.token = "t";
  });

  it("renders nothing before auth hydrates (no forbidden-screen flash on SSR)", () => {
    mocks.auth.hydrated = false;
    mocks.auth.token = null;
    const { container } = render(<AdminUsersPage />);
    expect(container.innerHTML).toBe("");
    expect(mocks.users).not.toHaveBeenCalled();
  });

  it("refuses to render for a non-admin", () => {
    mocks.auth.isAdmin = false;
    mocks.auth.user = { username: "analyst", role: "analyst" };
    mocks.users.mockResolvedValue([]);
    render(<AdminUsersPage />);
    expect(screen.getByText(viLocale["admin.users.forbidden"])).toBeTruthy();
    // and must not have asked the API for the list
    expect(mocks.users).not.toHaveBeenCalled();
  });

  it("lists accounts", async () => {
    mocks.users.mockResolvedValue([row(), row({ user_id: 2, username: "analyst", role: "analyst" })]);
    render(<AdminUsersPage />);
    expect(await screen.findByText("analyst")).toBeTruthy();
  });

  // the password label also carries the "8–72 characters" hint inside it, so
  // an exact getByLabelText("Mật khẩu") misses — match the label by substring
  const passwordField = () => screen.getByLabelText(new RegExp(viLocale["login.password"]));

  it("appends the created account without a refetch", async () => {
    mocks.users.mockResolvedValue([row()]);
    mocks.createUser.mockResolvedValue(row({ user_id: 9, username: "newbie", role: "analyst" }));
    render(<AdminUsersPage />);
    await screen.findByText("admin");
    fireEvent.change(screen.getByLabelText(viLocale["login.username"]), { target: { value: "newbie" } });
    fireEvent.change(passwordField(), { target: { value: "password123" } });
    fireEvent.click(screen.getByRole("button", { name: viLocale["admin.users.create"] }));
    expect(await screen.findByText("newbie")).toBeTruthy();
    expect(mocks.users).toHaveBeenCalledTimes(1);
  });

  it("names the duplicate case rather than showing a generic failure", async () => {
    mocks.users.mockResolvedValue([row()]);
    mocks.createUser.mockRejectedValue(new ApiError(409, "/auth/users -> 409"));
    render(<AdminUsersPage />);
    await screen.findByText("admin");
    fireEvent.change(screen.getByLabelText(viLocale["login.username"]), { target: { value: "admin" } });
    fireEvent.change(passwordField(), { target: { value: "password123" } });
    fireEvent.click(screen.getByRole("button", { name: viLocale["admin.users.create"] }));
    expect(await screen.findByText(viLocale["admin.users.duplicate"])).toBeTruthy();
  });

  it("gives the signed-in admin no delete button for their own row", async () => {
    mocks.users.mockResolvedValue([row(), row({ user_id: 2, username: "analyst", role: "analyst" })]);
    render(<AdminUsersPage />);
    await screen.findByText("analyst");
    // The server also refuses this; the UI should not offer it in the first place.
    expect(screen.getAllByRole("button", { name: viLocale["admin.users.delete"] })).toHaveLength(1);
  });

  it("removes the row after a successful delete", async () => {
    mocks.users.mockResolvedValue([row(), row({ user_id: 2, username: "analyst", role: "analyst" })]);
    mocks.deleteUser.mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<AdminUsersPage />);
    await screen.findByText("analyst");
    fireEvent.click(screen.getByRole("button", { name: viLocale["admin.users.delete"] }));
    await waitFor(() => expect(screen.queryByText("analyst")).toBeNull());
  });

  it("ignores a second delete click while the first is in flight", async () => {
    mocks.users.mockResolvedValue([row(), row({ user_id: 2, username: "analyst", role: "analyst" })]);
    let resolveDelete!: () => void;
    mocks.deleteUser.mockReturnValue(new Promise((res) => { resolveDelete = () => res(undefined); }));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<AdminUsersPage />);
    await screen.findByText("analyst");
    const button = screen.getByRole("button", { name: viLocale["admin.users.delete"] });
    fireEvent.click(button);
    fireEvent.click(button);
    resolveDelete();
    await waitFor(() => expect(mocks.deleteUser).toHaveBeenCalledTimes(1));
  });
});
