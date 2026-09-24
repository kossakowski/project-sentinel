# Full-text second read in production — design notes (NOT a spec)

Status: deferred on 2026-09-25. Write a production spec (`/spec-forge`) only after the eval in
`SPEC.md` shows which variant (B and/or which C definition) passes the pre-registered rule on the
operator's labels. These notes keep the operator's decisions and the pitfalls that three
independent verification rounds found, so the future spec starts from them.

## Operator decisions (2026-09-24)

- Switches per variant in `config/config.yaml`: `off` / `shadow` (read and store, change no alert) /
  `active`. Default `off`. Modes written as quoted strings (a bare YAML `off` parses as `False`).
- **B** runs only after the call, only for an event that actually received a phone call in that
  cycle, at most once per event. It never delays or cancels the call.
- **B correction message** carries only the new score and the source link, never the model's
  summary: `Pełny artykuł: model ocenia teraz 6/10. Sprawdź źródła: <link>`. No words such as
  "odwołane" or "fałszywy alarm".
- **C** may raise 5–8 into a call and may lower (suppress an SMS/push). C runs after the cycle's
  calls are dispatched: the calls of the same cycle never wait for C; the next cycle may start at
  most ~30 s later. The SMS/push of a C article waits up to ~20 s for its second read.
- A failed or slow full-text fetch never blocks or delays a call; the first read then applies.
- Monthly model budget raised to $30 (commit 31acd3a on master).

## Pitfalls found by verification (must be handled by the future spec)

1. **Google News decoder can hang forever.** `googlenewsdecoder` 0.1.7 calls `requests.get`/
   `requests.post` without a timeout. Never run it on asyncio's default executor
   (`asyncio.to_thread`): Twilio calls use that pool. Use a small dedicated pool, detect when all
   its threads are stuck, and skip resolution then. (The enricher already calls the decoder
   synchronously on the event loop today — a pre-existing risk worth its own fix.)
2. **httpx timeouts are per chunk, not total.** Wrap the whole fetch (resolution, GET, extraction)
   in one `asyncio.timeout`. Cap the body size (stream or check Content-Length).
3. **Which knob gates the call.** The phone call is decided by the phone_call level's own
   `alerts.urgency_levels.<level>.corroboration_required` in `AlertStateMachine._determine_action`,
   not by `classification.corroboration_required` (that one only labels `alert_status`). Any guard
   about corroboration must read the right knob.
4. **C must not remove corroboration.** An article C lowers below 5 creates no event and stops
   counting as an independent source; a changed incident-memory decision can also move it away.
   Either keep C out of corroboration-relevant articles or never let C lower/regroup when a second
   source is required.
5. **Setting a C article aside can delay another article's call** when that article is the
   second source the call needs. "Calls of the same cycle never wait for C" must hold in that case
   too.
6. **Stale incident-memory candidates.** A set-aside article validated later must use candidates
   recomputed after the dispatch, but a kept first result must be validated against the
   candidates its decision was made on (else `validate()` downgrades a valid match to
   `uncertain`).
7. **B target must be the article that caused the call** (first read ≥ call tier). Retry calls on
   old unacknowledged events are triggered by new, possibly weak articles — B must not read those.
8. **One `second_read` column holds one record.** B and shadow-C writes must not overwrite each
   other; "once per event" depends on that record.
9. **Correction sends need their own time bound** and must not use the default executor
   (`TwilioClient.send_sms` has no timeout). Respect `testing.dry_run`. `send_push` returns `None`
   by design when push is disabled — not an error.
10. **Budget.** Stop second reads at a fraction of the monthly cap; timed-out requests keep their
    whole reservation in the ledger; shadow reads also spend.
11. **Existing test pipelines** are built with `SentinelPipeline.__new__`; new attributes need
    class-level defaults.
12. Eval vs production gap: production caps second reads per article and per cycle and does not
    retry; the eval assumes every triggered read happens. Treat eval gains as an upper bound.
