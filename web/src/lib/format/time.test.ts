import { describe, expect, test } from "vitest";
import { formatUkDateTime, formatUkTime } from "./time";

describe("formatUkDateTime", () => {
  test("renders a UTC time in British Summer Time", () => {
    expect(formatUkDateTime("2026-10-17T14:00:00Z")).toBe("Sat 17 Oct, 15:00");
  });

  test("renders a UTC time in Greenwich Mean Time after the clocks change", () => {
    expect(formatUkDateTime("2026-11-01T15:00:00Z")).toBe("Sun 1 Nov, 15:00");
  });

  test("uses the UK date when UTC is still the day before", () => {
    expect(formatUkDateTime("2026-10-08T23:00:00Z")).toBe("Fri 9 Oct, 00:00");
  });
});

describe("formatUkTime", () => {
  test("renders only the UK clock time", () => {
    expect(formatUkTime("2026-10-17T14:05:00Z")).toBe("15:05");
  });
});
