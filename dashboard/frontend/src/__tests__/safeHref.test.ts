// Tests for safeHref — defends against XSS via untrusted source_url fields
// from external feeds (RSS / Google News / Telegram).

import { describe, expect, it } from "vitest";

import { safeHref } from "../utils/safeHref";

describe("safeHref", () => {
  it("accepts http and https URLs unchanged", () => {
    expect(safeHref("http://example.com/article")).toBe(
      "http://example.com/article",
    );
    expect(safeHref("https://example.com/article")).toBe(
      "https://example.com/article",
    );
    expect(safeHref("https://example.com/path?with=query#frag")).toBe(
      "https://example.com/path?with=query#frag",
    );
  });

  it("rejects javascript: scheme", () => {
    expect(safeHref("javascript:alert(1)")).toBeNull();
    // Mixed case / whitespace must still be caught — URL parsing normalises
    // case but the protocol check is exact-match against the parsed protocol.
    expect(safeHref("JavaScript:alert(1)")).toBeNull();
  });

  it("rejects data: scheme", () => {
    expect(safeHref("data:text/html,<script>alert(1)</script>")).toBeNull();
  });

  it("rejects ftp: scheme", () => {
    expect(safeHref("ftp://example.com/file")).toBeNull();
  });

  it("rejects malformed and empty URLs", () => {
    expect(safeHref("not a url")).toBeNull();
    expect(safeHref("")).toBeNull();
    expect(safeHref(null)).toBeNull();
    expect(safeHref(undefined)).toBeNull();
  });

  it("rejects file: scheme as defense-in-depth", () => {
    expect(safeHref("file:///etc/passwd")).toBeNull();
  });
});
