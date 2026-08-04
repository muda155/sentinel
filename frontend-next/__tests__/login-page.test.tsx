import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { vi as viLocale } from "@/lib/locales/vi";

const mocks = vi.hoisted(() => ({ login: vi.fn(), push: vi.fn() }));

vi.mock("@/lib/auth", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth")>("@/lib/auth");
  return { ...actual, useAuth: () => ({ login: mocks.login }) };
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));

import { LoginError } from "@/lib/auth";
import LoginPage from "@/app/login/page";

describe("LoginPage", () => {
  beforeEach(() => { mocks.login.mockReset(); mocks.push.mockReset(); });

  it("labels both fields for assistive tech", () => {
    render(<LoginPage />);
    expect(screen.getByLabelText(viLocale["login.username"])).toBeTruthy();
    expect(screen.getByLabelText(viLocale["login.password"])).toBeTruthy();
  });

  it("navigates to the dashboard on success", async () => {
    mocks.login.mockResolvedValue(undefined);
    render(<LoginPage />);
    fireEvent.change(screen.getByLabelText(viLocale["login.username"]), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText(viLocale["login.password"]), { target: { value: "admin" } });
    fireEvent.click(screen.getByRole("button", { name: viLocale["login.submit"] }));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/"));
  });

  // the inputs are `required`, and jsdom's constraint validation blocks the
  // submit event on empty required fields — fill both fields so the click
  // actually reaches the handler these tests are exercising
  const fillAndSubmit = () => {
    fireEvent.change(screen.getByLabelText(viLocale["login.username"]), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText(viLocale["login.password"]), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: viLocale["login.submit"] }));
  };

  it("distinguishes a rejected password from an unreachable API", async () => {
    mocks.login.mockRejectedValue(new LoginError("network"));
    render(<LoginPage />);
    fillAndSubmit();
    expect(await screen.findByText(viLocale["login.error.network"])).toBeTruthy();
  });

  it("shows the credentials message for a 401", async () => {
    mocks.login.mockRejectedValue(new LoginError("credentials"));
    render(<LoginPage />);
    fillAndSubmit();
    expect(await screen.findByText(viLocale["login.error.credentials"])).toBeTruthy();
  });

  it("disables submit while the request is in flight", async () => {
    let release: () => void = () => {};
    mocks.login.mockReturnValue(new Promise<void>((r) => { release = r; }));
    render(<LoginPage />);
    const button = screen.getByRole("button", { name: viLocale["login.submit"] });
    fireEvent.change(screen.getByLabelText(viLocale["login.username"]), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText(viLocale["login.password"]), { target: { value: "wrong" } });
    fireEvent.click(button);
    // Double-submitting fires a second /auth/login, which the new rate limiter
    // counts against the user.
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(true));
    release();
  });

  it("announces errors politely", async () => {
    mocks.login.mockRejectedValue(new LoginError("credentials"));
    render(<LoginPage />);
    fillAndSubmit();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(viLocale["login.error.credentials"]);
  });
});
