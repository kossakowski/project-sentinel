// Defense-in-depth URL sanitiser for hrefs that originate from external
// feeds (RSS / Google News / Telegram). React does NOT strip dangerous schemes
// from `href` attributes — only console-warns in dev — so we validate the
// scheme ourselves before rendering a link.

/**
 * Returns the URL unchanged when it parses cleanly as an http(s) URL, and
 * `null` otherwise. Callers should render a plain-text fallback (or hide the
 * link entirely) when this returns null.
 */
export function safeHref(url: string | null | undefined): string | null {
  if (typeof url !== "string" || url.length === 0) return null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return url;
    }
    return null;
  } catch {
    return null;
  }
}
