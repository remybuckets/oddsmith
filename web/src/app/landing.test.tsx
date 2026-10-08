import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import LandingPage from "./page";

describe("Landing page", () => {
  test("shows the name, tagline and three example questions", () => {
    render(<LandingPage />);

    expect(screen.getByRole("heading", { level: 1, name: /Oddsmith/ })).toBeInTheDocument();
    expect(screen.getByText(/the tipster the bookies would send off/i)).toBeInTheDocument();
    expect(screen.getAllByRole("listitem", { name: /example question/i })).toHaveLength(3);
  });

  test("leads to sign-in", () => {
    render(<LandingPage />);

    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in");
  });

  test("carries the 18+ notice and GamCare in the footer", () => {
    render(<LandingPage />);

    const footer = screen.getByRole("contentinfo");
    expect(footer).toHaveTextContent("18+ only.");
    expect(footer).toHaveTextContent("GamCare on 0808 8020 133");
    expect(footer).toHaveTextContent("GAMSTOP");
  });
});
