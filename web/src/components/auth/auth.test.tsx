import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { fakeAuth, renderWithApp } from "@/test/render";
import { AuthCallback } from "./auth-callback";
import { SignInForm } from "./sign-in-form";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const signedOut = () => fakeAuth({ session: null });

describe("SignInForm", () => {
  beforeEach(() => router.replace.mockClear());

  test("sends a magic link and asks the user to check their email", async () => {
    const auth = signedOut();
    renderWithApp(<SignInForm />, { auth });

    await userEvent.type(screen.getByLabelText("Email"), "punter@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Email me a sign-in link" }));

    expect(auth.sendMagicLink).toHaveBeenCalledWith("punter@example.com");
    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    expect(screen.getByText(/punter@example.com/)).toBeInTheDocument();
  });

  test("asks for a valid email before sending", async () => {
    const auth = signedOut();
    renderWithApp(<SignInForm />, { auth });

    await userEvent.type(screen.getByLabelText("Email"), "not-an-email");
    await userEvent.click(screen.getByRole("button", { name: "Email me a sign-in link" }));

    expect(auth.sendMagicLink).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a valid email address.");
  });

  test("says so when the link can't be sent", async () => {
    const auth = fakeAuth({ session: null, sendMagicLink: vi.fn().mockRejectedValue(new Error("rate limit")) });
    renderWithApp(<SignInForm />, { auth });

    await userEvent.type(screen.getByLabelText("Email"), "punter@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Email me a sign-in link" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't send the link/i);
  });

  test("sends signed-in visitors straight to chat", async () => {
    renderWithApp(<SignInForm />);

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/chat"));
  });
});

describe("AuthCallback", () => {
  beforeEach(() => router.replace.mockClear());
  afterEach(() => window.history.replaceState({}, "", "/"));

  test("continues to chat once the session arrives", async () => {
    renderWithApp(<AuthCallback />);

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/chat"));
  });

  test("waits while the link is being checked", () => {
    renderWithApp(<AuthCallback />, { auth: fakeAuth({ session: null, isLoading: true }) });

    expect(screen.getByText("Signing you in…")).toBeInTheDocument();
  });

  test("explains an expired or used link", () => {
    window.history.replaceState({}, "", "/auth/callback?error_description=Email+link+is+invalid+or+has+expired");
    renderWithApp(<AuthCallback />, { auth: signedOut() });

    expect(screen.getByRole("alert")).toHaveTextContent("Email link is invalid or has expired");
    expect(screen.getByRole("link", { name: "Send a new link" })).toHaveAttribute("href", "/sign-in");
  });
});
