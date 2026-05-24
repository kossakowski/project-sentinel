export const WARSAW_TZ = "Europe/Warsaw";

const DATE_TIME_FMT = new Intl.DateTimeFormat("en-CA", {
  timeZone: WARSAW_TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const DATE_TIME_SECONDS_FMT = new Intl.DateTimeFormat("en-CA", {
  timeZone: WARSAW_TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const TIME_ONLY_FMT = new Intl.DateTimeFormat("en-GB", {
  timeZone: WARSAW_TZ,
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function render(iso: string | null | undefined, formatter: Intl.DateTimeFormat): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  // en-CA produces "YYYY-MM-DD, HH:mm" — drop the comma for compactness.
  return formatter.format(parsed).replace(", ", " ");
}

/** YYYY-MM-DD HH:mm in Europe/Warsaw. */
export function formatWarsaw(iso: string | null | undefined): string {
  return render(iso, DATE_TIME_FMT);
}

/** YYYY-MM-DD HH:mm:ss in Europe/Warsaw. */
export function formatWarsawSeconds(iso: string | null | undefined): string {
  return render(iso, DATE_TIME_SECONDS_FMT);
}

/** HH:mm in Europe/Warsaw. */
export function formatWarsawTime(iso: string | null | undefined): string {
  return render(iso, TIME_ONLY_FMT);
}
