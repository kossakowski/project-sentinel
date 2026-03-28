"""Tests for multi-tenant schema: tiers, users, user countries, alert rules, confirmation codes."""

from datetime import datetime, timezone

from sentinel.models import (
    AlertRecord,
    ConfirmationCode,
    Tier,
    User,
    UserAlertRule,
)


# ---------------------------------------------------------------------------
# Tier tests
# ---------------------------------------------------------------------------


class TestTiers:
    def test_insert_and_get_tier(self, db, sample_tier):
        """Insert a tier and retrieve it by ID."""
        db.insert_tier(sample_tier)
        retrieved = db.get_tier_by_id(sample_tier.id)

        assert retrieved is not None
        assert retrieved.id == sample_tier.id
        assert retrieved.name == sample_tier.name
        assert retrieved.available_channels == sample_tier.available_channels
        assert retrieved.max_countries == sample_tier.max_countries
        assert retrieved.preference_mode == sample_tier.preference_mode
        assert retrieved.preset_rules == sample_tier.preset_rules
        assert retrieved.is_active is True

    def test_get_tier_by_id_not_found(self, db):
        """get_tier_by_id returns None for nonexistent ID."""
        assert db.get_tier_by_id("nonexistent-id") is None

    def test_get_all_tiers(self, db, sample_tier, sample_premium_tier):
        """get_all_tiers returns all inserted tiers."""
        db.insert_tier(sample_tier)
        db.insert_tier(sample_premium_tier)

        tiers = db.get_all_tiers()
        names = [t.name for t in tiers]
        assert "Standard" in names
        assert "Premium" in names
        assert len(tiers) == 2

    def test_tier_preset_rules_json_roundtrip(self, db, sample_tier):
        """Preset rules dict survives insert/retrieve via JSONB."""
        db.insert_tier(sample_tier)
        retrieved = db.get_tier_by_id(sample_tier.id)
        assert retrieved.preset_rules == {
            "9-10": "phone_call",
            "7-8": "sms",
            "5-6": "whatsapp",
            "1-4": "log_only",
        }

    def test_tier_null_preset_rules(self, db, sample_premium_tier):
        """Premium tier with preset_rules=None roundtrips correctly."""
        db.insert_tier(sample_premium_tier)
        retrieved = db.get_tier_by_id(sample_premium_tier.id)
        assert retrieved.preset_rules is None
        assert retrieved.max_countries is None

    def test_tier_to_dict_from_dict_roundtrip(self, sample_tier):
        """Tier -> to_dict() -> from_dict() preserves fields."""
        d = sample_tier.to_dict()
        restored = Tier.from_dict(d)
        assert restored.id == sample_tier.id
        assert restored.name == sample_tier.name
        assert restored.available_channels == sample_tier.available_channels
        assert restored.preference_mode == sample_tier.preference_mode


# ---------------------------------------------------------------------------
# User tests
# ---------------------------------------------------------------------------


class TestUsers:
    def test_insert_and_get_user(self, db, sample_user):
        """Insert a user and retrieve by ID."""
        db.insert_user(sample_user)
        retrieved = db.get_user_by_id(sample_user.id)

        assert retrieved is not None
        assert retrieved.id == sample_user.id
        assert retrieved.name == sample_user.name
        assert retrieved.phone_number == sample_user.phone_number
        assert retrieved.language == "pl"
        assert retrieved.tier_id == sample_user.tier_id
        assert retrieved.is_active is True

    def test_get_user_by_id_not_found(self, db):
        """get_user_by_id returns None for nonexistent ID."""
        assert db.get_user_by_id("nonexistent-id") is None

    def test_get_active_users(self, db, sample_tier):
        """get_active_users returns only active users."""
        active_user = User(
            name="Active User",
            phone_number="+48111111111",
            tier_id=sample_tier.id,
        )
        inactive_user = User(
            name="Inactive User",
            phone_number="+48222222222",
            tier_id=sample_tier.id,
            is_active=False,
        )
        db.insert_tier(sample_tier)
        db.insert_user(active_user)
        db.insert_user(inactive_user)

        active_users = db.get_active_users()
        ids = [u.id for u in active_users]
        assert active_user.id in ids
        assert inactive_user.id not in ids

    def test_user_to_dict_from_dict_roundtrip(self, sample_tier):
        """User -> to_dict() -> from_dict() preserves fields."""
        user = User(
            name="Roundtrip User",
            phone_number="+48999999999",
            tier_id=sample_tier.id,
        )
        d = user.to_dict()
        restored = User.from_dict(d)
        assert restored.id == user.id
        assert restored.name == user.name
        assert restored.phone_number == user.phone_number
        assert restored.tier_id == user.tier_id
        assert restored.language == "pl"


# ---------------------------------------------------------------------------
# User country tests
# ---------------------------------------------------------------------------


class TestUserCountries:
    def test_insert_and_get_countries(self, db, sample_user):
        """Associate countries with a user and retrieve them."""
        db.insert_user(sample_user)
        db.insert_user_country(sample_user.id, "PL")
        db.insert_user_country(sample_user.id, "LT")

        countries = db.get_user_countries(sample_user.id)
        assert sorted(countries) == ["LT", "PL"]

    def test_delete_user_countries(self, db, sample_user):
        """delete_user_countries removes all country associations."""
        db.insert_user(sample_user)
        db.insert_user_country(sample_user.id, "PL")
        db.insert_user_country(sample_user.id, "LT")

        db.delete_user_countries(sample_user.id)
        countries = db.get_user_countries(sample_user.id)
        assert countries == []

    def test_get_users_by_country(self, db, sample_tier):
        """get_users_by_country returns only active users with matching country."""
        db.insert_tier(sample_tier)

        user_pl = User(name="PL User", phone_number="+48111", tier_id=sample_tier.id)
        user_lt = User(name="LT User", phone_number="+37011", tier_id=sample_tier.id)
        user_inactive = User(
            name="Inactive PL", phone_number="+48222", tier_id=sample_tier.id, is_active=False,
        )

        db.insert_user(user_pl)
        db.insert_user(user_lt)
        db.insert_user(user_inactive)

        db.insert_user_country(user_pl.id, "PL")
        db.insert_user_country(user_lt.id, "LT")
        db.insert_user_country(user_inactive.id, "PL")

        # Only active user with PL should be returned
        pl_users = db.get_users_by_country("PL")
        pl_ids = [u.id for u in pl_users]
        assert user_pl.id in pl_ids
        assert user_inactive.id not in pl_ids
        assert user_lt.id not in pl_ids

        # LT query
        lt_users = db.get_users_by_country("LT")
        lt_ids = [u.id for u in lt_users]
        assert user_lt.id in lt_ids
        assert len(lt_ids) == 1

    def test_get_users_by_country_no_match(self, db):
        """get_users_by_country returns empty list for unmatched country."""
        users = db.get_users_by_country("XX")
        assert users == []

    def test_get_user_countries_empty(self, db, sample_user):
        """get_user_countries returns empty list for user with no countries."""
        db.insert_user(sample_user)
        countries = db.get_user_countries(sample_user.id)
        assert countries == []


# ---------------------------------------------------------------------------
# User alert rule tests
# ---------------------------------------------------------------------------


class TestUserAlertRules:
    def test_insert_and_get_rules(self, db, sample_user_alert_rule):
        """Insert a rule and retrieve it."""
        db.insert_user_alert_rule(sample_user_alert_rule)

        rules = db.get_user_alert_rules(sample_user_alert_rule.user_id)
        assert len(rules) == 1
        rule = rules[0]
        assert rule.id == sample_user_alert_rule.id
        assert rule.min_urgency == 7
        assert rule.max_urgency == 10
        assert rule.channel == "phone_call"
        assert rule.corroboration_required == 2
        assert rule.priority == 10

    def test_rules_ordered_by_priority_desc(self, db, sample_user):
        """Rules are returned in descending priority order."""
        db.insert_user(sample_user)

        low_priority = UserAlertRule(
            user_id=sample_user.id,
            min_urgency=1,
            max_urgency=4,
            channel="log_only",
            priority=0,
        )
        high_priority = UserAlertRule(
            user_id=sample_user.id,
            min_urgency=7,
            max_urgency=10,
            channel="phone_call",
            priority=10,
        )
        db.insert_user_alert_rule(low_priority)
        db.insert_user_alert_rule(high_priority)

        rules = db.get_user_alert_rules(sample_user.id)
        assert len(rules) == 2
        assert rules[0].priority > rules[1].priority
        assert rules[0].channel == "phone_call"
        assert rules[1].channel == "log_only"

    def test_delete_user_alert_rules(self, db, sample_user_alert_rule):
        """delete_user_alert_rules removes all rules for a user."""
        db.insert_user_alert_rule(sample_user_alert_rule)

        db.delete_user_alert_rules(sample_user_alert_rule.user_id)
        rules = db.get_user_alert_rules(sample_user_alert_rule.user_id)
        assert rules == []

    def test_rule_to_dict_from_dict_roundtrip(self):
        """UserAlertRule -> to_dict() -> from_dict() preserves fields."""
        rule = UserAlertRule(
            user_id="user-123",
            min_urgency=5,
            max_urgency=8,
            channel="sms",
            corroboration_required=1,
            priority=5,
        )
        d = rule.to_dict()
        restored = UserAlertRule.from_dict(d)
        assert restored.id == rule.id
        assert restored.user_id == rule.user_id
        assert restored.min_urgency == 5
        assert restored.max_urgency == 8
        assert restored.channel == "sms"

    def test_get_rules_empty(self, db, sample_user):
        """get_user_alert_rules returns empty list for user with no rules."""
        db.insert_user(sample_user)
        rules = db.get_user_alert_rules(sample_user.id)
        assert rules == []


# ---------------------------------------------------------------------------
# Confirmation code tests
# ---------------------------------------------------------------------------


class TestConfirmationCodes:
    def test_insert_and_get_active(self, db, sample_confirmation_code):
        """Insert a confirmation code and retrieve it as active."""
        db.insert_confirmation_code(sample_confirmation_code)

        active = db.get_active_confirmation_code(
            sample_confirmation_code.user_id,
            sample_confirmation_code.event_id,
        )
        assert active is not None
        assert active.id == sample_confirmation_code.id
        assert active.code == "ABC123"
        assert active.used_at is None

    def test_mark_used_then_not_active(self, db, sample_confirmation_code):
        """After marking used, get_active_confirmation_code returns None."""
        db.insert_confirmation_code(sample_confirmation_code)

        # Mark it used
        db.mark_confirmation_code_used(sample_confirmation_code.id)

        # Should no longer be returned as active
        active = db.get_active_confirmation_code(
            sample_confirmation_code.user_id,
            sample_confirmation_code.event_id,
        )
        assert active is None

    def test_mark_used_sets_used_at(self, db, sample_confirmation_code):
        """Marking used sets used_at to a non-null timestamp."""
        db.insert_confirmation_code(sample_confirmation_code)
        db.mark_confirmation_code_used(sample_confirmation_code.id)

        # Retrieve directly from DB to check used_at
        with db.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT used_at FROM confirmation_codes WHERE id = %s",
                    (sample_confirmation_code.id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert row["used_at"] is not None

    def test_most_recent_active_code_returned(self, db, sample_user, sample_event):
        """When multiple unused codes exist, the most recent one is returned."""
        db.insert_user(sample_user)
        db.insert_event(sample_event)

        code1 = ConfirmationCode(
            user_id=sample_user.id,
            event_id=sample_event.id,
            code="CODE1",
        )
        code2 = ConfirmationCode(
            user_id=sample_user.id,
            event_id=sample_event.id,
            code="CODE2",
        )
        db.insert_confirmation_code(code1)
        db.insert_confirmation_code(code2)

        active = db.get_active_confirmation_code(sample_user.id, sample_event.id)
        assert active is not None
        # The most recent one should be returned (code2 was inserted later)
        assert active.code == "CODE2"

    def test_no_active_code_returns_none(self, db, sample_user, sample_event):
        """get_active_confirmation_code returns None when no codes exist."""
        db.insert_user(sample_user)
        db.insert_event(sample_event)

        active = db.get_active_confirmation_code(sample_user.id, sample_event.id)
        assert active is None

    def test_confirmation_code_to_dict_from_dict_roundtrip(self):
        """ConfirmationCode -> to_dict() -> from_dict() preserves fields."""
        code = ConfirmationCode(
            user_id="user-123",
            event_id="event-456",
            code="XYZ789",
        )
        d = code.to_dict()
        restored = ConfirmationCode.from_dict(d)
        assert restored.id == code.id
        assert restored.user_id == code.user_id
        assert restored.event_id == code.event_id
        assert restored.code == "XYZ789"
        assert restored.used_at is None


# ---------------------------------------------------------------------------
# AlertRecord backward compatibility
# ---------------------------------------------------------------------------


class TestAlertRecordUserIdField:
    def test_alert_record_default_user_id_none(self):
        """AlertRecord created without user_id defaults to None."""
        record = AlertRecord(
            event_id="evt-1",
            alert_type="sms",
            twilio_sid="SM123",
            status="delivered",
            attempt_number=1,
            sent_at=datetime.now(timezone.utc),
            message_body="Test",
        )
        assert record.user_id is None

    def test_alert_record_with_user_id(self):
        """AlertRecord can be created with explicit user_id."""
        record = AlertRecord(
            event_id="evt-1",
            alert_type="sms",
            twilio_sid="SM123",
            status="delivered",
            attempt_number=1,
            sent_at=datetime.now(timezone.utc),
            message_body="Test",
            user_id="user-abc",
        )
        assert record.user_id == "user-abc"

    def test_alert_record_to_dict_includes_user_id(self):
        """to_dict() includes user_id field."""
        record = AlertRecord(
            event_id="evt-1",
            alert_type="sms",
            twilio_sid="SM123",
            status="delivered",
            attempt_number=1,
            sent_at=datetime.now(timezone.utc),
            message_body="Test",
            user_id="user-abc",
        )
        d = record.to_dict()
        assert d["user_id"] == "user-abc"

    def test_alert_record_from_dict_without_user_id(self):
        """from_dict() with no user_id field defaults to None."""
        d = {
            "event_id": "evt-1",
            "alert_type": "sms",
            "twilio_sid": "SM123",
            "status": "delivered",
            "attempt_number": 1,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "message_body": "Test",
        }
        record = AlertRecord.from_dict(d)
        assert record.user_id is None

    def test_alert_record_roundtrip_with_user_id(self):
        """AlertRecord with user_id survives to_dict -> from_dict roundtrip."""
        record = AlertRecord(
            event_id="evt-1",
            alert_type="phone_call",
            twilio_sid="CA123",
            status="completed",
            attempt_number=1,
            sent_at=datetime.now(timezone.utc),
            message_body="Test",
            user_id="user-xyz",
        )
        d = record.to_dict()
        restored = AlertRecord.from_dict(d)
        assert restored.user_id == "user-xyz"

    def test_alert_record_db_insert_with_user_id(self, db, sample_tier, sample_event):
        """AlertRecord with user_id can be inserted and retrieved from DB."""
        db.insert_tier(sample_tier)
        user = User(name="DB User", phone_number="+48111", tier_id=sample_tier.id)
        db.insert_user(user)
        db.insert_event(sample_event)

        record = AlertRecord(
            event_id=sample_event.id,
            alert_type="sms",
            twilio_sid="SM999",
            status="delivered",
            attempt_number=1,
            sent_at=datetime.now(timezone.utc),
            message_body="Test with user_id",
            user_id=user.id,
        )
        db.insert_alert_record(record)

        records = db.get_alert_records(sample_event.id)
        assert len(records) == 1
        assert records[0].user_id == user.id

    def test_alert_record_db_insert_without_user_id(self, db, sample_event):
        """AlertRecord without user_id (legacy) can still be inserted."""
        db.insert_event(sample_event)

        record = AlertRecord(
            event_id=sample_event.id,
            alert_type="sms",
            twilio_sid="SM888",
            status="delivered",
            attempt_number=1,
            sent_at=datetime.now(timezone.utc),
            message_body="Legacy record",
        )
        db.insert_alert_record(record)

        records = db.get_alert_records(sample_event.id)
        assert len(records) == 1
        assert records[0].user_id is None


# ---------------------------------------------------------------------------
# Table structure tests
# ---------------------------------------------------------------------------


class TestMultiTenantSchema:
    def test_new_tables_exist(self, db):
        """All 5 new tables exist in the database."""
        with db.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY table_name"
                )
                tables = {row["table_name"] for row in cur.fetchall()}

        for expected in ["tiers", "users", "user_countries", "user_alert_rules", "confirmation_codes"]:
            assert expected in tables, f"Table '{expected}' not found"

    def test_alert_records_has_user_id_column(self, db):
        """alert_records table has user_id column."""
        with db.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'alert_records' "
                    "AND column_name = 'user_id'"
                )
                row = cur.fetchone()
                assert row is not None, "alert_records.user_id column not found"

    def test_tiers_column_types(self, db):
        """Verify key column types on tiers table."""
        expected = [
            ("tiers", "available_channels", "jsonb"),
            ("tiers", "preset_rules", "jsonb"),
            ("tiers", "is_active", "boolean"),
            ("tiers", "created_at", "timestamp with time zone"),
        ]
        with db.pool.connection() as conn:
            with conn.cursor() as cur:
                for table, column, expected_type in expected:
                    cur.execute(
                        "SELECT data_type FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
                        (table, column),
                    )
                    row = cur.fetchone()
                    assert row is not None, f"Column {table}.{column} not found"
                    assert row["data_type"] == expected_type, (
                        f"{table}.{column}: expected '{expected_type}', got '{row['data_type']}'"
                    )

    def test_confirmation_codes_index_exists(self, db):
        """Verify the composite index on confirmation_codes(user_id, event_id, code) exists."""
        with db.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'confirmation_codes' "
                    "AND indexname = 'idx_confirmation_codes_lookup'"
                )
                row = cur.fetchone()
                assert row is not None, "idx_confirmation_codes_lookup index not found"
