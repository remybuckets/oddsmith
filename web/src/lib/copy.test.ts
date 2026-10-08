import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, test } from "vitest";

// SPEC "Compliance": never "guaranteed", "lock", "banker" or "sure thing" anywhere in the UI.
const BANNED = /\b(lock|locks|banker|bankers|guaranteed|guarantee|sure thing|can't lose)\b/i;
const SRC = path.resolve(__dirname, "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    const isSource = /\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name);
    return isSource ? [full] : [];
  });
}

describe("user-facing copy", () => {
  test.each(sourceFiles(SRC).map((file) => [path.relative(SRC, file), file]))(
    "%s uses no banned betting words",
    (_name, file) => {
      expect(readFileSync(file, "utf8")).not.toMatch(BANNED);
    },
  );
});
