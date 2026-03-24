# Corroboration Removal: Implementation Spec

**Status:** BLOCKED — deploy AFTER classifier prompt fixes (Workstream B) are live and validated
**Prerequisite:** Workstream B deployed, at least 24h of production data showing correct urgency scoring

---

## What to change

### 1. Config change: `/etc/sentinel/config.yaml`

```yaml
# BEFORE
alerts:
  urgency_levels:
    critical:
      min_score: 9
      action: phone_call
      corroboration_required: 2    # ← change this
      retry_attempts: 3
      retry_interval_minutes: 5
      fallback: sms

# AFTER
alerts:
  urgency_levels:
    critical:
      min_score: 9
      action: phone_call
      corroboration_required: 1    # ← single source is enough
      retry_attempts: 3
      retry_interval_minutes: 5
      fallback: sms
```

Same change in `config/config.example.yaml` (repo template).

### 2. Code change: `sentinel/alerts/state_machine.py`

In `_determine_action()` (~line 204-235), the logic currently does:

```
if action == "phone_call":
    if source_count >= corroboration_required:
        return "phone_call"
    else:
        return "sms"  # fallback: not enough sources yet
```

With `corroboration_required: 1`, this naturally works — any event with at least 1 source (which is always true) passes. **No code change needed.** Config-only.

### 3. What to verify before deploying this

Run a /sentinel-audit (or manual DB check) after Workstream B has been live for 24h:

```sql
-- Check: are urgency 9-10 classifications now limited to genuine PL/LT/LV/EE threats?
SELECT c.urgency_score, c.affected_countries, c.event_type, a.title, a.source_name
FROM classifications c JOIN articles a ON c.article_id = a.id
WHERE c.urgency_score >= 9
  AND c.classified_at > datetime('now', '-24 hours')
ORDER BY c.classified_at DESC;
```

If any rows show affected_countries=["UA"] or clickbait titles with urgency 9+, the classifier fixes haven't fully worked. Do NOT remove corroboration until this query returns only genuine threats.

### 4. Deployment

```bash
ssh -p 2222 deploy@178.104.76.254
sudo nano /etc/sentinel/config.yaml
# Change corroboration_required: 2 → 1 under critical tier
sudo systemctl restart sentinel
```

### 5. Rollback

Change it back to 2, restart. Instant.

---

## Also add Finland and Romania (separate task)

When ready, expand monitoring scope:

- `monitoring.target_countries`: add `{code: FI, name: Finland, name_native: Suomi}` and `{code: RO, name: Romania, name_native: România}`
- Classifier SYSTEM_PROMPT: add Finland and Romania to the target country list
- Google News queries: add `"military attack Finland"`, `"military attack Romania"`
- GDELT FIPS codes: FI→FI, RO→RO (happen to match ISO)

This is a separate change set — do not bundle with corroboration removal.
