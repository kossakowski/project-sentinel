import { describe, expect, it } from "vitest";

import {
  formatWarsaw,
  formatWarsawSeconds,
  formatWarsawTime,
} from "../utils/datetime";

describe("formatWarsaw", () => {
  it("converts UTC ISO to Europe/Warsaw in summer (CEST)", () => {
    // 2026-05-22 10:04 UTC → 12:04 Warsaw (UTC+2 CEST).
    expect(formatWarsaw("2026-05-22T10:04:00+00:00")).toBe("2026-05-22 12:04");
  });

  it("converts UTC ISO to Europe/Warsaw in winter (CET)", () => {
    // 2026-01-15 10:00 UTC → 11:00 Warsaw (UTC+1 CET).
    expect(formatWarsaw("2026-01-15T10:00:00+00:00")).toBe("2026-01-15 11:00");
  });

  it("returns em dash for null/undefined/empty input", () => {
    expect(formatWarsaw(null)).toBe("—");
    expect(formatWarsaw(undefined)).toBe("—");
    expect(formatWarsaw("")).toBe("—");
  });

  it("returns the raw string for unparseable input", () => {
    expect(formatWarsaw("not-a-date")).toBe("not-a-date");
  });
});

describe("formatWarsawSeconds", () => {
  it("includes seconds", () => {
    expect(formatWarsawSeconds("2026-05-22T10:04:30+00:00")).toBe(
      "2026-05-22 12:04:30",
    );
  });
});

describe("formatWarsawTime", () => {
  it("renders HH:mm only", () => {
    expect(formatWarsawTime("2026-05-22T10:04:00+00:00")).toBe("12:04");
  });
});
