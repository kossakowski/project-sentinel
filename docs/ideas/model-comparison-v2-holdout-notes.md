# Version 2 holdout construction notes

This note records the inventory and policy boundaries of
`tests/fixtures/model_comparison_v2_holdout.yaml`. It does not reproduce the
held-out report text.

## Inventory

- The fixture contains exactly 64 cases in 16 independent four-report sequences.
- Every case uses the `holdout` split. Independent review marked 63 cases
  `reviewed` and one case `disputed`; none is human-approved. Synthetic
  provenance, unique `synthetic://` URLs, and the `synthetic` source type remain
  unchanged.
- There are four sequences and 16 cases in each of Polish, English, Ukrainian,
  and Russian. Every sequence contains only one content language.
- There are 32 clearly critical cases, 16 middle-tier precaution cases, and 16
  negative cases with an urgency ceiling below 5.
- Notifications comprise 32 initial notices, 24 silent outcomes, and eight
  updates. Relations comprise 46 new reports and 18 same-episode reports.
- The factual protection labels comprise 20 `official_warning`, 16 `precaution`,
  and 28 `none` cases. The status labels comprise 50 `active`, six `resolved`,
  two `historical`, and six `unclear` cases.
- All 64 cases include short evidence excerpts that occur verbatim in their
  supplied title or summary.

## Diagnostic coverage

- The sequences exercise paraphrase duplicates, material escalation within one
  episode, unrelated locations and countries in the same replay stream, and a
  newly active wave after an explicitly ended earlier episode.
- Negative controls separate nationality, train destination, and source-query
  wording from physical attack geography. Other controls cover political alarm
  language without a new danger fact, civilian ground objects with no hostility,
  routine non-nuclear exercises, and distant strikes without a monitored-country
  incident or protective response.
- Middle-tier controls locate the physical attack in Ukraine while assigning the
  monitored country only a concrete precautionary response.
- Critical controls use either a confirmed hostile impact or incursion in Poland,
  Lithuania, Latvia, or Estonia, or an explicit active official resident warning.

## Policy ambiguity flags

- No case uses a strike inside Ukraine merely because it is close to the Polish
  border. That unresolved scoring choice remains outside this fixture.
- No case asks how to score a Russian drone after it has been neutralised with no
  remaining danger. That unresolved scoring choice remains outside this fixture.
- The labels are diagnostic annotations only. Independent review covered all 64
  cases, but it does not constitute human approval; the single disputed case
  remains excluded from trusted-gold use.
- The synthetic balance is deliberate and is not representative of real traffic;
  success on this fixture cannot establish real-world accuracy.
