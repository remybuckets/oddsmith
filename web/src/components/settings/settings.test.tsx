import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { MemberGate } from "@/components/app/member-gate";
import { ApiRequestError } from "@/lib/api/errors";
import { fakeApi, fakeAuth, ME, renderWithApp } from "@/test/render";
import { SettingsScreen } from "./settings-screen";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const BREAK_UNTIL = "2099-10-15T14:00:00Z";

function renderSettings(services: Parameters<typeof renderWithApp>[1] = {}) {
  return renderWithApp(
    <MemberGate allowOnBreak>
      <SettingsScreen />
    </MemberGate>,
    services,
  );
}

describe("SettingsScreen", () => {
  beforeEach(() => router.replace.mockClear());

  test("shows today's usage and when it resets", async () => {
    renderSettings();

    expect(await screen.findByText("3 of 15 questions used today")).toBeInTheDocument();
    expect(screen.getByText("Resets Fri 9 Oct, 00:00")).toBeInTheDocument();
  });

  test("starts a break only after confirming", async () => {
    const api = fakeApi({ takeBreak: vi.fn().mockResolvedValue({ ...ME, self_excluded_until: BREAK_UNTIL }) });
    renderSettings({ api });

    await userEvent.click(await screen.findByRole("button", { name: "7 days" }));
    expect(api.takeBreak).not.toHaveBeenCalled();
    await userEvent.click(await screen.findByRole("button", { name: "Start break" }));

    expect(api.takeBreak).toHaveBeenCalledWith("7d");
    expect(await screen.findByText(/You're on a break until Thu 15 Oct, 15:00/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "24 hours" })).not.toBeInTheDocument();
  });

  test("shows the break instead of the options while one is running", async () => {
    const api = fakeApi({ getMe: vi.fn().mockResolvedValue({ ...ME, self_excluded_until: BREAK_UNTIL }) });
    renderSettings({ api });

    expect(await screen.findByText(/You're on a break until/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "30 days" })).not.toBeInTheDocument();
  });

  test("shows the server's message if the break can't start", async () => {
    const failure = new ApiRequestError({ code: "internal", message: "Something went wrong.", status: 500 });
    renderSettings({ api: fakeApi({ takeBreak: vi.fn().mockRejectedValue(failure) }) });

    await userEvent.click(await screen.findByRole("button", { name: "24 hours" }));
    await userEvent.click(await screen.findByRole("button", { name: "Start break" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong.");
  });

  test("deletes the account after confirming, then signs out", async () => {
    const api = fakeApi();
    const auth = fakeAuth();
    renderSettings({ api, auth });

    await userEvent.click(await screen.findByRole("button", { name: "Delete account" }));
    await userEvent.click(await screen.findByRole("button", { name: "Delete my account" }));

    expect(api.deleteAccount).toHaveBeenCalledOnce();
    await waitFor(() => expect(auth.signOut).toHaveBeenCalledOnce());
    expect(router.replace).toHaveBeenCalledWith("/");
  });

  test("signs out", async () => {
    const auth = fakeAuth();
    renderSettings({ auth });

    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));

    expect(auth.signOut).toHaveBeenCalledOnce();
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/"));
  });

  test("links to GamCare and GAMSTOP", async () => {
    renderSettings();

    expect(await screen.findByRole("link", { name: /GamCare on 0808 8020 133/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "GAMSTOP" })).toHaveAttribute("href", "https://www.gamstop.co.uk");
  });
});
