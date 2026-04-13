# Phase 5: Alert System

> STATUS: COMPLETE — implemented in production
> KEY FILES: `sentinel/alerts/twilio_client.py`, `sentinel/alerts/state_machine.py`, `sentinel/alerts/dispatcher.py`

## Objective
Dispatch alerts via Twilio (phone call, SMS, WhatsApp) based on event urgency, manage call state and retries, prevent alert spam, and ensure the user is notified exactly once per event (with follow-up updates via text).

## Deliverables

### 5.1 Twilio Client (`sentinel/alerts/twilio_client.py`)

Wraps the Twilio SDK for outbound calls, SMS, and WhatsApp.

#### Method Reference

| Method | Signature | File:Line |
|---|---|---|
| Phone call | `make_alert_call(phone_number, message_pl, event_id) -> AlertRecord` | `twilio_client.py` |
| SMS | `send_sms(phone_number, message, event_id) -> AlertRecord` (truncates to 1600 chars) | `twilio_client.py` |
| WhatsApp | `send_whatsapp(phone_number, message, event_id) -> AlertRecord` — **unreachable from `process_event`**; only `--test-alert whatsapp` reaches it | `twilio_client.py` |

Explicit comment at `twilio_client.py:41` forbids `<Gather>` / DTMF — voicemail caused false-positive confirmations.

#### Phone Call

```python
def make_alert_call(self, phone_number: str, message_pl: str, event_id: str) -> AlertRecord:
    """Place an outbound call with Polish TTS message.

    The call instructs the operator to reply to the SMS they already
    received with the 6-digit confirmation code to acknowledge receipt.
    """
    twiml = (
        f'<Response>'
        f'<Say language="pl-PL" voice="Polly.Ewa">'
        f'Uwaga! Alert systemu Project Sentinel. {message_pl}.'
        f'</Say>'
        f'<Pause length="2"/>'
        f'<Say language="pl-PL" voice="Polly.Ewa">'
        f'Powtarzam. {message_pl}.'
        f'</Say>'
        f'<Pause length="1"/>'
        f'<Say language="pl-PL" voice="Polly.Ewa">'
        f'Potwierdź odbiór alertu. Odpisz na SMS kodem, który otrzymałeś.'
        f'</Say>'
        f'</Response>'
    )

    call = self.client.calls.create(
        from_=self.twilio_phone,
        to=phone_number,
        twiml=twiml,
    )

    return AlertRecord(
        id=str(uuid4()),
        event_id=event_id,
        alert_type="phone_call",
        twilio_sid=call.sid,
        status="initiated",
        duration_seconds=None,
        attempt_number=1,
        sent_at=datetime.utcnow(),
        message_body=message_pl,
    )
```

#### Call Structure
The phone call speaks in Polish using Amazon Polly's `Ewa` voice (native Polish):
1. "Uwaga! Alert systemu Project Sentinel." (Attention! Project Sentinel system alert.)
2. The actual alert message (from `summary_pl`)
3. 2-second pause
4. Repeats the alert message (in case user just woke up)
5. Instructs the operator to reply to the SMS they already received with the 6-digit confirmation code

#### SMS

```python
def send_sms(self, phone_number: str, message: str, event_id: str) -> AlertRecord:
    """Send an SMS alert."""
    # Twilio SMS max is 1600 chars; truncate if needed
    if len(message) > 1600:
        message = message[:1597] + "..."

    msg = self.client.messages.create(
        from_=self.twilio_phone,
        to=phone_number,
        body=message,
    )

    return AlertRecord(
        id=str(uuid4()),
        event_id=event_id,
        alert_type="sms",
        twilio_sid=msg.sid,
        status="sent",
        duration_seconds=None,
        attempt_number=1,
        sent_at=datetime.utcnow(),
        message_body=message,
    )
```

#### SMS Message Format
```
🚨 PROJECT SENTINEL ALERT 🚨
Typ: {event_type}
Pilność: {urgency_score}/10
Kraje: {affected_countries}
Agresor: {aggressor}

{summary_pl}

Źródła ({source_count}):
- {source_1_name}: {source_1_title}
- {source_2_name}: {source_2_title}

Czas wykrycia: {first_seen_at}
```

#### WhatsApp

```python
def send_whatsapp(self, phone_number: str, message: str, event_id: str) -> AlertRecord:
    """Send a WhatsApp message."""
    msg = self.client.messages.create(
        from_=self.twilio_whatsapp,
        to=f"whatsapp:{phone_number}",
        body=message,
    )

    return AlertRecord(
        id=str(uuid4()),
        event_id=event_id,
        alert_type="whatsapp",
        twilio_sid=msg.sid,
        status="sent",
        duration_seconds=None,
        attempt_number=1,
        sent_at=datetime.utcnow(),
        message_body=message,
    )
```

#### SMS Confirmation Code

Before the call loop starts, the system sends an SMS with a random 6-digit confirmation code. The operator must reply to that SMS with the code to acknowledge receipt.

```python
def _send_confirmation_sms(self, event: Event) -> None:
    """Send an SMS with a 6-digit confirmation code before the call loop."""
    self._confirmation_code = str(random.randint(100000, 999999))
    message = (
        f"🚨 PROJECT SENTINEL ALERT 🚨\n"
        f"Otrzymasz połączenie alarmowe.\n"
        f"Aby potwierdzić odbiór, odpisz na tę wiadomość kodem: {self._confirmation_code}"
    )
    self.twilio.send_sms(self.config.alerts.phone_number, message, event.id)

def _check_sms_confirmation(self, since: datetime) -> bool:
    """Poll incoming SMS messages to check if the operator replied with the code."""
    messages = self.twilio.client.messages.list(
        from_=self.config.alerts.phone_number,
        to=self.twilio.twilio_phone,
        limit=10,
    )
    for msg in messages:
        if self._confirmation_code in msg.body:
            return True
    return False
```

The confirmation code is stored in-memory (`self._confirmation_code`) on the `AlertStateMachine` instance. It is not persisted to the database — if the process restarts mid-call-loop, the code is lost.

#### Call Loop

The full call sequence with SMS code confirmation:

1. Generate a random 6-digit code and store in `self._confirmation_code`
2. Send SMS with the code ("Odpisz na tę wiadomość kodem: {code}")
3. Place call (up to **5** attempts, 10 seconds between calls)
4. After each call attempt, poll inbound SMS for the code reply
5. If code confirmed → acknowledge event
6. If all 5 calls exhausted without confirmation → mark `retry_pending`
7. Next pipeline cycle retries after `retry_interval_minutes` (default 5)

### 5.2 Call State Machine (`sentinel/alerts/state_machine.py`)

Tracks the lifecycle of each alert to prevent spam and manage retries.

#### State Diagram

```
                    ┌───────────────────────────┐
                    │        NEW EVENT          │
                    │   (urgency >= threshold)   │
                    └────────────┬──────────────┘
                                 │
                    ┌────────────▼──────────────┐
                    │    SEND SMS WITH CODE     │
                    │  (random 6-digit code)     │
                    └────────────┬──────────────┘
                                 │
                    ┌────────────▼──────────────┐
                    │       CALL_PLACED         │
                    │  (up to 5 attempts,        │
                    │   10s between calls)       │
                    └────────────┬──────────────┘
                                 │
                    ┌────────────▼──────────────┐
                    │    CHECK SMS REPLY        │
                    │  (poll inbound SMS after   │
                    │   each call attempt)       │
                    └──────┬─────────────┬──────┘
                           │             │
              ┌────────────▼──┐   ┌──────▼───────────┐
              │  CODE         │   │  NO REPLY         │
              │  CONFIRMED    │   │  (attempt < 5)    │
              └──────┬────────┘   └──────┬────────────┘
                     │                    │
          ┌──────────▼────────┐  ┌───────▼──────────────┐
          │  ACKNOWLEDGED     │  │  RETRY CALL          │
          │  Send follow-up   │  │  (next attempt)      │
          │  SMS with details │  └──┬──────────────┬────┘
          │  Set cooldown     │     │              │
          └───────────────────┘  ┌──▼────┐   ┌────▼────────┐
                                 │ CALL  │   │ ALL 5 CALLS │
                                 │ AGAIN │   │ EXHAUSTED   │
                                 └───────┘   └────┬────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │  RETRY_PENDING  │
                                          │  retry after    │
                                          │  5 min (next    │
                                          │  cycle)         │
                                          └─────────────────┘
```

#### State Machine Implementation

```python
class AlertStateMachine:
    """Manages the lifecycle of event alerts."""

    def __init__(self, db: Database, twilio_client: TwilioClient, config: SentinelConfig):
        self.db = db
        self.twilio = twilio_client
        self.config = config

    def process_event(self, event: Event) -> None:
        """Determine and execute the appropriate alert action for an event."""
        # Check if event is in cooldown
        if self._is_in_cooldown(event):
            return

        # Check if already alerted for this event
        existing_alerts = self.db.get_alert_records(event.id)
        if self._is_acknowledged(existing_alerts):
            # Already acknowledged -- send update via SMS if event updated
            if event.last_updated_at > self._last_alert_time(existing_alerts):
                self._send_update_sms(event)
            return

        # Determine alert action based on urgency and corroboration
        action = self._determine_action(event)

        if action == "phone_call":
            self._execute_phone_call(event)
        elif action == "sms":
            self._execute_sms(event)
        elif action == "whatsapp":
            self._execute_whatsapp(event)
        # action == "log_only" → do nothing

    def check_pending_calls(self) -> None:
        """Check for SMS confirmation code replies on pending calls.
        Called on each scheduler cycle."""
        pending_calls = self.db.get_pending_call_records()
        for record in pending_calls:
            self._handle_call_result(record, self._check_sms_confirmation(since=record.sent_at))
```

#### Acknowledgment Mechanism (`state_machine.py:362-413`)

| Parameter | Value | Source |
|---|---|---|
| Confirmation code | `str(random.randint(100000, 999999))` | `state_machine.py:362-413` |
| Poll interval | 5 s | `state_machine.py` |
| Poll timeout per call attempt | 90 s | `state_machine.py:446` |
| Between-call sleep (within round) | 10 s | `state_machine.py:331` |
| Calls per round (`max_call_retries`) | live=5, default=3 | config |
| Between-round wait (`retry_interval_minutes`) | default 5 | config |
| Poll API | `twilio.client.messages.list(to=twilio_phone, from_=phone_number)`, match code substring | — |
| Cooldown after `acknowledged_at` (`cooldown_hours`) | default/live 6 | config |

Round flow: send confirmation SMS → `max_call_retries` calls with 5 s code-polling after each → if no match across round, event flagged `retry_pending` → wait `retry_interval_minutes` → next round.

#### Cooldown Override

| Situation | Behavior |
|---|---|
| Same event, new source within cooldown | SMS update only |
| New higher-urgency or significantly different event within cooldown | Overrides cooldown, alerts normally |

#### Post-Acknowledgment Behavior

After event is acknowledged (operator replies to SMS with 6-digit code):
1. Event is marked with `acknowledged_at` timestamp
2. A follow-up SMS with full event details and source list is sent
3. Cooldown starts (default: 6 hours)
4. If new sources arrive during cooldown → brief SMS update only
5. A completely NEW event (different event_type or different country) bypasses cooldown

#### Preventing Alert Spam

Multiple safeguards:
1. **Event deduplication** (Corroborator in Phase 4) -- same incident = one event
2. **Cooldown period** -- no re-call for same event for N hours
3. **Max retries** -- max 5 call attempts per call loop, then `retry_pending` until next cycle
4. **Acknowledged flag** -- once acknowledged, only SMS updates
5. **Source count threshold** -- phone calls require corroboration (see `classification.corroboration_required` in config; live value is `1`)

### 5.3 Alert Dispatcher (`sentinel/alerts/dispatcher.py`)

Routes events to the appropriate alert channel based on urgency score.

```python
class AlertDispatcher:
    def __init__(self, state_machine: AlertStateMachine, config: SentinelConfig):
        self.state_machine = state_machine
        self.config = config
        self.dry_run = config.testing.dry_run

    def dispatch(self, events: list[Event]) -> None:
        """Process all events that need alerting."""
        for event in events:
            if self.dry_run:
                self._log_dry_run(event)
                continue

            self.state_machine.process_event(event)

    def _log_dry_run(self, event: Event) -> None:
        """Log what would happen without actually sending alerts."""
        action = self.state_machine._determine_action(event)
        self.logger.info(
            f"[DRY RUN] Event {event.id}: urgency={event.urgency_score}, "
            f"sources={event.source_count}, would_trigger={action}, "
            f"summary={event.summary_pl}"
        )
```

#### Alert Decision Matrix

Decided in `AlertStateMachine._determine_action`. Rules:

| Condition | Action | Source-count check |
|---|---|---|
| `urgency >= 9 AND source_count >= corroboration_required` | `phone_call` | Yes |
| `urgency >= 9 AND source_count < corroboration_required` | `sms` | — |
| `urgency >= 7` | `sms` | **None** — urgency alone triggers |
| `urgency >= 5` | `whatsapp` → routed to `_execute_sms` at `state_machine.py:190` | — |
| `urgency < 5` | `log_only` | — |

Phone-call corroboration values:

| Key | Pydantic default | Live production |
|---|---|---|
| `classification.corroboration_required` | 2 | 1 |
| `alerts.urgency_levels.critical.corroboration_required` | 2 | 1 |

With live config, a **single source at urgency 9** triggers a phone call.

Note: If a single-source urgency-10 event gets corroborated later (within `corroboration_window_minutes`), the next pass upgrades to a phone call.

### 5.4 Alert Message Templates

All alert messages are in Polish. Templates are stored in config for easy modification.

#### Phone Call Template
```
{event_type_pl} wykryte. {summary_pl}. Źródła potwierdzające: {source_count}. Pilność: {urgency_score} na 10.
```

Where `event_type_pl` maps:
```python
EVENT_TYPE_PL = {
    "invasion": "Inwazja",
    "airstrike": "Nalot powietrzny",
    "missile_strike": "Uderzenie rakietowe",
    "border_crossing": "Przekroczenie granicy",
    "airspace_violation": "Naruszenie przestrzeni powietrznej",
    "naval_blockade": "Blokada morska",
    "cyber_attack": "Atak cybernetyczny",
    "troop_movement": "Ruchy wojsk",
    "artillery_shelling": "Ostrzał artyleryjski",
    "drone_attack": "Atak dronów",
}
```

#### SMS Template
```
🚨 PROJECT SENTINEL: {event_type_pl}
Pilność: {urgency_score}/10
Kraje: {affected_countries_str}
Agresor: {aggressor}

{summary_pl}

Źródła ({source_count}):
{sources_list}

Wykryto: {first_seen_at_local}
```

#### SMS Update Template (for acknowledged events)
```
ℹ️ PROJECT SENTINEL UPDATE: {event_type_pl}
Nowe informacje ({new_source_name}):
{new_summary}

Łącznie źródeł: {source_count}
Pilność: {urgency_score}/10
```

## Acceptance Tests

### test_twilio_client.py
1. `test_make_call_returns_record` -- call creates AlertRecord with correct fields
2. `test_call_twiml_polish` -- TwiML contains Polish language tag and Polly.Ewa voice
3. `test_call_message_repeated` -- TwiML contains message twice with SMS reply instruction (for waking user)
4. `test_send_sms_returns_record` -- SMS creates AlertRecord
5. `test_sms_truncation` -- message > 1600 chars truncated
6. `test_send_whatsapp_returns_record` -- WhatsApp creates AlertRecord
7. `test_send_confirmation_sms` -- sends SMS with 6-digit confirmation code before call loop
8. `test_check_sms_confirmation_found` -- detects correct code in inbound SMS reply
9. `test_check_sms_confirmation_not_found` -- returns False when no matching SMS reply
10. `test_twilio_error_handled` -- TwilioRestException logged, not raised

### test_state_machine.py
1. `test_new_critical_event_triggers_call` -- urgency 10 + corroboration met → phone call
2. `test_single_source_critical_triggers_sms` -- urgency 10, corroboration not met → SMS only
3. `test_high_urgency_triggers_sms` -- urgency 8 → SMS
4. `test_medium_urgency_triggers_sms` -- urgency 6 → SMS (WhatsApp action routed to SMS)
5. `test_low_urgency_logs_only` -- urgency 3 → no alert sent
6. `test_sms_code_confirmed_acknowledged` -- operator replies to SMS with correct code → acknowledged
7. `test_sms_code_not_confirmed_retry` -- no SMS reply after call → retry next attempt
8. `test_no_answer_retry` -- call no-answer → retry after interval
9. `test_max_retries_retry_pending` -- 5 failed calls → retry_pending, retried next cycle
10. `test_cooldown_prevents_recall` -- acknowledged event within cooldown → no call
11. `test_cooldown_expired_allows_call` -- acknowledged event after cooldown → can call again
12. `test_new_event_bypasses_cooldown` -- different event during cooldown → calls normally
13. `test_acknowledged_event_gets_sms_update` -- event updated after ack → SMS update sent
14. `test_duplicate_alert_prevented` -- same event in same cycle → alerted only once

### test_dispatcher.py
1. `test_dry_run_no_calls` -- dry run mode logs but doesn't call Twilio
2. `test_multiple_events_all_processed` -- 3 events → all 3 processed
3. `test_events_sorted_by_urgency` -- highest urgency processed first
4. `test_dry_run_log_format` -- dry run log contains urgency, action, summary

### 5.4 End-to-End Alert Testing (`--test-alert`)

The `--test-alert` CLI flag fires a real Twilio alert without running the pipeline. It creates a synthetic event directly in the database and dispatches it through `AlertStateMachine.process_event()`, bypassing fetching, classification, and corroboration entirely.

```bash
python sentinel.py --test-alert              # phone call (default)
python sentinel.py --test-alert sms          # SMS
python sentinel.py --test-alert whatsapp     # WhatsApp
```

**Synthetic event properties:**
- `event_type`: `missile_strike`
- `urgency_score`: `10`
- `source_count`: `2` (satisfies `corroboration_required`)
- `aggressor`: `TEST`
- `summary_pl`: `[TEST] To jest próba alertu systemu Project Sentinel. Nie ma zagrożenia.`
- `alert_status`: matches the requested alert type

This flag forces `dry_run=False` regardless of config (`sentinel.py:367`), calls `AlertStateMachine._execute_*` **directly** (private methods), and bypasses corroboration / `process_event` entirely. No Claude API costs — only Twilio charges for the actual call/message. `--test-alert whatsapp` is the only path that reaches `_execute_whatsapp` / `TwilioClient.send_whatsapp`.

## Known Quirks

| Quirk | Location | Impact |
|---|---|---|
| WhatsApp permanently disabled in `process_event` (action `whatsapp` routed to `_execute_sms`) | `state_machine.py:190` | `_execute_whatsapp` (line 478) and `send_whatsapp` unreachable in normal flow |
| `if False:` block holds dead duration-based acknowledgment logic | `state_machine.py:501` | Never executes |
| `_check_confirmation_sms_delivered` implemented but never called | `state_machine.py:415` | Dead code |
| `_confirmation_code` is an instance attribute, not reset on event boundary | `state_machine.py` | Overlapping events risk stale-code match |
| `call_duration_threshold_seconds` config key only read inside dead `if False:` block | `state_machine.py:499` | Config key fully unused |
| Two urgency decision paths: Corroborator writes `event.alert_status`, StateMachine ignores it and re-decides | `state_machine.py` | Single source of truth is `_determine_action` |
| Inline TwiML (no Twilio webhooks) | `twilio_client.py` | No public HTTP endpoint required for alerts |

## Dependencies
No new dependencies (Twilio SDK already in requirements.txt).
