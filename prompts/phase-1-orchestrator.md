# Phase 1 Orchestrator Prompt

## Instructions

You are an orchestrator agent coordinating the implementation of Phase 1 (Infrastructure) of the Sentinel military alert monitoring system. Use high/extended thinking for planning and coordination.

**Your role**: Spawn sub-agents in sequence, validate their outputs, and ensure the phase is complete and all tests pass before finishing.

**Working directory**: `/home/kossa/code/twilio-plaground`

## Context

Sentinel is a Python bot that monitors media sources for military attacks on Poland/Baltics and alerts via Twilio phone call. Phase 1 builds the foundation: config loading, database, data models, logging, and CLI skeleton.

Read these files before starting:
- `docs/phase-1-infrastructure.md` -- the full specification for Phase 1
- `docs/architecture.md` -- system architecture (data models in section 4)
- `config/config.example.yaml` -- the example config file that must load correctly
- `CLAUDE.md` -- project rules (nothing hardcoded, tests must pass, etc.)
- `requirements.txt` -- current dependencies

## Execution Plan

### Step 1: Create package structure

Before spawning agents, create the directory structure yourself:

```
sentinel/__init__.py
sentinel/fetchers/__init__.py    (empty, placeholder for Phase 2)
sentinel/processing/__init__.py  (empty, placeholder for Phase 3)
sentinel/classification/__init__.py (empty, placeholder for Phase 4)
sentinel/alerts/__init__.py      (empty, placeholder for Phase 5)
tests/__init__.py
tests/fixtures/                  (directory only)
data/                            (directory only, for SQLite DB)
logs/                            (directory only)
```

### Step 2: Spawn Agent 1 -- Models & Config

Launch an Opus agent with the prompt from `prompts/phase-1-agent-1-models-config.md`.

**What Agent 1 produces:**
- `sentinel/models.py` -- Article, ClassificationResult, Event, AlertRecord dataclasses
- `sentinel/config.py` -- All Pydantic config models + `load_config()` function + env var substitution
- Updated `requirements.txt` with `pyyaml>=6.0` and `pydantic>=2.0`

**Validation after Agent 1:**
1. Run `python -c "from sentinel.models import Article, ClassificationResult, Event, AlertRecord; print('Models OK')"` -- must succeed
2. Run `python -c "from sentinel.config import load_config; print('Config imports OK')"` -- must succeed
3. Check that `sentinel/models.py` and `sentinel/config.py` exist and are non-empty

If validation fails, send a follow-up message to Agent 1 with the error and ask it to fix.

### Step 3: Spawn Agent 2 -- Database, CLI, Logging

Launch an Opus agent with the prompt from `prompts/phase-1-agent-2-database-cli.md`.

This agent depends on Agent 1's models being importable.

**What Agent 2 produces:**
- `sentinel/database.py` -- Database class with SQLite schema and access methods
- `sentinel/logging_setup.py` -- `setup_logging()` function
- `sentinel.py` -- CLI entry point with argparse

**Validation after Agent 2:**
1. Run `python -c "from sentinel.database import Database; db = Database(':memory:'); print('Database OK')"` -- must succeed
2. Run `python sentinel.py --help` -- must print usage and exit 0
3. Set required env vars and run `python sentinel.py --config config/config.example.yaml --dry-run --once` -- should print "Sentinel initialized successfully" (or similar) and exit 0

If validation fails, send a follow-up message to Agent 2 with the error.

### Step 4: Spawn Agent 3 -- Tests

Launch an Opus agent with the prompt from `prompts/phase-1-agent-3-tests.md`.

This agent depends on all Phase 1 code being in place.

**What Agent 3 produces:**
- `tests/conftest.py` -- shared fixtures
- `tests/test_config.py` -- 7 config tests
- `tests/test_database.py` -- 10 database tests
- `tests/test_models.py` -- 4 model roundtrip tests
- `tests/test_cli.py` -- 4 CLI tests
- `pyproject.toml` -- pytest configuration (if not exists)

**Validation after Agent 3:**
1. Run `pip install pytest pytest-asyncio pytest-mock pytest-cov` (if not installed)
2. Run `pytest tests/ -v` -- ALL tests must pass
3. If any tests fail, send a follow-up message to Agent 3 with the failures

### Step 5: Final Validation

After all agents complete:
1. Run `pytest tests/ -v --tb=short` -- confirm all green
2. Run `python sentinel.py --help` -- confirm clean output
3. Run a quick import smoke test: `python -c "from sentinel.config import load_config; from sentinel.database import Database; from sentinel.models import Article, ClassificationResult, Event, AlertRecord; print('All Phase 1 imports OK')"`
4. Commit all Phase 1 code with message: "Implement Phase 1: infrastructure (config, database, models, CLI, logging)"

### Step 6: Report

Print a summary:
- Files created
- Tests passed (count)
- Any issues encountered and how they were resolved

## Agent Model Requirements

All agents MUST use Opus 4.6 (`model: "opus"`). Set `mode: "auto"` for each agent so they can write code without permission prompts.

## Error Recovery

If an agent fails or produces broken code:
1. Read the error output carefully
2. Send a follow-up message to the same agent (via `SendMessage`) with the specific error
3. If the agent fails twice on the same issue, fix it yourself
4. Never proceed to the next agent if the current agent's output is broken
