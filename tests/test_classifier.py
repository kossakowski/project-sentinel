"""Tests for sentinel.classification.classifier."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from sentinel.classification.classifier import Classifier
from sentinel.models import Article


def _make_article(**overrides) -> Article:
    """Helper to build an Article with sensible defaults."""
    defaults = {
        "source_name": "TestSource",
        "source_url": "https://example.com/article/1",
        "source_type": "rss",
        "title": "Test Title",
        "summary": "Test summary.",
        "language": "en",
        "published_at": datetime.now(UTC),
        "fetched_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return Article(**defaults)


def _mock_response(data: dict, input_tokens: int = 100, output_tokens: int = 50):
    """Build a mock Anthropic API response."""
    content_block = SimpleNamespace(text=json.dumps(data))
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(content=[content_block], usage=usage)


def _invasion_response() -> dict:
    return {
        "is_military_event": True,
        "event_type": "invasion",
        "urgency_score": 10,
        "affected_countries": ["PL"],
        "aggressor": "RU",
        "is_new_event": True,
        "confidence": 0.95,
        "summary_pl": "Rosja dokonala inwazji na Polske.",
    }


def _exercise_response() -> dict:
    return {
        "is_military_event": False,
        "event_type": "none",
        "urgency_score": 2,
        "affected_countries": ["PL"],
        "aggressor": "none",
        "is_new_event": False,
        "confidence": 0.9,
        "summary_pl": "NATO prowadzi cwiczenia wojskowe w Polsce.",
    }


class TestClassifier:
    """Acceptance tests for the Classifier."""

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_classify_invasion_headline(self, mock_anthropic_cls, config):
        """'Russia invades Poland' -> urgency 10, event_type 'invasion'."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(_invasion_response()))

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="Russia invades Poland",
            summary="Russian forces crossed the Polish border in a full-scale invasion.",
        )
        result = await classifier.classify(article)

        assert result.urgency_score == 10
        assert result.event_type == "invasion"
        assert result.is_military_event is True

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_classify_exercise_headline(self, mock_anthropic_cls, config):
        """'NATO conducts military exercises in Poland' -> not military event, urgency 1-2."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(_exercise_response()))

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="NATO conducts military exercises in Poland",
            summary="Annual NATO exercises take place in eastern Poland.",
        )
        result = await classifier.classify(article)

        assert result.is_military_event is False
        assert 1 <= result.urgency_score <= 2

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_classify_airspace_violation(self, mock_anthropic_cls, config):
        """'Russian drone violates Polish airspace' -> urgency 6-8."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response(
                {
                    "is_military_event": True,
                    "event_type": "airspace_violation",
                    "urgency_score": 7,
                    "affected_countries": ["PL"],
                    "aggressor": "RU",
                    "is_new_event": True,
                    "confidence": 0.8,
                    "summary_pl": "Rosyjski dron naruszyl polska przestrzen powietrzna.",
                }
            )
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="Russian drone violates Polish airspace",
            summary="A Russian military drone entered Polish airspace.",
        )
        result = await classifier.classify(article)

        assert 6 <= result.urgency_score <= 8
        assert result.event_type == "airspace_violation"

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_classify_historical(self, mock_anthropic_cls, config):
        """'Anniversary of WWII invasion of Poland' -> not military event, urgency 1."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response(
                {
                    "is_military_event": False,
                    "event_type": "none",
                    "urgency_score": 1,
                    "affected_countries": [],
                    "aggressor": "none",
                    "is_new_event": False,
                    "confidence": 0.95,
                    "summary_pl": "Rocznica inwazji z II wojny swiatowej.",
                }
            )
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="Anniversary of WWII invasion of Poland",
            summary="Poland commemorates the 85th anniversary of the WWII invasion.",
        )
        result = await classifier.classify(article)

        assert result.is_military_event is False
        assert result.urgency_score == 1

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_classify_opinion_piece(self, mock_anthropic_cls, config):
        """'Analysis: Could Russia attack the Baltics?' -> not military event, urgency 2-3."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response(
                {
                    "is_military_event": False,
                    "event_type": "none",
                    "urgency_score": 2,
                    "affected_countries": ["LT", "LV", "EE"],
                    "aggressor": "none",
                    "is_new_event": False,
                    "confidence": 0.85,
                    "summary_pl": "Analiza mozliwosci ataku Rosji na kraje baltyckie.",
                }
            )
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="Analysis: Could Russia attack the Baltics?",
            summary="Experts analyze the likelihood of Russian aggression.",
        )
        result = await classifier.classify(article)

        assert result.is_military_event is False
        assert 2 <= result.urgency_score <= 3

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_classify_polish_headline(self, mock_anthropic_cls, config):
        """'Rosja zaatakowala Polske' -> urgency 10, summary_pl in Polish."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response(
                {
                    "is_military_event": True,
                    "event_type": "invasion",
                    "urgency_score": 10,
                    "affected_countries": ["PL"],
                    "aggressor": "RU",
                    "is_new_event": True,
                    "confidence": 0.95,
                    "summary_pl": "Rosja zaatakowala Polske. Trwa inwazja.",
                }
            )
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="Rosja zaatakowala Polske",
            summary="Sily zbrojne Rosji przekroczyly granice Polski.",
            language="pl",
        )
        result = await classifier.classify(article)

        assert result.urgency_score == 10
        assert len(result.summary_pl) > 0

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_classify_ukrainian_headline(self, mock_anthropic_cls, config):
        """Ukrainian headline about invasion -> urgency 10."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(_invasion_response()))

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="\u0420\u043e\u0441\u0456\u044f \u0432\u0442\u043e\u0440\u0433\u043b\u0430\u0441\u044f \u0432 \u041f\u043e\u043b\u044c\u0449\u0443",
            summary="\u0420\u043e\u0441\u0456\u0439\u0441\u044c\u043a\u0456 \u0432\u0456\u0439\u0441\u044c\u043a\u0430 \u043f\u0435\u0440\u0435\u0442\u043d\u0443\u043b\u0438 \u043a\u043e\u0440\u0434\u043e\u043d \u041f\u043e\u043b\u044c\u0449\u0456.",
            language="uk",
        )
        result = await classifier.classify(article)

        assert result.urgency_score == 10

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_classify_russian_provocation_framing(self, mock_anthropic_cls, config):
        """Russian media framing -> urgency 7+."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response(
                {
                    "is_military_event": True,
                    "event_type": "border_crossing",
                    "urgency_score": 8,
                    "affected_countries": ["PL"],
                    "aggressor": "RU",
                    "is_new_event": True,
                    "confidence": 0.7,
                    "summary_pl": "Rosyjskie media informuja o prowokacji ze strony Polski.",
                }
            )
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="Polska provocirovala Rossiju",
            summary="Poland provoked Russia at the border.",
            language="ru",
        )
        result = await classifier.classify(article)

        assert result.urgency_score >= 7

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_classify_ambiguous(self, mock_anthropic_cls, config):
        """'Troops seen near Polish border' -> urgency 4-6, confidence < 0.7."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response(
                {
                    "is_military_event": True,
                    "event_type": "troop_movement",
                    "urgency_score": 5,
                    "affected_countries": ["PL"],
                    "aggressor": "RU",
                    "is_new_event": True,
                    "confidence": 0.5,
                    "summary_pl": "Zaobserwowano ruchy wojsk w poblizu polskiej granicy.",
                }
            )
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="Troops seen near Polish border",
            summary="Unconfirmed reports of troop movements.",
        )
        result = await classifier.classify(article)

        assert 4 <= result.urgency_score <= 6
        assert result.confidence < 0.7

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_json_parse_recovery(self, mock_anthropic_cls, config):
        """LLM returns JSON wrapped in markdown -> extracted successfully."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # Wrap JSON in markdown code block
        data = _invasion_response()
        markdown_wrapped = f"```json\n{json.dumps(data)}\n```"
        content_block = SimpleNamespace(text=markdown_wrapped)
        usage = SimpleNamespace(input_tokens=100, output_tokens=50)
        mock_client.messages.create = AsyncMock(return_value=SimpleNamespace(content=[content_block], usage=usage))

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(title="Russia invades Poland")
        result = await classifier.classify(article)

        assert result.is_military_event is True
        assert result.urgency_score == 10

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.asyncio.sleep", new_callable=AsyncMock)
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_api_error_handled(self, mock_anthropic_cls, mock_sleep, config):
        """API returns 500 -> logged, article skipped in batch."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # Both attempts fail
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic.APIStatusError(
                message="Internal Server Error",
                response=MagicMock(status_code=500),
                body=None,
            )
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(title="Russia invades Poland")
        results = await classifier.classify_batch([article])

        assert len(results) == 0
        mock_sleep.assert_awaited_once_with(5)

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_token_usage_logged(self, mock_anthropic_cls, config):
        """Input/output tokens are recorded in the result."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response(_invasion_response(), input_tokens=287, output_tokens=94)
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(title="Russia invades Poland")
        result = await classifier.classify(article)

        assert result.input_tokens == 287
        assert result.output_tokens == 94

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_classify_batch_is_sequential(self, mock_anthropic_cls, config):
        """classify_batch awaits one article at a time (no concurrency) and preserves order."""
        mock_anthropic_cls.return_value = MagicMock()
        classifier = Classifier(config)

        concurrency = 0
        max_concurrency = 0
        call_order: list[str] = []

        async def fake_classify(article):
            nonlocal concurrency, max_concurrency
            concurrency += 1
            max_concurrency = max(max_concurrency, concurrency)
            await asyncio.sleep(0)
            concurrency -= 1
            call_order.append(article.title)
            return SimpleNamespace(
                article_id=article.id,
                title=article.title,
                urgency_score=5,
                event_type="other",
                is_military_event=True,
            )

        classifier.classify = AsyncMock(side_effect=fake_classify)

        articles = [
            _make_article(title="first"),
            _make_article(title="second"),
            _make_article(title="third"),
        ]
        results = await classifier.classify_batch(articles)

        assert max_concurrency == 1
        assert [r.title for r in results] == ["first", "second", "third"]
        assert call_order == ["first", "second", "third"]

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_classify_batch_skips_failures(self, mock_anthropic_cls, config):
        """A failing article (APIError / JSONDecodeError) is skipped; others kept in order."""
        mock_anthropic_cls.return_value = MagicMock()
        classifier = Classifier(config)

        article_api_err = _make_article(title="api-error")
        article_json_err = _make_article(title="json-error")
        article_ok = _make_article(title="ok")

        ok_result = SimpleNamespace(
            article_id=article_ok.id,
            title="ok",
            urgency_score=5,
            event_type="other",
            is_military_event=True,
        )

        async def fake_classify(article):
            if article.title == "api-error":
                raise anthropic.APIError(message="boom", request=MagicMock(), body=None)
            if article.title == "json-error":
                raise json.JSONDecodeError("bad", "", 0)
            return ok_result

        classifier.classify = AsyncMock(side_effect=fake_classify)

        results = await classifier.classify_batch([article_api_err, article_json_err, article_ok])

        assert results == [ok_result]

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_classifier_aclose(self, mock_anthropic_cls, config):
        """aclose() awaits the underlying async client's close() exactly once."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.close = AsyncMock()

        classifier = Classifier(config)
        classifier.client = mock_client

        await classifier.aclose()

        mock_client.close.assert_awaited_once_with()

    # ------------------------------------------------------------------
    # Geography seam: target_country / attacker_is_nato are parsed AND persisted.
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_classify_parses_geo_fields(self, mock_anthropic_cls, config):
        """target_country and attacker_is_nato are read off the response onto the result."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response(
                {
                    "is_military_event": True,
                    "event_type": "missile_strike",
                    "urgency_score": 9,
                    "affected_countries": ["RU"],
                    "target_country": "RU",
                    "attacker_is_nato": True,
                    "aggressor": "none",
                    "is_new_event": True,
                    "confidence": 0.9,
                    "summary_pl": "NATO uderzylo na terytorium Rosji.",
                }
            )
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        result = await classifier.classify(_make_article(title="NATO strikes Russian territory"))

        assert result.target_country == "RU"
        assert result.attacker_is_nato is True

        # Defaults when the model omits them (never a crash, never a silent True).
        mock_client.messages.create = AsyncMock(return_value=_mock_response(_invasion_response()))
        plain = await classifier.classify(_make_article(title="Russia invades Poland"))
        assert plain.target_country is None
        assert plain.attacker_is_nato is False

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_classify_handles_null_affected_countries(self, mock_anthropic_cls, config):
        """`"affected_countries": null` must not raise -- one malformed response cannot kill a cycle.

        `data.get("affected_countries", [])` returns None when the key is PRESENT with a
        null value, so the default never applies. If that None escaped, the whole
        classify_batch would abort and the scheduler would discard every classification
        of the cycle -- including a possible urgency 9-10.
        """
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response(
                {
                    "is_military_event": True,
                    "event_type": "missile_strike",
                    "urgency_score": 9,
                    "affected_countries": None,
                    "target_country": None,
                    "aggressor": "RU",
                    "is_new_event": True,
                    "confidence": 0.8,
                    "summary_pl": "Atak rakietowy.",
                }
            )
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        result = await classifier.classify(_make_article(title="Missile strike reported"))

        assert result.affected_countries == []
        assert result.target_country is None
        assert result.urgency_score == 9

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_classify_batch_survives_unexpected_error(self, mock_anthropic_cls, config):
        """An UNEXPECTED error on one article skips that article -- the batch keeps going.

        The scheduler treats a raised batch as "no classifications this cycle" and the
        articles are already stored (never re-classified), so a single malformed response
        must never discard a real urgency 9-10 sitting later in the same batch.
        """
        mock_anthropic_cls.return_value = MagicMock()
        classifier = Classifier(config)

        boom = _make_article(title="boom")
        critical = _make_article(title="Russia invades Poland")
        critical_result = SimpleNamespace(
            article_id=critical.id,
            title=critical.title,
            urgency_score=10,
            event_type="invasion",
            is_military_event=True,
        )

        async def fake_classify(article):
            if article.title == "boom":
                raise TypeError("'NoneType' object is not iterable")
            return critical_result

        classifier.classify = AsyncMock(side_effect=fake_classify)

        results = await classifier.classify_batch([boom, critical])

        assert results == [critical_result]

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_kinetic_floor_basis_is_target_country(self, mock_anthropic_cls, config):
        """A kinetic strike TARGETING Ukraine that lists PL as affected is not floored to a call."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response(
                {
                    "is_military_event": True,
                    "event_type": "missile_strike",
                    "urgency_score": 4,
                    "affected_countries": ["UA", "PL"],
                    "target_country": "UA",
                    "aggressor": "RU",
                    "is_new_event": True,
                    "confidence": 0.8,
                    "summary_pl": "Rosyjski atak na Ukraine; polskie mysliwce poderwane.",
                }
            )
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        result = await classifier.classify(_make_article(title="Russian strike on Ukraine, Polish jets scrambled"))
        assert result.urgency_score == 4

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_kinetic_floor_applies_when_target_unresolved(self, mock_anthropic_cls, config):
        """An unresolved target on a kinetic story naming Polish soil still floors to call tier."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response(
                {
                    "is_military_event": True,
                    "event_type": "missile_strike",
                    "urgency_score": 4,
                    "affected_countries": ["PL"],
                    "target_country": "unknown",
                    "aggressor": "RU",
                    "is_new_event": True,
                    "confidence": 0.6,
                    "summary_pl": "Uderzenie rakietowe na terytorium Polski.",
                }
            )
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        result = await classifier.classify(_make_article(title="Missile hits Polish territory"))
        assert result.urgency_score >= 9


# --------------------------------------------------------------------------
# attacker_is_nato strict parsing: the JSON string "false" must not become True.
# --------------------------------------------------------------------------
def test_as_bool_does_not_coerce_string_false():
    """`bool("false")` is True in Python; `_as_bool` must return False for it.

    A JSON *string* "false" (which the model sometimes emits despite the boolean
    schema) coerced to True would spuriously activate the RU+NATO HIGH tier for an
    inside-Russia story and fire a false call at urgency >= 9.
    """
    from sentinel.classification.classifier import _as_bool

    assert _as_bool("false") is False
    assert _as_bool(False) is False
    assert _as_bool(None) is False
    assert _as_bool("") is False
    assert _as_bool("no") is False
    assert _as_bool(True) is True
    assert _as_bool("true") is True
    assert _as_bool("1") is True
    assert _as_bool("yes") is True


class TestAttackerIsNatoStringFalse:
    """The string 'false' from the LLM must not flip attacker_is_nato on."""

    @pytest.mark.asyncio
    @patch("sentinel.classification.classifier.anthropic.AsyncAnthropic")
    async def test_string_false_stays_false(self, mock_anthropic_cls, config):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response(
                {
                    "is_military_event": True,
                    "event_type": "missile_strike",
                    "urgency_score": 2,
                    "affected_countries": ["RU"],
                    "target_country": "RU",
                    "attacker_is_nato": "false",
                    "aggressor": "UA",
                    "is_new_event": True,
                    "confidence": 0.7,
                    "summary_pl": "Ukrainskie uderzenie na terytorium Rosji.",
                }
            )
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        result = await classifier.classify(_make_article(title="Ukrainian strike inside Russia"))
        assert result.attacker_is_nato is False
