# API Setup Guide

Last verified: 2026-10-03 (deployed commit 6429124)

This guide covers the external service accounts Project Sentinel uses. OpenAI is the live classifier. Anthropic is only a legacy rollback path. OpenRouter is only for offline model comparison.

Contents:
1. [Direct OpenAI API (Luna)](#1-direct-openai-api-luna)
2. [Twilio (Phone Calls & SMS)](#2-twilio-phone-calls--sms)
3. [Expo Push (Mobile Push Channel)](#3-expo-push-mobile-push-channel)
4. [Telegram API (Channel Monitoring)](#4-telegram-api-channel-monitoring)
5. [GDELT API](#5-gdelt-api)
6. [Google News RSS](#6-google-news-rss)
7. [OpenRouter (Optional, Evals Only)](#7-openrouter-optional-evals-only)
8. [Complete `.env` Template](#complete-env-template)

The production service reads its secrets from env files under `/etc/sentinel/`; see the [server runbook](server-runbook.md). Local runs read the git-ignored `.env` in the repo folder.

## 1. Direct OpenAI API (Luna)

Production (`config/config.yaml`, deployed since 2026-09-20) and the template
(`config/config.example.yaml`) both select `classification.provider: openai` and
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

After funding and explicit approval of a $0.25 test allowance, run this command
with a new output filename (existing reports are never overwritten):

```bash
.venv/bin/python -m sentinel.eval.direct_luna --config data/config.local.yaml --live --max-cost-usd 0.25 --output data/eval/luna-direct-validation.jsonl
```

Pass a local config (see [Getting Started, step 4](../tutorials/getting-started.md#4-create-a-local-config)).
The default `--config config/config.yaml` is the production config. Its budget ledger
path is `/var/lib/sentinel/...`, which does not exist on a workstation, so the live
check fails before the first request. If the config itself loads, the failed run still leaves an empty `--output` file
behind, so delete it or pick a new `--output` name before retrying. The offline check is not affected.

The live check makes twenty classifier requests, plus at most one Polish-summary repair per
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

The monthly allowance is `classification.budget.monthly_usd`. Production
(`config/config.yaml`) sets 30 USD; it was raised from 10 on 2026-09-24 because Luna
costs about 11-17 USD a month. The code default (`sentinel/config.py`) and the template
keep 10; the validator accepts at most 50.

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
detection gap, not a successful safe classification. Provider outages, credit
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
choice. Preserve the database and alert history. A rollback is a production change
and needs the owner's explicit approval. `/deploy` copies `config/config.yaml` to the
server, so commit the rollback config to the repo; do not edit the server copy by hand.
The [Luna deployment record](../reference/luna-deployment-20260920.md) holds the
verified deployment and rollback procedure. Its "previous tag" rollback step predates
the 2026-09-25 deploys: the previous tag now also runs Luna. To return to Anthropic,
use the config-only rollback described here.

References: [Luna model and pricing](https://developers.openai.com/api/docs/models/gpt-5.6-luna),
[structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

---

## 2. Twilio (Phone Calls & SMS)

Twilio carries the urgency 9-10 phone call, its confirmation SMS, its SMS fallback, the update SMS for an acknowledged critical event, and the system-health SMS. In production, tiers 5-8 are push-only (`channel: push`), so they send no Twilio SMS. The template still routes them to `both` (SMS and push).

> Known state: the production Twilio account is deliberately left unfunded by the owner. Since 2026-09-21 every Twilio call and SMS returns HTTP 401 (`account ... with status 4 is not active`). This is expected, not an outage or a credential problem. Calls stay configured and return when the owner recharges the account. See the [server runbook troubleshooting](server-runbook.md#troubleshooting).

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

This sends a real, billed SMS. While the account is unfunded it fails with HTTP 401.
The simplest way is `./run.sh --config data/config.local.yaml --test-alert sms`.
To test with the Twilio library directly, first export the `.env` variables (the
snippet reads them from the environment):

```bash
set -a; . ./.env; set +a
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

## 3. Expo Push (Mobile Push Channel)

Expo Push delivers alerts to the companion mobile app. Each SMS urgency tier (5-8) has a `channel` setting (`sms` / `push` / `both`) that selects Twilio SMS, push, or both; the urgency 9-10 call also fires a push additively. Expo's push service is free.

Defaults and production differ:

- Code default and template: push is disabled (`alerts.push.enabled: false`, no tokens) and tiers 5-8 use `channel: both`. With push disabled, every tier sends SMS only and the 9-10 push does nothing.
- Production (`config/config.yaml`): push is enabled, tiers 5-8 use `channel: push` (no SMS), and the device token comes from the environment as `"${EXPO_PUSH_TOKEN}"`. Push is the only channel that reaches the phone while the Twilio account is unfunded.

There is no API key to obtain. The two pieces you provide are:

1. `EXPO_ACCESS_TOKEN` — an Expo access token that `sentinel/alerts/push_client.py` sends as a bearer credential. It is required when "Enhanced Security for Push Notifications" is turned on in the Expo project, because Expo then rejects unauthenticated sends. Production has it turned on (see the [server runbook](server-runbook.md)), so production needs this token. Without that setting, basic sends work without it. Create one at https://expo.dev (Account → Access Tokens), then add it to `.env`:
   ```
   EXPO_ACCESS_TOKEN=your-expo-access-token
   ```

2. Device push tokens — the per-device tokens (`ExponentPushToken[...]`) that identify which phones receive alerts. The companion mobile app under `mobile/` shows the device's token. Put it in `.env` as `EXPO_PUSH_TOKEN` and reference it from the config, then set `alerts.push.enabled: true`:
   ```yaml
   alerts:
     push:
       enabled: true
       tokens:
         - "${EXPO_PUSH_TOKEN}"
   ```
   Never paste a literal device token into `config/config.yaml`: it is tracked in a public repo. A literal token is acceptable only in an untracked local config such as `data/config.local.yaml`.

Every `${VAR}` in the config must be set when the config loads, or loading stops with a config error. So any machine that loads `config/config.yaml` needs `EXPO_PUSH_TOKEN` in its environment.

To change a tier's delivery, set its `channel`, for example `alerts.urgency_levels.high.channel: push` (push only, no SMS) or `both` (SMS and push).

See the [mobile companion app explanation](../explanation/mobile-app.md) for how to obtain a device token, and the [Configuration Reference](../reference/config-reference.md) for the full `alerts.push` block and the `channel` field.

Test it once configured with `./run.sh --config data/config.local.yaml --test-alert push`. This sends a real push to the configured device.

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

Run it from the repo folder. The first line exports the `.env` variables, because the snippet reads them from the environment:

```bash
set -a; . ./.env; set +a
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

No setup needed. The GDELT DOC 2.0 API is free and requires no API key or registration. Endpoint: `https://api.gdeltproject.org/api/v2/doc/doc`. Production disables GDELT (`sources.gdelt.enabled`) because of IP-level throttling; the template leaves it enabled. No credentials are required either way.

## 6. Google News RSS

No setup needed. Google News RSS feeds are public and free.

## 7. OpenRouter (Optional, Evals Only)

`OPENROUTER_API_KEY` is used only by the offline model comparison (`python -m sentinel.eval.compare_models`). Production alerting never uses it. Use a separate evaluation key with an OpenRouter credit limit. Setup and commands are in [Compare candidate classification models](model-comparison.md#openrouter-setup).

---

## Complete `.env` Template

This mirrors `.env.example` plus the two Expo variables. Values below are placeholders.

```bash
# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX

# Alert recipient
ALERT_PHONE_NUMBER=+48XXXXXXXXX

# Direct OpenAI classifier (required; paid API, separate from a ChatGPT/Codex subscription)
OPENAI_API_KEY=your_project_api_key

# Anthropic (only for explicit legacy rollback)
ANTHROPIC_API_KEY=sk-ant-xxxxx

# Optional: offline model comparison only; never used by production alerting.
# Use a separate evaluation key with an OpenRouter credit limit.
OPENROUTER_API_KEY=

# Telegram (channel monitoring)
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890

# Expo Push
# Required whenever the loaded config references ${EXPO_PUSH_TOKEN} (config/config.yaml does).
EXPO_PUSH_TOKEN=ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]
# Required when Enhanced Security for Push Notifications is on (production); optional otherwise.
EXPO_ACCESS_TOKEN=your-expo-access-token
```
