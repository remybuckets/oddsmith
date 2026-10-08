import { Card as UiCard, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import type { Card, Fixture, OddsCard, SourceRef, StatCard, ValueCard } from "@/lib/api/types";
import { formatUkDateTime } from "@/lib/format/time";
import { cn } from "@/lib/utils";

const MAX_BOOKMAKERS = 4;
const FORM_WORDS = { W: "won", D: "drawn", L: "lost" } as const;
type FormResult = keyof typeof FORM_WORDS;

const FORM_STYLES: Record<FormResult, string> = {
  W: "bg-primary text-primary-foreground",
  D: "bg-secondary text-secondary-foreground",
  L: "bg-muted text-muted-foreground",
};

function isFormResult(value: string): value is FormResult {
  return value in FORM_WORDS;
}

export function FormStrip({ form }: { form: string }) {
  const results = [...form].filter(isFormResult);
  const label = `Form: ${results.map((r) => FORM_WORDS[r]).join(", ")}`;
  return (
    <ul aria-label={label} className="flex gap-1">
      {results.map((result, index) => (
        <li
          key={index}
          aria-label={FORM_WORDS[result]}
          className={cn("grid size-6 place-items-center rounded text-xs font-semibold", FORM_STYLES[result])}
        >
          {result}
        </li>
      ))}
    </ul>
  );
}

function SourceFooter({ source }: { source: SourceRef }) {
  return (
    <CardFooter className="flex-col items-start gap-0.5 text-xs text-muted-foreground">
      <span>{`${source.source} · as of ${formatUkDateTime(source.as_of)}`}</span>
      {source.is_stale && <span className="text-card-red">This data may be out of date.</span>}
    </CardFooter>
  );
}

function fixtureLine(fixture: Fixture): string {
  return `${fixture.home.short_name} v ${fixture.away.short_name} · ${formatUkDateTime(fixture.kickoff_at)}`;
}

function marketLabel(market: OddsCard["market"], line: number | null | undefined): string {
  if (market === "h2h") return "Match result";
  if (market === "btts") return "Both teams to score";
  return line == null ? "Total goals" : `Total goals ${line}`;
}

function formatPrice(price: number): string {
  return price.toFixed(2);
}

function formatPercent(probability: number): string {
  return `${Math.round(probability * 100)}%`;
}

function formatEdge(edge: number): string {
  const points = (edge * 100).toFixed(1);
  return `${edge >= 0 ? "+" : ""}${points} pts`;
}

function StatCardView({ card }: { card: StatCard }) {
  return (
    <UiCard size="sm">
      <CardHeader>
        <CardTitle>{card.title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {card.form && <FormStrip form={card.form} />}
        <table className="w-full text-sm">
          <thead>
            <tr>
              {card.columns.map((column) => (
                <th key={column} scope="col" className="pb-1 text-left font-medium text-muted-foreground">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {card.rows.map((row, rowIndex) => (
              <tr key={rowIndex} className="border-t">
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} className="py-1 tabular-nums">
                    {cell ?? "–"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
      <SourceFooter source={card.source} />
    </UiCard>
  );
}

function OddsCardView({ card }: { card: OddsCard }) {
  return (
    <UiCard size="sm">
      <CardHeader>
        <CardTitle>{marketLabel(card.market, card.line)}</CardTitle>
        <p className="text-xs text-muted-foreground">{fixtureLine(card.fixture)}</p>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {card.selections.map((selection) => (
          <div key={selection.selection} className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{selection.label}</span>
              <span
                data-best="true"
                className="rounded bg-primary px-2 py-0.5 text-sm font-semibold text-primary-foreground tabular-nums"
              >
                {`Best ${formatPrice(selection.best_price)} · ${selection.best_bookmaker}`}
              </span>
            </div>
            <ul className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-sm text-muted-foreground">
              {selection.prices.slice(0, MAX_BOOKMAKERS).map((price) => (
                <li key={price.bookmaker} className="flex justify-between">
                  <span>{price.bookmaker}</span>
                  <span className="tabular-nums">{formatPrice(price.price)}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </CardContent>
      <SourceFooter source={card.source} />
    </UiCard>
  );
}

function ValueCardView({ card }: { card: ValueCard }) {
  return (
    <UiCard size="sm">
      <CardHeader>
        <CardTitle>{`${card.label} · ${marketLabel(card.market, card.line)}`}</CardTitle>
        <p className="text-xs text-muted-foreground">{fixtureLine(card.fixture)}</p>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span>{`Model ${formatPercent(card.model_probability)}`}</span>
          <span className="text-muted-foreground">vs</span>
          <span>{`Market ${formatPercent(card.implied_probability)}`}</span>
          <span
            data-highlighted={String(card.is_highlighted)}
            className={cn(
              "rounded px-2 py-0.5 font-semibold tabular-nums",
              card.is_highlighted ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
            )}
          >
            {`Edge ${formatEdge(card.edge)}`}
          </span>
        </div>
        <p className="text-muted-foreground">
          {`Best ${formatPrice(card.best_price)} · ${card.best_bookmaker}`}
        </p>
        {/* Always shown, whatever the card says (SPEC compliance). */}
        <p className="font-medium">Estimate, not advice.</p>
      </CardContent>
      <SourceFooter source={card.source} />
    </UiCard>
  );
}

export function CardView({ card }: { card: Card }) {
  switch (card.card_type) {
    case "stat":
      return <StatCardView card={card} />;
    case "odds":
      return <OddsCardView card={card} />;
    case "value":
      return <ValueCardView card={card} />;
  }
}
