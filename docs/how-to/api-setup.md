# API Setup Guide

This guide covers setting up all external service accounts needed by Project Sentinel.

## 1. Direct OpenAI API (Luna)

The local configuration selects `classification.provider: openai` and
`gpt-5.6-luna`. This requires paid OpenAI API access, separately from a ChatGPT or
Codex subscription. The key is used by classification, the existing article-quality gate and, only
when needed, one bounded Polish-summary translation. OpenAI mode does not require an Anthropic key.

Finish coding/offline checks first. For assisted setup, use a visible Playwright
browser and select/create a dedicated **Project Sentinel** project. If more than
one organisation is available, confirm which organisation should pay. The
operator handles sign-in, private payment details and final funding confirmation.
Do not enable automatic recharge without a separate decision.

Create a project-scoped key with Responses write permission and access to the
selected model. Store it as `OPENAI_API_KEY` in the ignored local `.env`, preserving
other credentials. Never paste the key into chat, a command argument, screenshot
or a committed file. Restrict the secret file to its owner (`chmod 600 .env`).
Use the platform's current permission controls; account-specific access must be
verified by a real bounded request.

The application uses explicit reasoning `none`, standard service tier, no SDK
retries, a total deadline, strict JSON schema and `store=false`. It records model,
prompt and request hashes. There is no automatic fallback provider.

### Verify without sending alerts

First run the entirely offline check:

```bash
.venv/bin/python -m sentinel.eval.direct_luna
```

After funding and **explicit approval of a $0.25 test allowance**, run this command
with a new output filename (existing reports are never overwritten):

```bash
.venv/bin/python -m sentinel.eval.direct_luna --live --max-cost-usd 0.25 --output data/eval/luna-direct-validation.jsonl
```

This makes twenty classifier requests, plus at most one Polish-summary repair per
non-Polish result: ten identical known-miss inputs and
ten fresh synthetic cases, with fake phone/SMS/push transports and in-memory event
storage. It tests the real classifier, memory guards, grouping and notification
logic. It does not fetch real article bodies or test message delivery. Reports
include failures, message/request hashes, token usage and estimated costs.
The current runner also checks Polish output and records generic summary fallbacks
as degraded results. The reused known-miss case is not a fresh holdout. Fresh labels are engineering
expectations, not human-approved ground truth. Repeated successes do not establish
determinism or erase the historical miss.

### Budget, failure and rollback

The operator selected **$10/month** on 2026-09-20.

`classification.budget` controls a persistent SQLite ledger shared by classifier
and quality-gate requests. Keep its writable path stable across restarts and use
an absolute path on a server. Each call reserves an upper estimate before sending;
success settles token charges, including cached input. A timeout, authentication
failure or response without usable usage retains the reservation because the
charge is uncertain. Refused/incomplete answers with usage are billed too.
Uncached input conservatively includes the configured cache-write premium, so the
estimate can exceed the provider bill. The configured request cap excludes very
large contexts that would use another pricing tier.

At the monthly allowance, new paid work stops. The article remains queued, logs
explain the error, and `health.json` reports degraded classification. This is a
**detection gap**, not a successful safe classification. Provider outages, credit
exhaustion and malformed answers also leave work pending for retry. Do not delete
queued work or the usage ledger to make health appear green.

The guard is an application spending control at configured token rates, not a
provider-wide guarantee. Dashboard spend alerts do not impose a hard cap. OpenAI also supports a distinct
project hard limit; verify that **Enforce a hard limit** is enabled before calling
it an enforced cap. Enforcement can lag slightly. See [OpenAI spend limits](https://developers.openai.com/api/docs/guides/spend-limits). Other applications, purchases, tax and Twilio charges are outside this ledger.
Review rates when changing the model. Legacy Anthropic rollback retains its older
token estimate and does not use this OpenAI ledger.

Rollback explicitly selects `provider: anthropic`, the previous Haiku model and
its prior token limit, with `ANTHROPIC_API_KEY` available. The old prompt remains
available. Restore the prior incident-memory setting only as a reviewed rollback
choice. Preserve the database and alert history. See the
[migration plan](../ideas/luna-direct-api-migration-plan.md) for rollout gates.
Production deployment, secret installation and restart need separate approval.

References: [Luna model and pricing](https://developers.openai.com/api/docs/models/gpt-5.6-luna),
[structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

---

## 2. Twilio (Phone Calls & SMS)

Twilio powers the two primary alert channels: the urgency-9+ **phone call** and the SMS used for acknowledgments, updates, and the downgrade channel.

### Steps

1. Go to **https://www.twilio.com/console**
2. Sign up or log in
3. From the dashboard, note your:
   - **Account SID** (starts with `AC`)
   - **Auth Token**
4. Get a phone number:
   - Go to **Phone Numbers → Manage → Buy a Number**
   - Buy a number with **Voice** and **SMS** capabilities
   - For Polish calls: any US/EU number works, but a Polish number (+48) avoids international call costs
5. Add to `.env`:
   ```
   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
   ALERT_PHONE_NUMBER=+48XXXXXXXXX
   ```

### Polish TTS Voice

Project Sentinel uses Amazon Polly's **Ewa** voice for Polish TTS in phone calls. This is available through Twilio's `<Say>` verb with:
```xml
<Say language="pl-PL" voice="Polly.Ewa">Treść wiadomości po polsku</Say>
```

No additional Polly setup needed -- Twilio includes it.

### Verify It Works

```bash
python -c "
from twilio.rest import Client
import os
client = Client(os.environ['TWILIO_ACCOUNT_SID'], os.environ['TWILIO_AUTH_TOKEN'])
msg = client.messages.create(
    from_=os.environ['TWILIO_PHONE_NUMBER'],
    to=os.environ['ALERT_PHONE_NUMBER'],
    body='Project Sentinel test SMS'
)
print(f'SMS sent: {msg.sid}')
"
```

### Cost

- Phone number: ~$1.15/month
- Outbound call (US to Poland): ~$0.25/minute
- Outbound call (Polish number): ~$0.02/minute
- SMS to Poland: ~$0.07/message
- In practice: <$5/month unless many alerts fire

---

## 3. Expo Push (Optional — Mobile Push Channel)

Expo Push is an **optional** alert channel. Each SMS urgency tier (5–8) carries a per-tier `channel` setting (`sms` / `push` / `both`, default `both`) that selects whether that tier is delivered by Twilio SMS, by push, or by both; the urgency 9–10 call also fires a push additively. It is **off by default** and needs no account or paid plan for basic sends — Expo's push service is free.

There is no API key to obtain. The two pieces you provide are:

1. **(Optional) `EXPO_ACCESS_TOKEN`** — an Expo access token used as a bearer credential to harden sends against spoofing. Create one at **https://expo.dev → Account → Access Tokens**, then add it to `.env`:
   ```
   EXPO_ACCESS_TOKEN=your-expo-access-token
   ```
   Leave it unset for basic (unauthenticated) sends.

2. **Device push tokens** — the per-device tokens (`ExponentPushToken[...]`) that identify which phones receive alerts. These are surfaced by the companion mobile app under `mobile/`, which prints/copies the device's Expo push token. Paste each token into `alerts.push.tokens` in `config/config.yaml` and set `alerts.push.enabled: true`:
   ```yaml
   alerts:
     push:
       enabled: true
       tokens:
         - "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]"
   ```

The 5–8 tiers default to `channel: both`, so once push is enabled with a token they push immediately (alongside SMS) — no `channel` change is required. To change a tier's delivery, set its `channel` — e.g. `alerts.urgency_levels.high.channel: push` (push only, no SMS) or leave it at `both` (SMS and push). The urgency 9–10 call also fires its additive push as soon as push is enabled with a token (no `channel` needed there). While push is disabled or no token is set, every tier still sends SMS only and the 9–10 push no-ops.

See the [mobile companion app explanation](../explanation/mobile-app.md) for how to obtain a device token, and the [Configuration Reference](../reference/config-reference.md) for the full `alerts.push` block and the `channel` field.

Test it once configured with `./run.sh --test-alert push`.

---

## 4. Telegram API (Channel Monitoring)

Telegram monitoring uses a personal account via `telethon`. You do NOT need a bot -- you monitor public channels the same way a regular user would.

### Steps

1. Go to **https://my.telegram.org**
2. Log in with your phone number
3. Go to **API Development Tools**
4. Create a new application:
   - **App title:** Project Sentinel
   - **Short name:** project-sentinel
   - **Platform:** Other
   - **Description:** Military alert monitoring
5. Note your:
   - **api_id** (a number like `12345678`)
   - **api_hash** (a string like `abcdef1234567890abcdef1234567890`)
6. Add to `.env`:
   ```
   TELEGRAM_API_ID=12345678
   TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
   ```

### First-Time Authentication

The first time you run the Telegram fetcher, it will ask for your phone number and a verification code sent via Telegram. After that, a session file is created and subsequent runs don't need verification.

```bash
python -c "
import os
from telethon import TelegramClient

client = TelegramClient(
    'sentinel_session',
    int(os.environ['TELEGRAM_API_ID']),
    os.environ['TELEGRAM_API_HASH']
)

async def main():
    await client.start()
    me = await client.get_me()
    print(f'Authenticated as: {me.first_name} ({me.phone})')
    await client.disconnect()

import asyncio
asyncio.run(main())
"
```

Follow the prompts. After success, a `sentinel_session.session` file is created -- **keep this file secure**, it grants access to your Telegram account. The session base name (without the `.session` suffix) is set by `sources.telegram.session_name` in config; in **production** it lives at `/var/lib/sentinel/sentinel_session` (so the running file is `/var/lib/sentinel/sentinel_session.session`).

### Finding Channel IDs

Channel IDs in config use the format `@channel_name` (the public username). To find the username of a channel:
1. Open the channel in Telegram
2. Look at the channel info -- the username is shown as `t.me/channel_name`
3. Use `@channel_name` in config

### Monitored Channels (live config)

| Channel | ID | Language | Notes |
|---|---|---|---|
| Ukrainian Air Force | `@kpszsu` | uk | Fastest for cross-border drone/missile events |
| General Staff of Ukraine | `@GeneralStaffZSU` | uk | Official military situation updates |
| DeepState UA | `@DeepStateUA` | uk | Front-line mapping / situational reports |
| NEXTA Live | `@nexta_live` | ru | Belarusian opposition, fast on military events |

**Note:** Channel IDs may change. Verify them before configuring.

### Security Note

The Telegram session file (`sentinel_session.session`) is equivalent to being logged into your Telegram account. Protect it:
- Set permissions: `chmod 600 sentinel_session.session`
- Never commit it to git (add to `.gitignore`)
- If compromised, revoke all sessions in Telegram settings

---

## 5. GDELT API

**No setup needed.** The GDELT DOC 2.0 API is free and requires no API key or registration. Endpoint: `https://api.gdeltproject.org/api/v2/doc/doc` (GDELT is currently **disabled** in production — `sources.gdelt.enabled: false` — due to IP-level throttling, but no credentials are required if you re-enable it.)

## 6. Google News RSS

**No setup needed.** Google News RSS feeds are public and free.

---

## Complete `.env` Template

```bash
# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX

# Alert recipient
ALERT_PHONE_NUMBER=+48XXXXXXXXX

# Anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxx

# Telegram
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890

# Expo Push (optional — device push tokens go in alerts.push.tokens, not here)
# EXPO_ACCESS_TOKEN=your-expo-access-token
```
