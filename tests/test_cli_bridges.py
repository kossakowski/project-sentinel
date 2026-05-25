"""Smoke tests for the async CLI / eval bridges.

Phase 2 of the async refactor (SPEC_ASYNC_REFACTOR.md) made the classifier
coroutine-based. The synchronous CLI entry points in ``sentinel.py`` and the
eval harness now bridge to the async classify path via ``asyncio.run(...)``.
These tests assert those bridges complete with mocked dependencies and that
``_run_test_file`` drives all classifications under a SINGLE ``asyncio.run``
(not one event loop per article).

Phase 3 will extend this file with a ``_run_test_alert`` async-bridge case.
"""

import asyncio
import importlib.util
import inspect
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from sentinel.eval.harness import EvalReport, run_eval
from sentinel.scheduler import CycleResult, SentinelPipeline

# ``sentinel.py`` (the CLI entry-point script) is shadowed on the import path by
# the ``sentinel/`` package, so a plain ``import sentinel`` yields the package,
# not the script. Load the script file directly under a distinct module name so
# the CLI bridge functions (_run_test_headline / _run_test_file) are importable
# and their module-level ``asyncio.run`` is patchable. Importing is safe because
# the script guards execution with ``if __name__ == "__main__"``.
_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sentinel.py")
_spec = importlib.util.spec_from_file_location("sentinel_cli_entry", _SCRIPT_PATH)
sentinel_cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sentinel_cli)


def _fake_classification(headline: str = "headline") -> SimpleNamespace:
    """A stand-in classification result with the fields _print_classification_result reads."""
    return SimpleNamespace(
        is_military_event=True,
        event_type="invasion",
        urgency_score=10,
        affected_countries=["PL"],
        aggressor="RU",
        confidence=0.95,
        summary_pl="Rosja zaatakowala Polske.",
        input_tokens=100,
        output_tokens=50,
    )


# ---------------------------------------------------------------------------
# Acceptance test #7 [2.4a, 2.4b] -- CLI classify bridges complete; _run_test_file
# uses a single asyncio.run.
# ---------------------------------------------------------------------------


def test_cli_classify_bridges_complete(config, tmp_path):
    """_run_test_headline and _run_test_file both complete; _run_test_file uses ONE asyncio.run."""
    logger = MagicMock()

    # Patch the Classifier class so the local `from ... import Classifier` inside
    # the CLI functions picks up our mock; its classify is an awaitable AsyncMock.
    classifier_instance = MagicMock()
    classifier_instance.classify = AsyncMock(side_effect=lambda article: _fake_classification(article.title))

    # Wrap asyncio.run so it still actually drives the coroutine (no leaked
    # coroutine warnings) but we can count how many event loops are spun up.
    real_run = asyncio.run
    run_calls = []

    def counting_run(coro):
        run_calls.append(coro)
        return real_run(coro)

    # This test invokes the real ``asyncio.run`` (via counting_run) exactly as the
    # production CLI does. ``asyncio.run`` closes the loop and clears the current
    # event loop on exit; some legacy sibling tests call ``asyncio.get_event_loop()``
    # and would then see "no current event loop". Restore a fresh loop afterwards so
    # this test never pollutes global event-loop state for the rest of the session.
    try:
        # --- single headline: one asyncio.run ---
        with (
            patch("sentinel.classification.classifier.Classifier", return_value=classifier_instance),
            patch.object(sentinel_cli.asyncio, "run", side_effect=counting_run),
        ):
            sentinel_cli._run_test_headline("Russia invades Poland", config, logger)

        assert len(run_calls) == 1
        classifier_instance.classify.assert_awaited_once()

        # --- multi-headline file: still exactly ONE asyncio.run for all of them ---
        run_calls.clear()
        classifier_instance.classify.reset_mock()

        headlines_file = tmp_path / "headlines.yaml"
        headlines_file.write_text(
            yaml.safe_dump({"headlines": ["headline one", "headline two", "headline three"]}),
            encoding="utf-8",
        )

        with (
            patch("sentinel.classification.classifier.Classifier", return_value=classifier_instance),
            patch.object(sentinel_cli.asyncio, "run", side_effect=counting_run),
        ):
            sentinel_cli._run_test_file(str(headlines_file), config, logger)

        # All three headlines classified, but under a SINGLE event loop.
        assert len(run_calls) == 1
        assert classifier_instance.classify.await_count == 3
    finally:
        asyncio.set_event_loop(asyncio.new_event_loop())


# ---------------------------------------------------------------------------
# Acceptance test #5 [2.3a] -- run_eval is a coroutine and returns an EvalReport.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_eval_is_async(config, tmp_path):
    """run_eval is a coroutine; awaiting it with a mocked classifier returns an EvalReport."""
    assert inspect.iscoroutinefunction(run_eval)

    eval_set = tmp_path / "eval_set.yaml"
    eval_set.write_text(
        yaml.safe_dump(
            [
                {
                    "id": "case-1",
                    "headline": "Russia invades Poland",
                    "language": "en",
                    "source": "test",
                    "expected": {
                        "is_military_event": True,
                        "urgency_min": 9,
                        "urgency_max": 10,
                        "expected_action": "phone_call",
                    },
                },
                {
                    "id": "case-2",
                    "headline": "NATO holds annual exercise",
                    "language": "en",
                    "source": "test",
                    "expected": {
                        "is_military_event": False,
                        "urgency_min": 1,
                        "urgency_max": 2,
                        "expected_action": "log_only",
                    },
                },
            ]
        ),
        encoding="utf-8",
    )

    classifier_instance = MagicMock()

    async def fake_classify(article):
        return SimpleNamespace(
            article_id=article.id,
            is_military_event=True,
            event_type="invasion",
            urgency_score=10,
            affected_countries=["PL"],
            aggressor="RU",
            confidence=0.95,
            summary_pl="Rosja zaatakowala Polske.",
            input_tokens=100,
            output_tokens=50,
        )

    classifier_instance.classify = AsyncMock(side_effect=fake_classify)

    with patch("sentinel.eval.harness.Classifier", return_value=classifier_instance):
        report = await run_eval(str(eval_set), config)

    assert isinstance(report, EvalReport)
    assert report.eval_set_count == 2
    assert len(report.case_results) == 2
    assert classifier_instance.classify.await_count == 2


# ---------------------------------------------------------------------------
# Acceptance test #6 [2.2a] -- run_cycle awaits classify_batch exactly once.
# ---------------------------------------------------------------------------


@pytest.fixture
def _cycle_pipeline(config, tmp_path):
    """A SentinelPipeline with the real run_cycle but every component stubbed."""
    config.database.path = str(tmp_path / "cli_bridge_test.db")
    with (
        patch.object(SentinelPipeline, "_init_fetchers", return_value=[]),
        patch("sentinel.scheduler.Classifier"),
        patch("sentinel.scheduler.TwilioClient"),
    ):
        pipeline = SentinelPipeline(config)

    yield pipeline
    pipeline.db.close()


@pytest.mark.asyncio
async def test_run_cycle_awaits_classifier(_cycle_pipeline):
    """run_cycle awaits classifier.classify_batch once and completes cleanly."""
    pipeline = _cycle_pipeline

    article = SimpleNamespace(id="a1", title="Russia invades Poland")

    # Make the keyword filter yield one relevant article so the classify step runs.
    pipeline._fetch_all = AsyncMock(return_value=[article])
    pipeline.normalizer.normalize_batch = MagicMock(return_value=[article])
    pipeline.deduplicator.deduplicate_batch = MagicMock(return_value=[article])
    pipeline.keyword_filter.filter_batch = MagicMock(return_value=[article])
    pipeline.enricher.enrich_batch = AsyncMock(return_value=[article])

    classify_batch = AsyncMock(return_value=[])
    pipeline.classifier.classify_batch = classify_batch

    pipeline.corroborator.process_classifications = MagicMock(return_value=[])
    pipeline.dispatcher.dispatch = MagicMock()
    pipeline.state_machine.check_pending_calls = MagicMock()
    pipeline.db.cleanup_old_records = MagicMock()

    result = await pipeline.run_cycle()

    classify_batch.assert_awaited_once_with([article])
    assert isinstance(result, CycleResult)
