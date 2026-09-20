# Independent review of the version-2 held-out corpus

Review date: 2026-09-20

## Scope and review basis

- I reviewed `tests/fixtures/model_comparison_v2_holdout.yaml` against the policy described in `docs/ideas/model-comparison-v2-plan.md` and implemented in `sentinel/eval/clarified_policy.py`.
- I determined ground truth from each current article's title and summary, using earlier reports only to assess incident identity. I did not use model predictions.
- I did not inspect development fixtures, earlier paid results, or old-runtime source prompts. I made no network, paid-provider, or production calls.
- A recommendation of `reviewed` below means independently assistant-reviewed. It does not mean human-approved.

## Result

- Total cases reviewed: **64**.
- Recommended for `label_status: reviewed`: **63**.
- Excluded pending clarification or correction: **1**.
- Blocking operator-choice cases found: **0**. The corpus contains neither a near-border strike case nor a neutralised Russian ground-drone case.
- Cases explicitly synthetic and not human-approved: **64 of 64**.

The single excluded case is `v2h-en-01-c`. The phrase identifying the radar strike as Lithuanian is grammatically compatible with either a Lithuanian location or merely a Lithuanian asset. The policy says asset nationality does not establish impact geography, while the ordinary reading can locate the strike in Lithuania. This makes the expected empty attack and affected-country fields non-deterministic from the current article alone. The case should be rewritten to state either the location or the lack of a stated location, then reviewed again. Its score band, episode relation, notification behavior, protection, and status are otherwise supported.

## Cross-corpus checks

| Check | Result |
|---|---:|
| Unique case IDs | 64/64 |
| Holdout split | 64/64 |
| Four reports per sequence | 16/16 sequences |
| Whole-sequence split consistency | 16/16 sequences |
| Chronological publication/fetch order within sequences | 16/16 sequences |
| Valid prior `same_as` target in the same sequence | 18/18 references |
| Verbatim provenance evidence present in title/summary | 128/128 excerpts |
| Synthetic provenance kind, source type, and URL scheme | 64/64 cases |
| Provisional rather than human-approved status | 64/64 cases |
| Content/article language agreement | 64/64 cases |
| PL / EN / UK / RU balance | 16 / 16 / 16 / 16 |
| Score-band support | 64/64 cases |
| Episode relation and notification support | 64/64 cases |
| Full factual-label support without blocking ambiguity | 63/64 cases |

The notification distribution is 32 initial, 24 silent, and 8 update. The relation distribution is 46 new and 18 same. All eight update decisions are material escalations of an explicitly linked continuing episode; high-severity paraphrases without new danger remain silent.

## Per-case decisions

`reviewed` means all expected fields are supported by the current source text and permitted sequence context. `exclude` means that at least one ground-truth field is ambiguous and should not be scored until the source text or expected label is corrected.

| Case ID | Recommendation | Review decision |
|---|---|---|
| v2h-pl-01-a | reviewed | Facts, score band, and new initial notification are supported. |
| v2h-pl-01-b | reviewed | Facts, score band, and new initial notification are supported. |
| v2h-pl-01-c | reviewed | Reaction-only facts, same-episode relation, and silence are supported without importing earlier geography. |
| v2h-pl-01-d | reviewed | Facts, score band, and independent new initial notification are supported. |
| v2h-pl-02-a | reviewed | Explicit active resident order supports the facts, critical band, and initial notification. |
| v2h-pl-02-b | reviewed | Explicit continuation supports the same-episode relation and silent duplicate treatment. |
| v2h-pl-02-c | reviewed | Explicit same-object impact supports escalation and an update notification. |
| v2h-pl-02-d | reviewed | Civilian, non-hostile, concluded local incident supports the low band and silence. |
| v2h-pl-03-a | reviewed | Ended false-warning episode supports resolved status, low band, and silence. |
| v2h-pl-03-b | reviewed | Explicitly separate new wave supports a new critical initial notification. |
| v2h-pl-03-c | reviewed | Explicit continuation without new development supports a silent duplicate. |
| v2h-pl-03-d | reviewed | Facts, score band, and independent new initial notification are supported. |
| v2h-pl-04-a | reviewed | Nationality and destination are correctly excluded from attack geography. |
| v2h-pl-04-b | reviewed | Active hostile territorial incursion supports the critical band and initial notification. |
| v2h-pl-04-c | reviewed | Explicit same-weapon impact supports escalation and an update notification. |
| v2h-pl-04-d | reviewed | Facts, score band, and independent new initial notification are supported. |
| v2h-en-01-a | reviewed | Facts, score band, and new initial notification are supported. |
| v2h-en-01-b | reviewed | Facts, score band, and new initial notification are supported. |
| v2h-en-01-c | exclude | Attack location versus asset nationality is ambiguous in the current article; two geography fields lack deterministic ground truth. |
| v2h-en-01-d | reviewed | Facts, score band, and independent new initial notification are supported. |
| v2h-en-02-a | reviewed | Explicit active resident order supports the facts, critical band, and initial notification. |
| v2h-en-02-b | reviewed | Explicit continuation supports the same-episode relation and silent duplicate treatment. |
| v2h-en-02-c | reviewed | Explicit same-object impact supports escalation and an update notification. |
| v2h-en-02-d | reviewed | Civilian, non-hostile, concluded local incident supports the low band and silence. |
| v2h-en-03-a | reviewed | Ended false-warning episode supports resolved status, low band, and silence. |
| v2h-en-03-b | reviewed | Explicitly separate new wave supports a new critical initial notification. |
| v2h-en-03-c | reviewed | Explicit continuation without new development supports a silent duplicate. |
| v2h-en-03-d | reviewed | Facts, score band, and independent new initial notification are supported. |
| v2h-en-04-a | reviewed | Nationality, destination, and query metadata are correctly excluded from attack geography. |
| v2h-en-04-b | reviewed | Active hostile territorial incursion supports the critical band and initial notification. |
| v2h-en-04-c | reviewed | Explicit same-weapon impact supports escalation and an update notification. |
| v2h-en-04-d | reviewed | Facts, score band, and independent new initial notification are supported. |
| v2h-uk-01-a | reviewed | Facts, score band, and new initial notification are supported. |
| v2h-uk-01-b | reviewed | Facts, score band, and new initial notification are supported. |
| v2h-uk-01-c | reviewed | Concluded conventional exercise supports historical status, low band, and silence. |
| v2h-uk-01-d | reviewed | Facts, score band, and independent new initial notification are supported. |
| v2h-uk-02-a | reviewed | Explicit active resident order supports the facts, critical band, and initial notification. |
| v2h-uk-02-b | reviewed | Explicit continuation supports the same-episode relation and silent duplicate treatment. |
| v2h-uk-02-c | reviewed | Explicit same-object impact supports escalation and an update notification. |
| v2h-uk-02-d | reviewed | Remote attack without monitored-country effects supports the low band and silence. |
| v2h-uk-03-a | reviewed | Ended false-warning episode supports resolved status, low band, and silence. |
| v2h-uk-03-b | reviewed | Explicitly separate new wave supports a new critical initial notification. |
| v2h-uk-03-c | reviewed | Explicit continuation without new development supports a silent duplicate. |
| v2h-uk-03-d | reviewed | Facts, score band, and independent new initial notification are supported. |
| v2h-uk-04-a | reviewed | Nationality, destination, and query metadata are correctly excluded from attack geography. |
| v2h-uk-04-b | reviewed | Active hostile territorial incursion supports the critical band and initial notification. |
| v2h-uk-04-c | reviewed | Explicit same-weapon impact supports escalation and an update notification. |
| v2h-uk-04-d | reviewed | Facts, score band, and independent new initial notification are supported. |
| v2h-ru-01-a | reviewed | Facts, score band, and new initial notification are supported. |
| v2h-ru-01-b | reviewed | Facts, score band, and new initial notification are supported. |
| v2h-ru-01-c | reviewed | Remote attack without monitored-country effects supports the low band and silence. |
| v2h-ru-01-d | reviewed | Facts, score band, and independent new initial notification are supported. |
| v2h-ru-02-a | reviewed | Explicit active resident order supports the facts, critical band, and initial notification. |
| v2h-ru-02-b | reviewed | Explicit continuation supports the same-episode relation and silent duplicate treatment. |
| v2h-ru-02-c | reviewed | Explicit same-object impact supports escalation and an update notification. |
| v2h-ru-02-d | reviewed | Concluded conventional exercise supports historical status, low band, and silence. |
| v2h-ru-03-a | reviewed | Ended false-warning episode supports resolved status, low band, and silence. |
| v2h-ru-03-b | reviewed | Explicitly separate new wave supports a new critical initial notification. |
| v2h-ru-03-c | reviewed | Explicit continuation without new development supports a silent duplicate. |
| v2h-ru-03-d | reviewed | Facts, score band, and independent new initial notification are supported. |
| v2h-ru-04-a | reviewed | Nationality, destination, and query metadata are correctly excluded from attack geography. |
| v2h-ru-04-b | reviewed | Active hostile territorial incursion supports the critical band and initial notification. |
| v2h-ru-04-c | reviewed | Explicit same-weapon impact supports escalation and an update notification. |
| v2h-ru-04-d | reviewed | Facts, score band, and independent new initial notification are supported. |

## Recommended next action

- Mark the 63 `reviewed` cases as independently assistant-reviewed, not human-approved.
- Keep `v2h-en-01-c` provisional and out of scoring until its current-article geography is made unambiguous and independently re-reviewed.
