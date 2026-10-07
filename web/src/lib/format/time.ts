// Times arrive as ISO 8601 UTC; users see UK time (contracts/README.md).
const UK_TIME_ZONE = "Europe/London";

const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: UK_TIME_ZONE,
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const timeFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: UK_TIME_ZONE,
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function partsOf(format: Intl.DateTimeFormat, iso: string): Record<string, string> {
  const entries = format.formatToParts(new Date(iso)).map((part) => [part.type, part.value]);
  return Object.fromEntries(entries);
}

/** "Sat 17 Oct, 15:00" in UK time. */
export function formatUkDateTime(iso: string): string {
  const p = partsOf(dateTimeFormat, iso);
  return `${p.weekday} ${p.day} ${p.month}, ${p.hour}:${p.minute}`;
}

/** "15:00" in UK time. */
export function formatUkTime(iso: string): string {
  const p = partsOf(timeFormat, iso);
  return `${p.hour}:${p.minute}`;
}
