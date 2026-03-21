# Phase 5: Alert System

## Objective
Dispatch alerts via Twilio (phone call, SMS, WhatsApp) based on event urgency, manage call state and retries, prevent alert spam, and ensure the user is notified exactly once per event (with follow-up updates via text).

## Deliverables

### 5.1 Twilio Client (`sentinel/alerts/twilio_client.py`)

Wraps the Twilio SDK for outbound calls, SMS, and WhatsApp.

#### Phone Call

```python
def make_alert_call(self, phone_number: str, message_pl: str, event_id: str) -> AlertRecord:
    """Place an outbound call with Polish TTS message."""
    twiml = (
        f'<Response>'
        f'<Say language="pl-PL" voice="Polly.Ewa">'
        f'Uwaga! Alert systemu Project Sentinel. {message_pl}'
        f'</Say>'
        f'<Pause length="2"/>'
        f'<Say language="pl-PL" voice="Polly.Ewa">'
        f'Powtarzam. {message_pl}'
        f'</Say>'
        f'<Pause length="1"/>'
        f'<Say language="pl-PL" voice="Polly.Ewa">'
        f'Koniec alertu. Dalsze aktualizacje otrzymasz SMS-em.'
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
5. "Koniec alertu. Dalsze aktualizacje otrzymasz SMS-em." (End of alert. Further updates will be sent via SMS.)

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

#### Check Call Status

After placing a call, we need to check its status to determine acknowledgment:

```python
def get_call_status(self, twilio_sid: str) -> dict:
    """Check the status of a previously placed call."""
    call = self.client.calls(twilio_sid).fetch()
    return {
        "status": call.status,  # "queued", "ringing", "in-progress", "completed", "busy", "no-answer", "canceled", "failed"
        "duration": int(call.duration) if call.duration else 0,
    }
```

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
                    │       CALL_PLACED         │
                    │  (Twilio call initiated)   │
                    └────────────┬──────────────┘
                                 │
                    ┌────────────▼──────────────┐
                    │     CHECK CALL STATUS     │
                    │  (poll Twilio after 60s)   │
                    └──────┬─────────────┬──────┘
                           │             │
              ┌────────────▼──┐   ┌──────▼───────────┐
              │  ANSWERED     │   │  NOT ANSWERED     │
              │  duration>15s │   │  (no-answer/busy/ │
              │               │   │   failed/short)   │
              └──────┬────────┘   └──────┬────────────┘
                     │                    │
          ┌──────────▼────────┐  ┌───────▼──────────────┐
          │  ACKNOWLEDGED     │  │  RETRY?              │
          │  Send follow-up   │  │  attempt < max_retry │
          │  SMS with details │  └──┬──────────────┬────┘
          │  Set cooldown     │     │              │
          └───────────────────┘  ┌──▼────┐   ┌────▼────────┐
                                 │ WAIT  │   │ MAX RETRIES │
                                 │ 5 min │   │ REACHED     │
                                 └──┬────┘   └────┬────────┘
                                    │              │
                              ┌─────▼────┐   ┌────▼─────────┐
                              │ RETRY    │   │ SMS FALLBACK │
                              │ CALL     │   │ Send SMS     │
                              └──────────┘   └──────────────┘
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
        """Check status of calls that were placed but not yet confirmed.
        Called on each scheduler cycle."""
        pending_calls = self.db.get_pending_call_records()
        for record in pending_calls:
            status = self.twilio.get_call_status(record.twilio_sid)
            self._handle_call_result(record, status)
```

#### Cooldown Logic

After an event is acknowledged:
- No more phone calls for this event for `cooldown_hours` (default: 6)
- SMS/WhatsApp updates can still be sent if the event is updated with new information
- A completely NEW event (different event_type or different country) bypasses cooldown

After an event transitions to SMS fallback:
- No more phone calls for this event
- Further updates go via SMS

#### Preventing Alert Spam

Multiple safeguards:
1. **Event deduplication** (Corroborator in Phase 4) -- same incident = one event
2. **Cooldown period** -- no re-call for same event for N hours
3. **Max retries** -- max 3 call attempts, then SMS fallback
4. **Acknowledged flag** -- once acknowledged, only SMS updates
5. **Source count threshold** -- phone calls require 2+ independent sources

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

| Urgency | Sources | Action |
|---------|---------|--------|
| 9-10 | 2+ independent | Phone call → SMS follow-up |
| 9-10 | 1 only | SMS (wait for corroboration before calling) |
| 7-8 | 1+ | SMS |
| 5-6 | 1+ | WhatsApp |
| 1-4 | any | Log only |

Note: If a single-source urgency-10 event gets corroborated later (within `corroboration_window_minutes`), the system upgrades to a phone call at that point.

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
3. `test_call_message_repeated` -- TwiML contains message twice (for waking user)
4. `test_send_sms_returns_record` -- SMS creates AlertRecord
5. `test_sms_truncation` -- message > 1600 chars truncated
6. `test_send_whatsapp_returns_record` -- WhatsApp creates AlertRecord
7. `test_get_call_status` -- fetches call status from Twilio API
8. `test_twilio_error_handled` -- TwilioRestException logged, not raised

### test_state_machine.py
1. `test_new_critical_event_triggers_call` -- urgency 10 + 2 sources → phone call
2. `test_single_source_critical_triggers_sms` -- urgency 10 + 1 source → SMS only
3. `test_high_urgency_triggers_sms` -- urgency 8 → SMS
4. `test_medium_urgency_triggers_whatsapp` -- urgency 6 → WhatsApp
5. `test_low_urgency_logs_only` -- urgency 3 → no alert sent
6. `test_answered_call_acknowledged` -- call completed, duration 30s → acknowledged
7. `test_short_call_not_acknowledged` -- call completed, duration 5s → not acknowledged, retry
8. `test_no_answer_retry` -- call no-answer → retry after interval
9. `test_max_retries_sms_fallback` -- 3 failed calls → SMS fallback
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

## Dependencies
No new dependencies (Twilio SDK already in requirements.txt).
