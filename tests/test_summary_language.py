"""Polish summary repair must never reclassify or suppress a valid critical event."""

import copy
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from sentinel.classification.corroborator import Corroborator
from sentinel.classification.incident_memory import IncidentMemory
from sentinel.classification.openai_provider import BudgetExceeded, StructuredReply
from sentinel.classification.summary_language import ensure_polish, is_polish
from sentinel.config import SummaryLanguageConfig
from sentinel.eval.compare_models import RecordingAlerts, RecordingTransport
from sentinel.models import ClassificationResult
from tests.test_direct_openai import answer, classifier_with_http, response

UKRAINIAN = (
    "Влада Латвії наказала мешканцям Даугавпілса негайно перейти в укриття через наближення ударних безпілотників. "
    "Влучання наразі не підтверджені, тому факт атаки в Латвії не встановлено."
)
POLISH = (
    "Władze Łotwy nakazały mieszkańcom Dyneburga natychmiast schronić się przed nadlatującymi dronami uderzeniowymi. "
    "Trafień nie potwierdzono, więc nie ustalono, czy doszło do ataku na terytorium Łotwy."
)


@pytest.mark.parametrize(
    "text,expected",
    [
        (UKRAINIAN, False),
        (POLISH, True),
        ("Russian forces crossed the Polish border. Residents have been ordered to shelter.", False),
        ("Rosyjskie wojska przekroczyły polską granicę. Mieszkańcom nakazano schronienie.", True),
        ("NATO prowadzi zaplanowane ćwiczenia w Polsce. Nie ma nowego zagrożenia.", True),
        ("Rosja zaatakowala Polske.", True),
        ("", False),
        ("123456", False),
        ("Na Łotwie wydano nakaz schronienia: «негайно перейти в укриття».", False),
    ],
)
def test_local_language_gate(text, expected):
    assert bool(is_polish(text, tuple(SummaryLanguageConfig().detector_languages))) == expected


def test_fallback_config_cannot_be_nonpolish():
    with pytest.raises(ValidationError, match="fallback must be Polish"):
        SummaryLanguageConfig(fallback_pl="The summary is unavailable. Please check the source information.")
    with pytest.raises(ValidationError, match="include pl/en/uk/ru"):
        SummaryLanguageConfig(detector_languages=["pl"])


@pytest.mark.asyncio
async def test_guard_leaves_polish_untouched_and_free():
    provider = AsyncMock()
    summary, metadata, reply = await ensure_polish(POLISH, provider, SummaryLanguageConfig())
    assert summary == POLISH and metadata["action"] == "unchanged" and reply is None
    provider.request.assert_not_called()


@pytest.mark.asyncio
async def test_repair_changes_only_summary_and_accounts_both_calls(direct_config, sample_article, monkeypatch, db):
    original = answer()
    original["summary_pl"] = UKRAINIAN
    original["affected_countries"] = ["LV"]
    expected = copy.deepcopy(original)
    requests = []

    def handler(request):
        sent = json.loads(request.content)
        requests.append(sent)
        if sent["text"]["format"]["name"] == "classification":
            return httpx.Response(200, json=response(original))
        assert sent["text"]["format"]["name"] == "summary_translation"
        assert set(sent["text"]["format"]["schema"]["properties"]) == {"summary_pl"}
        assert json.loads(sent["input"][1]["content"]) == {"summary": UKRAINIAN}
        return httpx.Response(200, json=response({"summary_pl": POLISH}))

    classifier = await classifier_with_http(direct_config, monkeypatch, handler)
    try:
        result = await classifier.classify(sample_article)
        assert len(requests) == 2
        assert result.summary_pl == POLISH
        for key, value in expected.items():
            if key != "summary_pl":
                assert getattr(result, key) == value
        assert result.summary_processing["action"] == "translated"
        assert result.summary_processing["original_summary"] == UKRAINIAN
        assert result.summary_processing["repair_request_hash"]
        assert result.summary_processing["translation_prompt_sha256"]
        assert result.input_tokens == 200 and result.output_tokens == 100 and result.cached_input_tokens == 40
        assert result.estimated_cost_usd == classifier.provider.ledger.total()
        db.insert_article(sample_article)
        db.insert_classification(result)
        restored = ClassificationResult.from_row(db.conn.execute("SELECT * FROM classifications").fetchone())
        assert restored == result
    finally:
        await classifier.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["quota", "refusal", "incomplete", "nonpolish", "malformed", "budget", "deadline"])
async def test_repair_failure_preserves_critical_notification(direct_config, sample_article, monkeypatch, db, failure):
    original = answer()
    original["summary_pl"] = UKRAINIAN
    calls = []

    async def handler(request):
        sent = json.loads(request.content)
        calls.append(sent)
        if len(calls) == 1:
            return httpx.Response(200, json=response(original))
        if failure == "quota":
            return httpx.Response(
                429,
                json={"error": {"message": "exhausted", "code": "insufficient_quota", "type": "insufficient_quota"}},
            )
        raw = response({"summary_pl": UKRAINIAN if failure == "nonpolish" else POLISH})
        if failure == "refusal":
            raw["output"][0]["content"] = [{"type": "refusal", "refusal": "Refused"}]
        if failure == "incomplete":
            raw["status"] = "incomplete"
        if failure == "malformed":
            raw["output"][0]["content"][0]["text"] = "{}"
        if failure == "deadline":
            import asyncio

            await asyncio.sleep(1)
        return httpx.Response(200, json=raw)

    direct_config.classification.corroboration_required = 1
    direct_config.alerts.urgency_levels["critical"].corroboration_required = 1
    classifier = await classifier_with_http(direct_config, monkeypatch, handler)
    real_request = classifier.provider.request

    async def limited_request(*args, **kwargs):
        if kwargs["purpose"] == "summary_translation":
            assert kwargs["timeout_seconds"] == direct_config.classification.summary_language.repair_timeout_seconds
            if failure == "budget":
                raise BudgetExceeded("Budget reached")
        return await real_request(*args, **kwargs)

    classifier.provider.request = limited_request
    if failure == "deadline":
        direct_config.classification.summary_language.repair_timeout_seconds = 0.01
    try:
        result = await classifier.classify(sample_article)
        assert result.summary_processing["action"] == "fallback"
        assert result.summary_pl == direct_config.classification.summary_language.fallback_pl
        assert result.urgency_score == 10 and result.affected_countries == ["PL"]
        assert result.is_military_event is True
        assert result.incident_memory == original["incident_memory"]
        assert len(calls) == (1 if failure == "budget" else 2)
        db.insert_article(sample_article)
        IncidentMemory(db, direct_config).validate(result, [], sample_article)
        event = Corroborator(db, direct_config).process_classifications([result])[0]
        await RecordingAlerts(db, RecordingTransport(), direct_config, push_client=RecordingTransport()).process_event(
            event
        )
        records = db.get_alert_records(event.id)
        assert sum(r.alert_type == "phone_call" for r in records) == 1
        assert all("Влада" not in r.message_body for r in records)
    finally:
        await classifier.aclose()


@pytest.mark.asyncio
async def test_nonpolish_second_answer_never_loops():
    reply = StructuredReply({"summary_pl": UKRAINIAN}, 10, 0, 10, 0.0001, "hash", "response")
    provider = AsyncMock()
    provider.request.return_value = reply
    summary, metadata, returned = await ensure_polish(UKRAINIAN, provider, SummaryLanguageConfig())
    assert metadata["action"] == "fallback" and is_polish(summary, tuple(SummaryLanguageConfig().detector_languages))
    assert provider.request.await_count == 1 and returned == reply
