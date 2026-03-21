"""Tests for sentinel.classification.classifier."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from sentinel.classification.classifier import Classifier, _JSON_BLOCK_RE
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
        "published_at": datetime.now(timezone.utc),
        "fetched_at": datetime.now(timezone.utc),
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

    @patch("sentinel.classification.classifier.anthropic.Anthropic")
    def test_classify_invasion_headline(self, mock_anthropic_cls, config):
        """'Russia invades Poland' -> urgency 10, event_type 'invasion'."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(_invasion_response())

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="Russia invades Poland",
            summary="Russian forces crossed the Polish border in a full-scale invasion.",
        )
        result = classifier.classify(article)

        assert result.urgency_score == 10
        assert result.event_type == "invasion"
        assert result.is_military_event is True

    @patch("sentinel.classification.classifier.anthropic.Anthropic")
    def test_classify_exercise_headline(self, mock_anthropic_cls, config):
        """'NATO conducts military exercises in Poland' -> not military event, urgency 1-2."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(_exercise_response())

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="NATO conducts military exercises in Poland",
            summary="Annual NATO exercises take place in eastern Poland.",
        )
        result = classifier.classify(article)

        assert result.is_military_event is False
        assert 1 <= result.urgency_score <= 2

    @patch("sentinel.classification.classifier.anthropic.Anthropic")
    def test_classify_airspace_violation(self, mock_anthropic_cls, config):
        """'Russian drone violates Polish airspace' -> urgency 6-8."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response({
            "is_military_event": True,
            "event_type": "airspace_violation",
            "urgency_score": 7,
            "affected_countries": ["PL"],
            "aggressor": "RU",
            "is_new_event": True,
            "confidence": 0.8,
            "summary_pl": "Rosyjski dron naruszyl polska przestrzen powietrzna.",
        })

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="Russian drone violates Polish airspace",
            summary="A Russian military drone entered Polish airspace.",
        )
        result = classifier.classify(article)

        assert 6 <= result.urgency_score <= 8
        assert result.event_type == "airspace_violation"

    @patch("sentinel.classification.classifier.anthropic.Anthropic")
    def test_classify_historical(self, mock_anthropic_cls, config):
        """'Anniversary of WWII invasion of Poland' -> not military event, urgency 1."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response({
            "is_military_event": False,
            "event_type": "none",
            "urgency_score": 1,
            "affected_countries": [],
            "aggressor": "none",
            "is_new_event": False,
            "confidence": 0.95,
            "summary_pl": "Rocznica inwazji z II wojny swiatowej.",
        })

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="Anniversary of WWII invasion of Poland",
            summary="Poland commemorates the 85th anniversary of the WWII invasion.",
        )
        result = classifier.classify(article)

        assert result.is_military_event is False
        assert result.urgency_score == 1

    @patch("sentinel.classification.classifier.anthropic.Anthropic")
    def test_classify_opinion_piece(self, mock_anthropic_cls, config):
        """'Analysis: Could Russia attack the Baltics?' -> not military event, urgency 2-3."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response({
            "is_military_event": False,
            "event_type": "none",
            "urgency_score": 2,
            "affected_countries": ["LT", "LV", "EE"],
            "aggressor": "none",
            "is_new_event": False,
            "confidence": 0.85,
            "summary_pl": "Analiza mozliwosci ataku Rosji na kraje baltyckie.",
        })

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="Analysis: Could Russia attack the Baltics?",
            summary="Experts analyze the likelihood of Russian aggression.",
        )
        result = classifier.classify(article)

        assert result.is_military_event is False
        assert 2 <= result.urgency_score <= 3

    @patch("sentinel.classification.classifier.anthropic.Anthropic")
    def test_classify_polish_headline(self, mock_anthropic_cls, config):
        """'Rosja zaatakowala Polske' -> urgency 10, summary_pl in Polish."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response({
            "is_military_event": True,
            "event_type": "invasion",
            "urgency_score": 10,
            "affected_countries": ["PL"],
            "aggressor": "RU",
            "is_new_event": True,
            "confidence": 0.95,
            "summary_pl": "Rosja zaatakowala Polske. Trwa inwazja.",
        })

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="Rosja zaatakowala Polske",
            summary="Sily zbrojne Rosji przekroczyly granice Polski.",
            language="pl",
        )
        result = classifier.classify(article)

        assert result.urgency_score == 10
        assert len(result.summary_pl) > 0

    @patch("sentinel.classification.classifier.anthropic.Anthropic")
    def test_classify_ukrainian_headline(self, mock_anthropic_cls, config):
        """Ukrainian headline about invasion -> urgency 10."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(_invasion_response())

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="\u0420\u043e\u0441\u0456\u044f \u0432\u0442\u043e\u0440\u0433\u043b\u0430\u0441\u044f \u0432 \u041f\u043e\u043b\u044c\u0449\u0443",
            summary="\u0420\u043e\u0441\u0456\u0439\u0441\u044c\u043a\u0456 \u0432\u0456\u0439\u0441\u044c\u043a\u0430 \u043f\u0435\u0440\u0435\u0442\u043d\u0443\u043b\u0438 \u043a\u043e\u0440\u0434\u043e\u043d \u041f\u043e\u043b\u044c\u0449\u0456.",
            language="uk",
        )
        result = classifier.classify(article)

        assert result.urgency_score == 10

    @patch("sentinel.classification.classifier.anthropic.Anthropic")
    def test_classify_russian_provocation_framing(self, mock_anthropic_cls, config):
        """Russian media framing -> urgency 7+."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response({
            "is_military_event": True,
            "event_type": "border_crossing",
            "urgency_score": 8,
            "affected_countries": ["PL"],
            "aggressor": "RU",
            "is_new_event": True,
            "confidence": 0.7,
            "summary_pl": "Rosyjskie media informuja o prowokacji ze strony Polski.",
        })

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="Polska provocirovala Rossiju",
            summary="Poland provoked Russia at the border.",
            language="ru",
        )
        result = classifier.classify(article)

        assert result.urgency_score >= 7

    @patch("sentinel.classification.classifier.anthropic.Anthropic")
    def test_classify_ambiguous(self, mock_anthropic_cls, config):
        """'Troops seen near Polish border' -> urgency 4-6, confidence < 0.7."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response({
            "is_military_event": True,
            "event_type": "troop_movement",
            "urgency_score": 5,
            "affected_countries": ["PL"],
            "aggressor": "RU",
            "is_new_event": True,
            "confidence": 0.5,
            "summary_pl": "Zaobserwowano ruchy wojsk w poblizu polskiej granicy.",
        })

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(
            title="Troops seen near Polish border",
            summary="Unconfirmed reports of troop movements.",
        )
        result = classifier.classify(article)

        assert 4 <= result.urgency_score <= 6
        assert result.confidence < 0.7

    @patch("sentinel.classification.classifier.anthropic.Anthropic")
    def test_json_parse_recovery(self, mock_anthropic_cls, config):
        """LLM returns JSON wrapped in markdown -> extracted successfully."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # Wrap JSON in markdown code block
        data = _invasion_response()
        markdown_wrapped = f"```json\n{json.dumps(data)}\n```"
        content_block = SimpleNamespace(text=markdown_wrapped)
        usage = SimpleNamespace(input_tokens=100, output_tokens=50)
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[content_block], usage=usage
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(title="Russia invades Poland")
        result = classifier.classify(article)

        assert result.is_military_event is True
        assert result.urgency_score == 10

    @patch("sentinel.classification.classifier.anthropic.Anthropic")
    def test_api_error_handled(self, mock_anthropic_cls, config):
        """API returns 500 -> logged, article skipped in batch."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # Both attempts fail
        mock_client.messages.create.side_effect = anthropic.APIStatusError(
            message="Internal Server Error",
            response=MagicMock(status_code=500),
            body=None,
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(title="Russia invades Poland")
        results = classifier.classify_batch([article])

        assert len(results) == 0

    @patch("sentinel.classification.classifier.anthropic.Anthropic")
    def test_token_usage_logged(self, mock_anthropic_cls, config):
        """Input/output tokens are recorded in the result."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(
            _invasion_response(), input_tokens=287, output_tokens=94
        )

        classifier = Classifier(config)
        classifier.client = mock_client

        article = _make_article(title="Russia invades Poland")
        result = classifier.classify(article)

        assert result.input_tokens == 287
        assert result.output_tokens == 94
