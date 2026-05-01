# API Setup Guide

This guide covers setting up all external service accounts needed by Project Sentinel.

## 1. Anthropic API (Claude Haiku)

You need an Anthropic API account to use Claude Haiku for article classification. This is separate from a Claude Pro/Team chat subscription.

### Steps

1. Go to **https://console.anthropic.com**
2. Sign up or log in (can use same email as your Claude chat account)
3. Navigate to **Settings → Billing**
4. Add a payment method
5. Add credits -- **$5 is enough for months** of usage at Haiku rates
6. Navigate to **Settings → API Keys**
7. Click **Create Key**
8. Name it `project-sentinel` (for your reference)
9. Copy the key -- it starts with `sk-ant-...`
10. Add to your `.env` file:
    ```
    ANTHROPIC_API_KEY=sk-ant-your-key-here
    ```

### Pricing (Claude Haiku 4.5)

Pricing changes — see [Anthropic pricing](https://www.anthropic.com/pricing) for current Haiku 4.5 rates. Project Sentinel uses ~50-100 classifications/day; costs are minimal.

### Verify It Works

```bash
pip install anthropic
python -c "
import anthropic
client = anthropic.Anthropic()
msg = client.messages.create(
    model='claude-haiku-4-5-20251001',
    max_tokens=100,
    messages=[{'role': 'user', 'content': 'Say hello in Polish'}]
)
print(msg.content[0].text)
"
```

---

## 2. Twilio (Phone Calls, SMS, WhatsApp)

If you want a sandbox to test Twilio interactively, you can build one separately — Project Sentinel itself does not include one.

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
5. For WhatsApp:
   - Go to **Messaging → Try it Out → Send a WhatsApp message**
   - Follow the sandbox setup (or apply for a WhatsApp Business sender)
6. Add to `.env`:
   ```
   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
   TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
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

## 3. Telegram API (Channel Monitoring)

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

Follow the prompts. After success, a `sentinel_session.session` file is created -- **keep this file secure**, it grants access to your Telegram account.

### Finding Channel IDs

Channel IDs in config use the format `@channel_name` (the public username). To find the username of a channel:
1. Open the channel in Telegram
2. Look at the channel info -- the username is shown as `t.me/channel_name`
3. Use `@channel_name` in config

### Recommended Channels

| Channel | ID | Language | Notes |
|---|---|---|---|
| Ukrainian Air Force | `@kpszsu` | UK | Fastest for cross-border drone events |
| NEXTA Live | `@nexta_live` | EN/RU | Belarusian opposition, fast on military events |
| Rybar | `@rybar_force` | RU | Russian mil-blogger, detailed maps |

**Note:** Channel IDs may change. Verify them before configuring.

### Security Note

The Telegram session file (`sentinel_session.session`) is equivalent to being logged into your Telegram account. Protect it:
- Set permissions: `chmod 600 sentinel_session.session`
- Never commit it to git (add to `.gitignore`)
- If compromised, revoke all sessions in Telegram settings

---

## 4. GDELT API

**No setup needed.** The GDELT DOC 2.0 API is free and requires no API key or registration. Endpoint: `https://api.gdeltproject.org/api/v2/doc/doc`

## 5. Google News RSS

**No setup needed.** Google News RSS feeds are public and free.

---

## Complete `.env` Template

```bash
# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886

# Alert recipient
ALERT_PHONE_NUMBER=+48XXXXXXXXX

# Anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxx

# Telegram
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
```
