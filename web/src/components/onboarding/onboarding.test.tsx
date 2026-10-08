import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { MemberGate } from "@/components/app/member-gate";
import { ApiRequestError } from "@/lib/api/errors";
import { fakeApi, ME, renderWithApp } from "@/test/render";
import { Onboarding } from "./onboarding";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

function renderOnboarding(api = fakeApi()) {
  return renderWithApp(
    <MemberGate allowUnconfirmed>
      <Onboarding />
    </MemberGate>,
    { api },
  );
}

const unconfirmed = () => fakeApi({ getMe: vi.fn().mockResolvedValue({ ...ME, age_confirmed: false }) });

describe("Onboarding", () => {
  beforeEach(() => router.push.mockClear());

  test("needs the 18+ box ticked before continuing", async () => {
    const api = unconfirmed();
    renderOnboarding(api);

    const button = await screen.findByRole("button", { name: "Continue" });
    expect(button).toBeDisabled();

    await userEvent.click(screen.getByRole("checkbox", { name: /I'm 18 or over/ }));
    expect(button).toBeEnabled();
  });

  test("records the declaration, then explains how Oddsmith works", async () => {
    const api = unconfirmed();
    renderOnboarding(api);

    await userEvent.click(await screen.findByRole("checkbox", { name: /I'm 18 or over/ }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(api.confirmAge).toHaveBeenCalledOnce();
    expect(await screen.findByRole("heading", { name: "How Oddsmith works" })).toBeInTheDocument();
    expect(screen.getByText(/not advice/i)).toBeInTheDocument();
  });

  test("links to the terms from the declaration", async () => {
    renderOnboarding(unconfirmed());

    expect(await screen.findByRole("link", { name: "terms" })).toHaveAttribute("href", "/terms");
  });

  test("shows the server's message if the declaration fails", async () => {
    const failure = new ApiRequestError({ code: "internal", message: "Something went wrong.", status: 500 });
    const api = fakeApi({
      getMe: vi.fn().mockResolvedValue({ ...ME, age_confirmed: false }),
      confirmAge: vi.fn().mockRejectedValue(failure),
    });
    renderOnboarding(api);

    await userEvent.click(await screen.findByRole("checkbox", { name: /I'm 18 or over/ }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong.");
  });

  test("skips the declaration once confirmed and starts chatting", async () => {
    renderOnboarding();

    await userEvent.click(await screen.findByRole("button", { name: "Start asking" }));

    expect(router.push).toHaveBeenCalledWith("/chat");
  });
});
