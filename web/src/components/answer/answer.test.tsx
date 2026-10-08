import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import type { Fixture, OddsCard, SourceRef, StatCard, ValueCard } from "@/lib/api/types";
import { type AnswerState, initialAnswer } from "@/lib/chat/answer";
import { AnswerView } from "./answer-view";
import { CardView, FormStrip } from "./cards";

const SOURCE: SourceRef = { source: "API-Football", as_of: "2026-10-10T09:00:00Z", is_stale: false };
const ODDS_SOURCE: SourceRef = { source: "The Odds API", as_of: "2026-10-16T13:30:00Z", is_stale: false };

const FIXTURE: Fixture = {
  fixture_id: 101,
  matchweek: 7,
  kickoff_at: "2026-10-17T14:00:00Z",
  status: "scheduled",
  home: { id: 1, name: "Newcastle United", short_name: "Newcastle" },
  away: { id: 2, name: "Arsenal", short_name: "Arsenal" },
};

const STAT: StatCard = {
  card_type: "stat",
  title: "Saka — away, 2026/27",
  columns: ["Stat", "Value"],
  rows: [
    ["Goals", 3],
    ["xG", null],
  ],
  form: "WWDLW",
  source: SOURCE,
};

const ODDS: OddsCard = {
  card_type: "odds",
  fixture: FIXTURE,
  market: "totals",
  line: 2.5,
  selections: [
    {
      selection: "over",
      label: "Over 2.5",
      best_price: 1.95,
      best_bookmaker: "Sky Bet",
      prices: [
        { bookmaker: "Sky Bet", price: 1.95 },
        { bookmaker: "Coral", price: 1.9 },
        { bookmaker: "Betfred", price: 1.88 },
        { bookmaker: "William Hill", price: 1.85 },
        { bookmaker: "Ladbrokes", price: 1.8 },
      ],
    },
  ],
  source: ODDS_SOURCE,
};

const VALUE: ValueCard = {
  card_type: "value",
  fixture: FIXTURE,
  market: "h2h",
  line: null,
  selection: "home",
  label: "Newcastle",
  model_probability: 0.46,
  implied_probability: 0.4,
  edge: 0.06,
  best_price: 2.5,
  best_bookmaker: "Paddy Power",
  is_highlighted: true,
  disclaimer: "Estimate, not advice.",
  source: ODDS_SOURCE,
};

function answer(overrides: Partial<AnswerState>): AnswerState {
  return { ...initialAnswer(), ...overrides };
}

describe("FormStrip", () => {
  test("shows one result per match with a readable label", () => {
    render(<FormStrip form="WWDLW" />);

    const strip = screen.getByRole("list", { name: "Form: won, won, drawn, lost, won" });
    expect(within(strip).getAllByRole("listitem")).toHaveLength(5);
  });
});

describe("stat card", () => {
  test("shows the title, table, form strip and source with its UK as-of time", () => {
    render(<CardView card={STAT} />);

    expect(screen.getByText("Saka — away, 2026/27")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Stat" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "3" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "–" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: /^Form:/ })).toBeInTheDocument();
    expect(screen.getByText("API-Football · as of Sat 10 Oct, 10:00")).toBeInTheDocument();
  });

  test("warns when the data is stale", () => {
    render(<CardView card={{ ...STAT, source: { ...SOURCE, is_stale: true } }} />);

    expect(screen.getByText(/may be out of date/i)).toBeInTheDocument();
  });
});

describe("odds card", () => {
  test("names the fixture and market, and highlights the best price", () => {
    render(<CardView card={ODDS} />);

    expect(screen.getByText("Newcastle v Arsenal · Sat 17 Oct, 15:00")).toBeInTheDocument();
    expect(screen.getByText("Total goals 2.5")).toBeInTheDocument();
    expect(screen.getByText("Best 1.95 · Sky Bet")).toHaveAttribute("data-best", "true");
    expect(screen.getByText("The Odds API · as of Fri 16 Oct, 14:30")).toBeInTheDocument();
  });

  test("lists at most four bookmakers", () => {
    render(<CardView card={ODDS} />);

    expect(screen.getAllByRole("listitem")).toHaveLength(4);
    expect(screen.queryByText("Ladbrokes")).not.toBeInTheDocument();
  });
});

describe("value badge", () => {
  test("shows model and implied probability, the edge and the disclaimer", () => {
    render(<CardView card={VALUE} />);

    expect(screen.getByText("Model 46%")).toBeInTheDocument();
    expect(screen.getByText("Market 40%")).toBeInTheDocument();
    expect(screen.getByText("Edge +6.0 pts")).toHaveAttribute("data-highlighted", "true");
    expect(screen.getByText("Estimate, not advice.")).toBeInTheDocument();
  });

  test("stays neutral when the edge is below the threshold, but keeps the disclaimer", () => {
    render(<CardView card={{ ...VALUE, edge: 0.01, is_highlighted: false }} />);

    expect(screen.getByText("Edge +1.0 pts")).toHaveAttribute("data-highlighted", "false");
    expect(screen.getByText("Estimate, not advice.")).toBeInTheDocument();
  });
});

describe("AnswerView", () => {
  test("renders markdown text", () => {
    render(<AnswerView answer={answer({ text: "Saka has **3 goals** away." })} />);

    expect(screen.getByText("3 goals").tagName).toBe("STRONG");
  });

  test("shows the running tool while streaming and hides feedback", () => {
    render(<AnswerView answer={answer({ activity: "Checking odds" })} onFeedback={vi.fn()} />);

    expect(screen.getByRole("status")).toHaveTextContent("Checking odds…");
    expect(screen.queryByRole("button", { name: /helpful/i })).not.toBeInTheDocument();
  });

  test("lists its sources with UK as-of times", () => {
    render(<AnswerView answer={answer({ status: "done", sources: [SOURCE, ODDS_SOURCE] })} />);

    expect(
      screen.getByText("Sources: API-Football (Sat 10 Oct, 10:00), The Odds API (Fri 16 Oct, 14:30)"),
    ).toBeInTheDocument();
  });

  test("sends thumbs up or down once the answer is done", async () => {
    const onFeedback = vi.fn();
    render(
      <AnswerView answer={answer({ status: "done", messageId: "m1" })} feedback={null} onFeedback={onFeedback} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Not helpful" }));

    expect(onFeedback).toHaveBeenCalledWith(-1);
  });

  test("marks the chosen rating as pressed", () => {
    render(
      <AnswerView answer={answer({ status: "done", messageId: "m1" })} feedback={1} onFeedback={vi.fn()} />,
    );

    expect(screen.getByRole("button", { name: "Helpful" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Not helpful" })).toHaveAttribute("aria-pressed", "false");
  });

  test("shows the server's message when the answer fails", () => {
    const error = { code: "internal" as const, message: "Something went wrong on our side." };
    render(<AnswerView answer={answer({ status: "error", error })} />);

    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong on our side.");
  });

  test("renders each card", () => {
    render(<AnswerView answer={answer({ status: "done", cards: [STAT, ODDS, VALUE] })} />);

    expect(screen.getByText("Saka — away, 2026/27")).toBeInTheDocument();
    expect(screen.getByText("Total goals 2.5")).toBeInTheDocument();
    expect(screen.getByText("Estimate, not advice.")).toBeInTheDocument();
  });
});
