# Archive — Historic Implementation Scaffolding

> ⚠️ **This folder is NOT current truth.** Everything here is a snapshot of a
> *completed* implementation effort — specs, handoffs, and the original phase-1
> build prompts. It is kept for provenance and historical context only. For how
> the system behaves **today**, always read the living docs under
> [`../explanation/`](../explanation/), [`../reference/`](../reference/),
> [`../how-to/`](../how-to/), and the dashboard spec at [`../../SPEC.md`](../../SPEC.md).

These documents describe *intended* changes at the time they were written. The
code has since shipped and, in places, drifted from the wording here (thresholds
retuned, windows changed, channels added). Do **not** treat any number, window,
or behaviour stated in an archived file as authoritative — verify against the
living docs and the source.

## What's in here, and where the living equivalent now lives

| Archived item | What it was | Current truth now lives in |
|---|---|---|
| [`SPEC_ALERT_GROUPING.md`](SPEC_ALERT_GROUPING.md) | The completed 3-phase alert-grouping / event-grouping effort (corroborator window widening, dashboard event grouping, audit-skill event grouping). | [`../explanation/architecture.md`](../explanation/architecture.md), [`../explanation/pipeline.md`](../explanation/pipeline.md), and the dashboard spec [`../../SPEC.md`](../../SPEC.md). |
| [`SPEC_ASYNC_REFACTOR.md`](SPEC_ASYNC_REFACTOR.md) | The completed async refactor of blocking calls (async Anthropic client, `asyncio.to_thread` for Twilio, single cycle lock). | [`../explanation/architecture.md`](../explanation/architecture.md). |
| [`HANDOFF_audit-findings-2026-05-23.md`](HANDOFF_audit-findings-2026-05-23.md) | A historical audit handoff from the 2026-05-23 `/sentinel-audit` run (nuclear-keyword gap and quality findings). | Tracked/resolved in [`../../TODO.md`](../../TODO.md); audit process in the `/sentinel-audit` skill. |
| [`prompts/`](prompts/) | The original phase-1 implementation prompts — spec-forge / code-refiner scaffolding used to bootstrap the build (per-agent build prompts, audit-remediation, corroboration-removal, the audit skill draft). | Superseded by the shipped code under `sentinel/` and the living docs; no living equivalent — kept for provenance only. |

## A note on source-code citations

Several source files and tests cite **`SPEC_ALERT_GROUPING.md`** *by name* (e.g.
`SPEC_ALERT_GROUPING.md req 2.4`) as provenance for why a piece of behaviour
exists. Those citations were intentionally left unchanged — they are reference
labels, not file paths. The file they point to now lives **here**, at
[`docs/archive/SPEC_ALERT_GROUPING.md`](SPEC_ALERT_GROUPING.md). If you are
hunting for a `SPEC_ALERT_GROUPING.md` reference found in code, this is where it
moved to.
