"""Tests for sentinel.classification.classifier."""

import asyncio
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from sentinel.classification.classifier import Classifier
from sentinel.classification.legacy_anthropic import (
    MEMORY_INSTRUCTIONS,
    SYSTEM_PROMPT,
    LegacyAnthropicBackend,
    build_user_prompt,
)
from sentinel.models import Article, ClassificationResult

REPO_ROOT = Path(__file__).resolve().parents[1]

# ``prompt_version`` of the legacy path as master wrote it: "legacy:" + sha256 of
# the system prompt, plus the incident-memory instructions when memory is on.
LEGACY_PROMPT_VERSION = "legacy:b7a817a4389b9120aa20dc4c189e708fda0dd5ee259f57a93fdfdcbdc44adb06"
LEGACY_MEMORY_PROMPT_VERSION = "legacy:be399586ba207457109a0aef63234791c0bb96a1088b51c776a585f4b2a599eb"


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
    @patch("anthropic.AsyncAnthropic")
    async def test_classify_invasion_headline(self, mock_anthropic_cls, config):
        """'Russia invades Poland' -> urgency 10, event_type 'invasion'."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(_invasion_response()))

        classifier = Classifier(config)
        classifier.backend.client = mock_client

        article = _make_article(
            title="Russia invades Poland",
            summary="Russian forces crossed the Polish border in a full-scale invasion.",
        )
        result = await classifier.classify(article)

        assert result.urgency_score == 10
        assert result.event_type == "invasion"
        assert result.is_military_event is True

    @pytest.mark.asyncio
    @patch("anthropic.AsyncAnthropic")
    async def test_classify_exercise_headline(self, mock_anthropic_cls, config):
        """'NATO conducts military exercises in Poland' -> not military event, urgency 1-2."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(_exercise_response()))

        classifier = Classifier(config)
        classifier.backend.client = mock_client

        article = _make_article(
            title="NATO conducts military exercises in Poland",
            summary="Annual NATO exercises take place in eastern Poland.",
        )
        result = await classifier.classify(article)

        assert result.is_military_event is False
        assert 1 <= result.urgency_score <= 2

    @pytest.mark.asyncio
    @patch("anthropic.AsyncAnthropic")
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
        classifier.backend.client = mock_client

        article = _make_article(
            title="Russian drone violates Polish airspace",
            summary="A Russian military drone entered Polish airspace.",
        )
        result = await classifier.classify(article)

        assert 6 <= result.urgency_score <= 8
        assert result.event_type == "airspace_violation"

    @pytest.mark.asyncio
    @patch("anthropic.AsyncAnthropic")
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
        classifier.backend.client = mock_client

        article = _make_article(
            title="Anniversary of WWII invasion of Poland",
            summary="Poland commemorates the 85th anniversary of the WWII invasion.",
        )
        result = await classifier.classify(article)

        assert result.is_military_event is False
        assert result.urgency_score == 1

    @pytest.mark.asyncio
    @patch("anthropic.AsyncAnthropic")
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
        classifier.backend.client = mock_client

        article = _make_article(
            title="Analysis: Could Russia attack the Baltics?",
            summary="Experts analyze the likelihood of Russian aggression.",
        )
        result = await classifier.classify(article)

        assert result.is_military_event is False
        assert 2 <= result.urgency_score <= 3

    @pytest.mark.asyncio
    @patch("anthropic.AsyncAnthropic")
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
        classifier.backend.client = mock_client

        article = _make_article(
            title="Rosja zaatakowala Polske",
            summary="Sily zbrojne Rosji przekroczyly granice Polski.",
            language="pl",
        )
        result = await classifier.classify(article)

        assert result.urgency_score == 10
        assert len(result.summary_pl) > 0

    @pytest.mark.asyncio
    @patch("anthropic.AsyncAnthropic")
    async def test_classify_ukrainian_headline(self, mock_anthropic_cls, config):
        """Ukrainian headline about invasion -> urgency 10."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_response(_invasion_response()))

        classifier = Classifier(config)
        classifier.backend.client = mock_client

        article = _make_article(
            title="\u0420\u043e\u0441\u0456\u044f \u0432\u0442\u043e\u0440\u0433\u043b\u0430\u0441\u044f \u0432 \u041f\u043e\u043b\u044c\u0449\u0443",
            summary="\u0420\u043e\u0441\u0456\u0439\u0441\u044c\u043a\u0456 \u0432\u0456\u0439\u0441\u044c\u043a\u0430 \u043f\u0435\u0440\u0435\u0442\u043d\u0443\u043b\u0438 \u043a\u043e\u0440\u0434\u043e\u043d \u041f\u043e\u043b\u044c\u0449\u0456.",
            language="uk",
        )
        result = await classifier.classify(article)

        assert result.urgency_score == 10

    @pytest.mark.asyncio
    @patch("anthropic.AsyncAnthropic")
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
        classifier.backend.client = mock_client

        article = _make_article(
            title="Polska provocirovala Rossiju",
            summary="Poland provoked Russia at the border.",
            language="ru",
        )
        result = await classifier.classify(article)

        assert result.urgency_score >= 7

    @pytest.mark.asyncio
    @patch("anthropic.AsyncAnthropic")
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
        classifier.backend.client = mock_client

        article = _make_article(
            title="Troops seen near Polish border",
            summary="Unconfirmed reports of troop movements.",
        )
        result = await classifier.classify(article)

        assert 4 <= result.urgency_score <= 6
        assert result.confidence < 0.7

    @pytest.mark.asyncio
    @patch("anthropic.AsyncAnthropic")
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
        classifier.backend.client = mock_client

        article = _make_article(title="Russia invades Poland")
        result = await classifier.classify(article)

        assert result.is_military_event is True
        assert result.urgency_score == 10

    @pytest.mark.asyncio
    @patch("sentinel.classification.legacy_anthropic.asyncio.sleep", new_callable=AsyncMock)
    @patch("anthropic.AsyncAnthropic")
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
        classifier.backend.client = mock_client

        article = _make_article(title="Russia invades Poland")
        results = await classifier.classify_batch([article])

        assert len(results) == 0
        mock_sleep.assert_awaited_once_with(5)

    @pytest.mark.asyncio
    @patch("anthropic.AsyncAnthropic")
    async def test_token_usage_logged(self, mock_anthropic_cls, config):
        """Input/output tokens are recorded in the result."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response(_invasion_response(), input_tokens=287, output_tokens=94)
        )

        classifier = Classifier(config)
        classifier.backend.client = mock_client

        article = _make_article(title="Russia invades Poland")
        result = await classifier.classify(article)

        assert result.input_tokens == 287
        assert result.output_tokens == 94

    @pytest.mark.asyncio
    @patch("anthropic.AsyncAnthropic")
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
    @patch("anthropic.AsyncAnthropic")
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
    @patch("anthropic.AsyncAnthropic")
    async def test_classifier_aclose(self, mock_anthropic_cls, config):
        """aclose() awaits the underlying async client's close() exactly once."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.close = AsyncMock()

        classifier = Classifier(config)
        classifier.backend.client = mock_client

        await classifier.aclose()

        mock_client.close.assert_awaited_once_with()


def test_classifier_does_not_import_anthropic():
    """The classifier module loads in a fresh interpreter in which ``anthropic`` cannot be imported."""
    probe = (
        "import sys\n"
        "sys.modules['anthropic'] = None\n"  # every `import anthropic` now raises ImportError
        "import sentinel.classification.classifier as classifier\n"
        "assert 'anthropic' not in vars(classifier)\n"
        "print('loaded')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO_ROOT, capture_output=True, text=True, timeout=120, check=False
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "loaded"
    import sentinel.classification.classifier as classifier_module

    assert "anthropic" not in vars(classifier_module)
    source = Path(classifier_module.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(?:import\s+anthropic|from\s+anthropic\b)", source, re.MULTILINE)


def test_openai_classifier_builds_without_anthropic(prod_config, monkeypatch):
    """On the live config (``provider: openai``) a Classifier is built where ``anthropic`` cannot be imported."""
    assert prod_config.classification.provider == "openai"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    probe = (
        "import sys\n"
        "sys.modules['anthropic'] = None\n"  # every `import anthropic` now raises ImportError
        "from sentinel.classification.classifier import Classifier, OpenAIBackend\n"
        "from sentinel.config import load_config\n"
        "config = load_config(sys.argv[1])\n"
        "config.classification.budget.ledger_path = ':memory:'\n"
        "assert isinstance(Classifier(config).backend, OpenAIBackend)\n"
        "print('built')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe, str(REPO_ROOT / "config" / "config.yaml")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "built"


@pytest.mark.asyncio
@pytest.mark.parametrize("with_memory", [False, True], ids=["no-memory", "memory"])
async def test_legacy_backend_still_classifies(config, monkeypatch, with_memory):
    """With ``provider: anthropic`` the Classifier sends the legacy request and returns a full result."""
    config.classification.provider = "anthropic"
    mock_client = MagicMock()
    reply = {**_invasion_response(), "incident_memory": {"decision": "new", "matched_event_id": None}}
    mock_client.messages.create = AsyncMock(return_value=_mock_response(reply, input_tokens=321, output_tokens=45))
    monkeypatch.setattr("anthropic.AsyncAnthropic", MagicMock(return_value=mock_client))

    classifier = Classifier(config)
    assert isinstance(classifier.backend, LegacyAnthropicBackend)
    assert classifier.provider is None
    article = _make_article(title="Russia invades Poland", summary="Russian forces crossed the Polish border.")
    incident_context = [{"id": "event-1"}] if with_memory else None

    result = await classifier.classify(article, incident_context=incident_context)

    assert isinstance(result, ClassificationResult)
    assert result.article_id == article.id
    assert result.is_military_event is True
    assert result.event_type == "invasion"
    assert result.urgency_score == 10
    assert result.affected_countries == ["PL"]
    assert result.aggressor == "RU"
    assert result.is_new_event is True
    assert result.confidence == 0.95
    assert result.summary_pl == "Rosja dokonala inwazji na Polske."
    assert result.incident_memory == {"decision": "new", "matched_event_id": None}
    assert result.model_used == config.classification.model
    assert result.provider_used == "anthropic"
    assert result.prompt_version == (LEGACY_MEMORY_PROMPT_VERSION if with_memory else LEGACY_PROMPT_VERSION)
    assert (result.input_tokens, result.output_tokens) == (321, 45)
    # The daily token counters still see the request.
    assert (classifier._daily_input_tokens, classifier._daily_output_tokens) == (321, 45)

    request = mock_client.messages.create.await_args.kwargs
    extra_tokens = config.classification.incident_memory.extra_output_tokens if with_memory else 0
    assert request["model"] == config.classification.model
    assert request["temperature"] == config.classification.temperature
    assert request["max_tokens"] == config.classification.max_tokens + extra_tokens
    assert request["system"] == SYSTEM_PROMPT + (MEMORY_INSTRUCTIONS if with_memory else "")
    assert request["messages"] == [{"role": "user", "content": build_user_prompt(article, incident_context)}]
