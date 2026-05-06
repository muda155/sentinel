# Phase 1 Sprint 3 Scoring + LLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Sprint 3 consensus scoring and NVIDIA NIM verification pipeline with persistence and tests.

**Architecture:** Add a dedicated scoring module that computes source density, geopolitical diversity, and confidence score per hotspot using hotspot-event joins. Add an LLM verifier module for prompt generation, citation validation, NIM API retries on 429, and summary persistence. Wire both with CLI entrypoints for batch execution.

**Tech Stack:** Python, pandas, requests, psycopg2, PostgreSQL/PostGIS, pytest

---

### Task 1: Add Sprint 3 schema

**Files:**
- Create: `db/init/003_create_scoring_llm.sql`
- Modify: `db/init/001_create_events.sql`

- [ ] **Step 1: Write failing DB schema test**
- [ ] **Step 2: Run schema verification query and confirm missing columns/tables**
- [ ] **Step 3: Add `events.country_code`, scoring columns in `hotspots`, and `llm_summaries` table**
- [ ] **Step 4: Recreate DB and verify new schema objects exist**

### Task 2: Implement consensus scoring with TDD

**Files:**
- Create: `pipeline/scoring.py`
- Create: `tests/test_scoring.py`
- Modify: `pipeline/ingestion.py`

- [ ] **Step 1: Write failing tests for `compute_source_density`, `geopolitical_diversity`, and weighted confidence score**
- [ ] **Step 2: Run `pytest -q tests/test_scoring.py` and confirm failures**
- [ ] **Step 3: Implement minimal scoring functions + repository updater**
- [ ] **Step 4: Run `pytest -q tests/test_scoring.py` and confirm pass**
- [ ] **Step 5: Update ingestion record builder to persist `country_code`**

### Task 3: Implement LLM verifier with TDD

**Files:**
- Create: `pipeline/llm_verifier.py`
- Create: `tests/test_llm_verifier.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Write failing tests for prompt format, citation validation, and 429 retry behavior**
- [ ] **Step 2: Run `pytest -q tests/test_llm_verifier.py` and confirm failures**
- [ ] **Step 3: Implement prompt builder, citation validator, NIM API caller, and repository writer**
- [ ] **Step 4: Run `pytest -q tests/test_llm_verifier.py` and confirm pass**

### Task 4: Wire Sprint 3 execution path

**Files:**
- Modify: `pipeline/clustering.py`
- Modify: `README.md`

- [ ] **Step 1: Add CLI command flow to run scoring then LLM verification for `conf_score > 40`**
- [ ] **Step 2: Add test for threshold gate (no call when score <= 40)**
- [ ] **Step 3: Run `pytest -q` and then execute ingestion -> clustering -> scoring/llm flow**
- [ ] **Step 4: Document Sprint 3 run commands in README**
