import { screen, waitFor } from "@testing-library/react";
import { Activity } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { AppContext } from "@/components/app/app-context";
import { ApiRequestError } from "@/lib/api/errors";
import { fakeApi, fakeAuth, ME, renderWithApp } from "@/test/render";
import { MemberGate, useMe } from "./member-gate";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

function Email() {
  return <p>{useMe().me.email}</p>;
}

describe("MemberGate", () => {
  beforeEach(() => {
    router.replace.mockClear();
  });

  test("shows its children with the member's profile", async () => {
    renderWithApp(
      <MemberGate>
        <Email />
      </MemberGate>,
    );

    expect(await screen.findByText(ME.email)).toBeInTheDocument();
  });

  test("sends signed-out visitors to sign in", async () => {
    renderWithApp(<MemberGate>secret</MemberGate>, { auth: fakeAuth({ session: null }) });

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/sign-in"));
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  test("waits while the session loads", () => {
    renderWithApp(<MemberGate>secret</MemberGate>, { auth: fakeAuth({ session: null, isLoading: true }) });

    expect(router.replace).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  test("sends members without the 18+ declaration to onboarding", async () => {
    const api = fakeApi({ getMe: vi.fn().mockResolvedValue({ ...ME, age_confirmed: false }) });
    renderWithApp(<MemberGate>secret</MemberGate>, { api });

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/onboarding"));
  });

  test("doesn't bounce back to onboarding on stale state when a hidden page returns", async () => {
    // Next keeps visited pages mounted in a hidden <Activity>, state included.
    const getMe = vi.fn().mockResolvedValueOnce({ ...ME, age_confirmed: false }).mockResolvedValue(ME);
    const api = fakeApi({ getMe });
    const gate = (mode: "visible" | "hidden") => (
      <Activity mode={mode}>
        <MemberGate>chat</MemberGate>
      </Activity>
    );
    const { rerender } = renderWithApp(gate("visible"), { api });
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/onboarding"));

    rerender(<AppContext.Provider value={{ api, auth: fakeAuth() }}>{gate("hidden")}</AppContext.Provider>);
    rerender(<AppContext.Provider value={{ api, auth: fakeAuth() }}>{gate("visible")}</AppContext.Provider>);

    expect(await screen.findByText("chat")).toBeInTheDocument();
    expect(router.replace).toHaveBeenCalledTimes(1);
  });

  test("lets onboarding through before the 18+ declaration", async () => {
    const api = fakeApi({ getMe: vi.fn().mockResolvedValue({ ...ME, age_confirmed: false }) });
    renderWithApp(<MemberGate allowUnconfirmed>onboarding</MemberGate>, { api });

    expect(await screen.findByText("onboarding")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  test("shows the break screen with support links during a break", async () => {
    const until = "2099-01-01T12:00:00Z";
    const api = fakeApi({ getMe: vi.fn().mockResolvedValue({ ...ME, self_excluded_until: until }) });
    renderWithApp(<MemberGate>chat</MemberGate>, { api });

    expect(await screen.findByRole("heading", { name: "You're on a break" })).toBeInTheDocument();
    expect(screen.getByText(/Thu 1 Jan, 12:00/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /GamCare/ })).toHaveAttribute("href", "tel:08088020133");
    expect(screen.queryByText("chat")).not.toBeInTheDocument();
  });

  test("lets settings through during a break", async () => {
    const api = fakeApi({
      getMe: vi.fn().mockResolvedValue({ ...ME, self_excluded_until: "2099-01-01T12:00:00Z" }),
    });
    renderWithApp(<MemberGate allowOnBreak>settings</MemberGate>, { api });

    expect(await screen.findByText("settings")).toBeInTheDocument();
  });

  test("ignores a break that has already ended", async () => {
    const api = fakeApi({
      getMe: vi.fn().mockResolvedValue({ ...ME, self_excluded_until: "2020-01-01T00:00:00Z" }),
    });
    renderWithApp(<MemberGate>chat</MemberGate>, { api });

    expect(await screen.findByText("chat")).toBeInTheDocument();
  });

  test("follows the redirect for an expired session", async () => {
    const expired = new ApiRequestError({ code: "unauthenticated", message: "Please sign in again.", status: 401 });
    renderWithApp(<MemberGate>chat</MemberGate>, { api: fakeApi({ getMe: vi.fn().mockRejectedValue(expired) }) });

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/sign-in"));
  });

  test("shows the server's message when the profile can't load", async () => {
    const down = new ApiRequestError({ code: "internal", message: "Something went wrong.", status: 500 });
    renderWithApp(<MemberGate>chat</MemberGate>, { api: fakeApi({ getMe: vi.fn().mockRejectedValue(down) }) });

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong.");
  });
});
