# Phase 2 M1 — Codebase Analysis & Remediation Plan

**Date:** 2026-05-22
**Branch:** `phase2-m1-db-migration`
**Analyzed by:** Claude Code

---

## Architecture Overview

```
pipeline/ (7 files, 1,267 LOC)     tests/ (8 files, 1,100 LOC)
├── ingestion.py       374 lines   ├── test_ingestion.py          137 lines
├── clustering.py      251 lines   ├── test_clustering.py         151 lines
├── pool.py            226 lines   ├── test_scoring.py             77 lines
├── llm_verifier.py    196 lines   ├── test_llm_verifier.py        81 lines
├── scoring.py         126 lines   ├── test_dashboard_data.py      47 lines
├── db.py               59 lines   ├── test_dashboard_ui.py       201 lines
└── dashboard_data.py   33 lines   ├── test_dashboard_refresh.py  138 lines
frontend/ (3 files, 505 LOC)       └── test_e2e_dashboard.py      268 lines
├── app.py             408 lines   db/init/ (5 files, 423 LOC)
├── refresh_utils.py    96 lines   ├── 001_create_events.sql
└── __init__.py          1 line    ├── 002_create_hotspots.sql
                                   ├── 003_create_scoring_llm.sql
                                   ├── 004_add_partitioning.sql   189 lines
                                   └── 005_add_sources_table.sql  174 lines
```

---

## Finding 1: Partitioned Tables Are Dead Code

**Severity:** High
**Category:** Incomplete migration

### Problem

Migration `004_add_partitioning.sql` creates `events_partitioned` and `hotspots_partitioned` with monthly range partitioning, plus the `create_monthly_partitions()` function. Two utility scripts (`scripts/create_partitions.py`, `scripts/cleanup_old_partitions.py`) manage partition lifecycle.

**However, zero Python code uses these tables.** Every pipeline module reads/writes the original `events` and `hotspots`:

| File | Line | Query |
|------|------|-------|
| `pipeline/ingestion.py` | 149 | `INSERT INTO events (...)` |
| `pipeline/clustering.py` | 108 | `INSERT INTO hotspots (...)` |
| `pipeline/clustering.py` | 130 | `INSERT INTO event_hotspot (...)` |
| `pipeline/clustering.py` | 156 | `FROM events` |
| `pipeline/scoring.py` | 64 | `JOIN events e` |
| `pipeline/scoring.py` | 80 | `UPDATE hotspots SET ...` |
| `pipeline/llm_verifier.py` | 92 | `JOIN events e` |
| `pipeline/dashboard_data.py` | 16 | `FROM hotspots h` |

The migration SQL itself includes data-migration comments (lines 172–186) showing how to backfill from the original tables — that backfill was never executed. The original tables continue to accumulate all data.

### Solution

Two paths:

**Path A — Complete the migration now (recommended):**

1. Add a new migration `006_migrate_to_partitioned.sql` that:
   - Inserts all rows from `events` → `events_partitioned`
   - Inserts all rows from `hotspots` → `hotspots_partitioned`
   - Renames old tables: `events` → `events_legacy`, `hotspots` → `hotspots_legacy`
   - Creates views: `events` → `events_partitioned`, `hotspots` → `hotspots_partitioned` (so no Python code changes needed)
2. Or update all Python INSERT/SELECT statements to target the partitioned tables directly.

**Path B — Defer to M2 (microservices):**

- Partitioning becomes a scale concern for production. Leave the migration scripts in place as "ready to activate" and document that M2 will route writes to the partitioned tables when message-bus workers are introduced.

---

## Finding 2: `sources.trust_score` Is Never Consumed

**Severity:** Medium
**Category:** Feature incomplete

### Problem

Migration `005_add_sources_table.sql` creates a `sources` table with a `trust_score` column (default 0.5), plus a `register_source()` SQL function. Ingestion code (`pipeline/ingestion.py:136–184`) calls `_register_sources()` and stores `source_id` on each event — so sources are populated on insert.

**But `pipeline/scoring.py` never queries the `sources` table.** The `_fetch_hotspot_events` method (line 60) only selects:

```sql
SELECT e.url, e.country_code
FROM event_hotspot eh
JOIN events e ON e.event_id = eh.event_id
```

No `JOIN sources` and no reference to `trust_score`. The `compute_source_density` function (line 21) counts unique domains from URLs directly — all domains are weighted equally.

The spec's risk mitigation R1 explicitly requires this: *"Assign provenance weights per domain (e.g., Reuters = 1.0, unknown = 0.5) stored in `sources.trust_score`. Weight confidence contributions by `trust_score`."*

### Solution

Update `pipeline/scoring.py`:

1. Modify `_fetch_hotspot_events` (line 60) to JOIN sources:

   ```sql
   SELECT e.url, e.country_code, COALESCE(s.trust_score, 0.5) AS trust_score
   FROM event_hotspot eh
   JOIN events e ON e.event_id = eh.event_id
   LEFT JOIN sources s ON e.source_id = s.source_id
   ```

2. Update `compute_source_density` to accept and apply trust-score weighting:

   ```python
   def compute_source_density(domains: list[str], trust_scores: list[float] | None = None) -> float:
       if not trust_scores:
           trust_scores = [1.0] * len(domains)
       # Weight each domain by its trust score
       weighted = sum(trust_scores)
       return float(math.tanh(weighted / 10))
   ```

3. Update `score_hotspot_from_events` to pass trust scores through.
4. Add a test case with mixed trust scores (e.g., known domain = 1.0, unknown = 0.5).

---

## Finding 3: `db.py` and `pool.py` Have Zero Test Coverage

**Severity:** Medium
**Category:** Test gap

### Problem

Every pipeline module has dedicated tests except the connection infrastructure:

| Module | Test file | Status |
|--------|-----------|--------|
| `pipeline/clustering.py` | `tests/test_clustering.py` | Covered |
| `pipeline/dashboard_data.py` | `tests/test_dashboard_data.py` | Covered |
| `pipeline/ingestion.py` | `tests/test_ingestion.py` | Covered |
| `pipeline/llm_verifier.py` | `tests/test_llm_verifier.py` | Covered |
| `pipeline/scoring.py` | `tests/test_scoring.py` | Covered |
| `pipeline/db.py` | — | **No coverage** |
| `pipeline/pool.py` | — | **No coverage** |

`SentinelConnectionPool` has a singleton pattern with thread-locking, lazy initialization, a health-check method, and PgBouncer-aware connection options. None of this is tested. A silent pool failure (e.g., connection exhaustion, port misconfiguration) would only surface at runtime.

### Solution

Create `tests/test_pool.py` covering:

```python
def test_pool_singleton_returns_same_instance()
def test_get_connection_returns_usable_connection()
def test_return_connection_returns_to_pool()
def test_health_check_reports_healthy()
def test_health_check_reports_unhealthy_when_disconnected()
def test_pool_skips_statement_timeout_for_pgbouncer_port_6432()
def test_close_all_cleans_up()
def test_thread_safety_multiple_concurrent_connections()
```

--

## Finding 4: Deprecated `get_connection()` Is Dead Code

**Severity:** Low
**Category:** Cleanup
ư
### Problem

`pipeline/db.py:18` defines `get_connection()` with a deprecation warning, but no production code imports it. All 5 pipeline/frontend modules import `get_pooled_connection` instead. The function is pure dead weight.

### Solution

Remove `get_connection()` from `pipeline/db.py`, or keep it as an explicit backward-compat shim for scripts that connect directly (the two scripts in `scripts/` define their own local `get_connection()` and don't use `pipeline.db` at all).

---

## Finding 5: SQL Injection Pattern in Utility Scripts

**Severity:** Low (inputs are system-catalog-derived)
**Category:** Security hardening

### Problem

Two scripts use f-string interpolation for SQL identifiers:

- `scripts/cleanup_old_partitions.py:98` — `f"ALTER TABLE {table} DETACH PARTITION {partition_name}"`
- `scripts/cleanup_old_partitions.py:109` — `f"DROP TABLE IF EXISTS {partition_name}"`
- `scripts/create_partitions.py:64–71` — f-string for `{partition_name}` and `{table_name}`

Inputs come from hardcoded lists (`["events_partitioned", "hotspots_partitioned"]`) or from `pg_class` queries, so practical risk is minimal. But the pattern is unsafe and should be hardened.

### Solution

Use `psycopg2.sql.Identifier`:

```python
from psycopg2.sql import Identifier, SQL

cur.execute(
    SQL("ALTER TABLE {table} DETACH PARTITION {partition}").format(
        table=Identifier(table),
        partition=Identifier(partition_name),
    )
)
```

---

## Finding 6: `.gitignore` Missing Patterns

**Severity:** Low
**Category:** Hygiene

### Problem

`git status` shows untracked files that should be ignored:
- `node_modules/` (entire directory)
- `*.csv` artifacts (`military_events.csv`, `test_fallback.csv`, `test_latest.csv`)
- `*.docx` files (thesis artifacts)
- `.DS_Store` files

### Solution

Add to `.gitignore`:

```gitignore
node_modules/
*.csv
*.docx
.DS_Store
```

---

## Finding 7: No TODO/FIXME Markers

**Severity:** Informational
**Category:** Process

Zero TODO, FIXME, HACK, or XXX comments exist in the codebase. This means deferred work has no in-code visibility — issues like the dead partitioned tables or unused `trust_score` would be invisible to a developer reading only the source.

### Solution

Add a single `# TODO(phase2-m1): ...` comment at each finding's location so future readers know the work is tracked:

- `pipeline/ingestion.py:149` — `# TODO(phase2-m1): route INSERT to events_partitioned`
- `pipeline/scoring.py:60` — `# TODO(phase2-m1): JOIN sources for trust_score weighting`

---

## Summary

| # | Finding | Severity | Effort | Target |
|---|---------|----------|--------|--------|
| 1 | Partitioned tables unused | High | Medium | Either migrate or defer to M2 |
| 2 | `trust_score` not consumed | Medium | Small | Update scoring.py |
| 3 | `db.py`/`pool.py` untested | Medium | Medium | Add test_pool.py |
| 4 | Dead `get_connection()` | Low | Trivial | Remove or keep as shim |
| 5 | SQL injection in scripts | Low | Trivial | Use `sql.Identifier` |
| 6 | `.gitignore` gaps | Low | Trivial | Add patterns |
| 7 | No TODO markers | Info | Trivial | Add comments |

**Total estimated effort:** ~1–3 hours (depending on Path A vs B for finding 1)
File: sentinel_confidence_scoring_validation.js
Line: 1039
Type: potential_issue
Severity: critical

Comment:
Replace hardcoded absolute path with relative path.

The output path is hardcoded to a specific user's directory, making this script non-portable.



🐛 Proposed fix for portability

-const outputPath = "/Users/macduong/Documents/1/VB2/CNTT14/final_project/sentinel/sentinel_confidence_scoring_validation.docx";
+const path = require('path');
+const outputPath = path.join(__dirname, "sentinel_confidence_scoring_validation.docx");


Alternatively, use an environment variable:
-const outputPath = "/Users/macduong/Documents/1/VB2/CNTT14/final_project/sentinel/sentinel_confidence_scoring_validation.docx";
+const outputPath = process.env.OUTPUT_PATH || path.join(__dirname, "sentinel_confidence_scoring_validation.docx");

Prompt for AI Agent:
Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @sentinel_confidence_scoring_validation.js at line 1039, Replace the hardcoded absolute path assigned to the outputPath constant with a portable approach: compute a relative path (e.g., using the current script directory via __dirname and path.join) or read the output location from an environment variable (e.g., process.env.OUTPUT_PATH) with a sensible default; update the declaration for outputPath so the script no longer contains "/Users/…" and instead derives the path from __dirname/path.join or process.env before writing the docx.

============================================================================
File: sentinel_confidence_scoring_validation.js
Line: 846
Type: potential_issue
Severity: minor

Comment:
Replace Chinese text with Vietnamese translation.

Line 846 contains Chinese text in what should be a Vietnamese academic document.



🌐 Proposed fix

The text "几乎没有相关性，需要其他方法验证" should be translated to Vietnamese. A suggested translation:

-    createDataRow(["0.00 - 0.19", "Rất thấp", "几乎没有相关性，需要其他方法验证"], [2500, 2000, 4526], false, "F0F0F0"),
+    createDataRow(["0.00 - 0.19", "Rất thấp", "Hầu như không có tương quan, cần xác minh bằng các phương pháp khác"], [2500, 2000, 4526], false, "F0F0F0"),

Prompt for AI Agent:
Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @sentinel_confidence_scoring_validation.js at line 846, The createDataRow call contains Chinese text ("几乎没有相关性，需要其他方法验证") that must be replaced with Vietnamese; update the third argument of createDataRow (the human-readable description) to the Vietnamese translation, e.g. "Hầu như không có tương quan, cần phương pháp khác để xác minh", so that the call createDataRow(["0.00 - 0.19", "Rất thấp", "Hầu như không có tương quan, cần phương pháp khác để xác minh"], [2500, 2000, 4526], false, "F0F0F0") uses Vietnamese throughout.

============================================================================
File: CLAUDE.md
Line: 86 to 92
Type: potential_issue
Severity: minor

Comment:
Update CAMEO code descriptions to match specs.md.

The CAMEO code descriptions here are inconsistent with the corrected descriptions in specs.md Appendix A. Code 16 is labeled "(non-violent)" but should reflect "coercive diplomatic actions" as part of the military/conflict event range.



♻️ Proposed fix to align with specs.md

 ## CAMEO Military Codes

 Only events with EventRootCode 14-19 are retained:
 - 14: Unconventional mass violence
 - 15: Violent acts for political reasons
-- 16: Reduced relations (non-violent)
-- 17: Coercive actions
+- 16: Reduced relations / coercive diplomatic actions
+- 17: Demonstrate military or political power
 - 18: Assault
 - 19: Fight (large-scale military)

Prompt for AI Agent:
Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @CLAUDE.md around lines 86 - 92, Update the CAMEO EventRootCode descriptions for codes 14–19 to match specs.md Appendix A: ensure 14 = "Unconventional mass violence", 15 = "Violent acts for political reasons", 16 = "Coercive diplomatic actions" (replace the current "(non-violent)" wording), 17 = "Coercive actions", 18 = "Assault", and 19 = "Fight (large-scale military)"; locate the block that lists "Only events with EventRootCode 14-19 are retained" and replace the incorrect code 16 description so all entries match the canonical specs.

============================================================================
File: sentinel_confidence_scoring_validation.js
Line: 346 to 386
Type: potential_issue
Severity: minor

Comment:
Fix Python syntax error in confusion matrix code snippet.

Line 365 in the embedded Python code is missing a comma before the labels parameter, causing a syntax error.
:


🐛 Proposed fix

 const confusionCode = [
   ...
   "    cm = confusion_matrix(",
   "        df['binary_label'],",
   "        df['predicted_label']",
-  "        labels=[0, 1]",
+  "        labels=[0, 1],",
   "    )",
   ...
 ];


Note: Actually, looking more carefully, the comma should come BEFORE labels, not after:

   "    cm = confusion_matrix(",
   "        df['binary_label'],",
-  "        df['predicted_label']",
-  "        labels=[0, 1]",
+  "        df['predicted_label'],",
+  "        labels=[0, 1]",
   "    )",

Prompt for AI Agent:
Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @sentinel_confidence_scoring_validation.js around lines 346 - 386, The embedded Python in compute_confusion_matrix has a missing comma before the labels argument in the confusion_matrix call causing a syntax error; update the confusion_matrix invocation inside compute_confusion_matrix (the call that passes df['binary_label'] and df['predicted_label']) to include the trailing comma after df['predicted_label'] so the labels=[0, 1] parameter is properly separated, then run lint/tests to verify compute_confusion_matrix and print_confusion_matrix still behave as expected.

============================================================================
File: validation_blueprint.js
Line: 877
Type: potential_issue
Severity: critical

Comment:
Replace hardcoded absolute path with relative path.

The output path is hardcoded to a specific user's directory, making this script non-portable.



🐛 Proposed fix for portability

-const outputPath = "/Users/macduong/Documents/1/VB2/CNTT14/final_project/sentinel/sentinel_confidence_scoring_validation_blueprint.docx";
+const path = require('path');
+const outputPath = path.join(__dirname, "sentinel_confidence_scoring_validation_blueprint.docx");


Alternatively, use an environment variable:
-const outputPath = "/Users/macduong/Documents/1/VB2/CNTT14/final_project/sentinel/sentinel_confidence_scoring_validation_blueprint.docx";
+const outputPath = process.env.OUTPUT_PATH || path.join(__dirname, "sentinel_confidence_scoring_validation_blueprint.docx");

Prompt for AI Agent:
Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @validation_blueprint.js at line 877, The constant outputPath is hardcoded to an absolute user-specific path; change the code that sets outputPath to use a relative path or an environment-configured path instead (e.g., derive from process.cwd() or process.env.OUTPUT_PATH) so the script is portable: update the assignment of outputPath to compute the path at runtime (using path.join or similar) or read from an environment variable with a sensible default, and ensure any downstream code using outputPath continues to work with the new value.

============================================================================
File: tests/test_e2e_dashboard.py
Line: 217 to 225
Type: potential_issue
Severity: major

Comment:
Test doesn't verify dashboard error handling.

This test sets up a mock to raise an exception but then manually raises the exception in a pytest.raises block. It doesn't actually invoke any dashboard code, so it doesn't verify that the dashboard handles database errors gracefully as the docstring claims.




🧪 Proposed fix: Actually call dashboard code

To properly test error handling, the test should call render_dashboard() or the relevant dashboard function with the mocked connection that raises an exception:

     @patch("pipeline.db.get_pooled_connection")
     def test_e2e_dashboard_handles_db_error(self, mock_get_pooled_connection):
         """Test dashboard handles database connection errors gracefully."""
+        from frontend.app import render_dashboard
+
         # Mock database error
         mock_get_pooled_connection.side_effect = Exception("Database connection failed")

         # Should raise exception (caught by dashboard UI)
         with pytest.raises(Exception, match="Database connection failed"):
-            raise mock_get_pooled_connection.side_effect
+            # This would require mocking Streamlit components as well
+            # Alternatively, test at a lower level with fetch_dashboard_hotspots
+            conn, pool = mock_get_pooled_connection()


Note: Full integration testing with Streamlit may require additional mocking infrastructure.

Prompt for AI Agent:
Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @tests/test_e2e_dashboard.py around lines 217 - 225, The test test_e2e_dashboard_handles_db_error currently sets mock_get_pooled_connection.side_effect but never invokes dashboard code; replace the manual raise with a call to the dashboard entrypoint (e.g., render_dashboard() or the function that initializes DB for the dashboard) so the mocked exception is raised during real execution, then assert the dashboard reacts appropriately (use pytest.raises(Exception, match="Database connection failed") if the dashboard propagates, or assert that the error handling path/logging/UI fallback is invoked). Make sure to reference mock_get_pooled_connection and the dashboard function name (render_dashboard or the actual initializer) so the mock applies to the real call.

============================================================================
File: specs.md
Line: 224
Type: potential_issue
Severity: major

Comment:
Correct the Llama-3-70B context window specification.

The specification claims a 128K token context window for Llama-3-70B via NVIDIA NIM, but the actual deployed model supports only 8K tokens. Update line 224 to reflect the correct 8K token context window and adjust the batching/pagination strategy accordingly if needed.

Prompt for AI Agent:
Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @specs.md at line 224, Update the sentence that claims a 128K token context window for "Llama-3-70B via NVIDIA NIM" to state the correct 8K token context window and adjust the batching guidance in the same line: replace "128K tokens" with "8K tokens" in the phrase "Prompt fits within the Llama-3-70B via NVIDIA NIM context window (128K tokens); for hotspot batches exceeding this, paginate by cluster and aggregate summaries." and change the pagination instruction to paginate hotspot batches into chunks that fit within an 8K token window (e.g., safe chunk size ~7.5K tokens) by cluster, then aggregate per-cluster summaries.

============================================================================
File: scripts/create_partitions.py
Line: 20 to 27
Type: potential_issue
Severity: critical

Comment:
Fix date format mismatch - SQL function expects 'YYYY-MM', not 'YYYYMM'.

Line 26 generates month strings in YYYYMM format (e.g., '202605'), but the create_monthly_partitions() SQL function expects 'YYYY-MM' format (as documented in 004_add_partitioning.sql Line 89 and demonstrated in usage at Lines 134, 137). The SQL function concatenates target_month || '-01' to form a date, so passing '202605' would create the invalid date string '202605-01'.




🐛 Proposed fix to match the expected SQL format

 def get_months_to_create(months_ahead: int) -> list[str]:
-    """Generate list of YYYYMM strings from current month to N months ahead."""
+    """Generate list of YYYY-MM strings from current month to N months ahead."""
     months = []
     current = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
     for i in range(months_ahead + 1):
         dt = current + relativedelta(months=i)
-        months.append(dt.strftime("%Y%m"))
+        months.append(dt.strftime("%Y-%m"))
     return months

Prompt for AI Agent:
Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @scripts/create_partitions.py around lines 20 - 27, get_months_to_create currently returns month strings in "YYYYMM" which mismatches the SQL create_monthly_partitions expectation of "YYYY-MM"; update get_months_to_create to format months using a dash (e.g., change strftime to produce "%Y-%m") so that values passed to create_monthly_partitions form valid date strings when the SQL concatenates target_month || '-01'.

============================================================================
File: db/init/004_add_partitioning.sql
Line: 19 to 31
Type: potential_issue
Severity: major

Comment:
Add foreign key constraint for source_id to maintain referential integrity.

The events_partitioned table includes a source_id column (Line 28) but lacks a foreign key constraint to the sources table. Migration 005_add_sources_table.sql adds this constraint only to the legacy events table, not to events_partitioned. This allows insertion of events with invalid source_id values, violating referential integrity.




🔗 Proposed fix to add the foreign key constraint

 CREATE TABLE IF NOT EXISTS events_partitioned (
     event_id BIGSERIAL,
     gdelt_global_event_id VARCHAR(50) NOT NULL,
     point_geom GEOMETRY(POINT, 4326),
     event_date TIMESTAMPTZ NOT NULL,
     cameo_code INTEGER,
     country_code VARCHAR(3),
     url TEXT,
     title TEXT,
     source_id BIGINT,
     created_at TIMESTAMPTZ DEFAULT NOW(),
-    PRIMARY KEY (event_id, event_date)
+    PRIMARY KEY (event_id, event_date),
+    FOREIGN KEY (source_id) REFERENCES sources (source_id) ON DELETE SET NULL
 ) PARTITION BY RANGE (event_date);


Note: This requires that migration 005_add_sources_table.sql runs before this migration, or the foreign key should be added after the sources table exists.

Prompt for AI Agent:
Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @db/init/004_add_partitioning.sql around lines 19 - 31, The events_partitioned table is missing a foreign key on source_id to the sources table; add a FOREIGN KEY constraint referencing sources(id) for the source_id column on events_partitioned (or create the FK in a follow-up migration that runs after migration 005_add_sources_table.sql) so inserts into events_partitioned enforce referential integrity for source_id.

============================================================================
File: scripts/cleanup_old_partitions.py
Line: 93 to 113
Type: potential_issue
Severity: major

Comment:
Use parameterized queries or sql.Identifier to prevent SQL injection.

Lines 98 and 109 use f-strings to construct SQL statements with user-controlled identifiers (table, partition_name). While these values come from the system catalog (pg_class.relname) and are likely safe, using f-strings for SQL construction is a security anti-pattern that could lead to SQL injection if the code is refactored or if the source of these identifiers changes.




🔒 Proposed fix using psycopg2.sql.Identifier

+from psycopg2 import sql
+
 def detach_partition(conn, partition_name: str, table: str) -> bool:
     """Detach partition from parent table before dropping."""
     try:
         with conn.cursor() as cur:
-            cur.execute(
-                f"ALTER TABLE {table} DETACH PARTITION {partition_name}"
-            )
+            cur.execute(sql.SQL(
+                "ALTER TABLE {} DETACH PARTITION {}"
+            ).format(
+                sql.Identifier(table),
+                sql.Identifier(partition_name)
+            ))
         return True
     except psycopg2.Error:
         return False


 def drop_partition(conn, partition_name: str) -> bool:
     """Drop the partition table."""
     try:
         with conn.cursor() as cur:
-            cur.execute(f"DROP TABLE IF EXISTS {partition_name}")
+            cur.execute(sql.SQL(
+                "DROP TABLE IF EXISTS {}"
+            ).format(sql.Identifier(partition_name)))
         return True
     except psycopg2.Error as e:
         print(f"    ERROR dropping {partition_name}: {e}", file=sys.stderr)
         return False

Prompt for AI Agent:
Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @scripts/cleanup_old_partitions.py around lines 93 - 113, Replace the f-string SQL construction in detach_partition and drop_partition with safe identifier handling: use psycopg2.sql.Identifier (from psycopg2 import sql) to build the ALTER TABLE ... DETACH PARTITION and DROP TABLE IF EXISTS statements so table and partition_name are inserted as identifiers rather than interpolated strings; update detach_partition to construct the ALTER TABLE statement with sql.SQL(...) + sql.Identifier(table) + sql.Identifier(partition_name) and execute it, and update drop_partition similarly to use sql.Identifier(partition_name) to avoid SQL injection risks.

============================================================================
File: scripts/cleanup_old_partitions.py
Line: 38 to 77
Type: potential_issue
Severity: critical

Comment:
Fix partition name parsing to handle underscore-separated format.

Lines 66-69 attempt to extract a 6-digit YYYYMM string from partition names, but the create_monthly_partitions() SQL function (in 004_add_partitioning.sql Line 106) creates partitions with underscore-separated format: 'events_2026_05' (using REPLACE(target_month, '-', '_')).

The extraction partition_name[idx + 1 : idx + 7] would yield '2026_0' (missing the last digit), and even if corrected to extract 7 characters, the result '2026_05' contains an underscore, causing the year_month.isdigit() check at Line 69 to fail.




🐛 Proposed fix to correctly extract YYYY_MM and normalize to YYYYMM

                 partition_name = row[0]
                 bound = row[1]
-                # Extract YYYYMM from partition name (e.g., events_partitioned_202405)
+                # Extract YYYY_MM from partition name (e.g., events_2026_05)
                 if "_20" in partition_name:
                     idx = partition_name.index("_20")
-                    year_month = partition_name[idx + 1 : idx + 7]
-                    if year_month.isdigit() and len(year_month) == 6:
+                    year_month_with_sep = partition_name[idx + 1 : idx + 8]  # Extract 7 chars: "2026_05"
+                    # Normalize to YYYYMM by removing underscore
+                    year_month = year_month_with_sep.replace('_', '')
+                    if year_month.isdigit() and len(year_month) == 6:
                         partitions.append(
                             {
                                 "table": table,
                                 "partition": partition_name,
                                 "year_month": year_month,
                             }
                         )

Prompt for AI Agent:
Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @scripts/cleanup_old_partitions.py around lines 38 - 77, The current slicing in list_partitions that uses partition_name and idx to get year_month fails for underscore-separated names like 'events_2026_05' created by create_monthly_partitions; update list_partitions to parse partition_name by splitting or regex (e.g., split on '_' and take the year and month tokens or match r'(\d{4})_(\d{2})'), then normalize by concatenating year+month into a 6-digit YYYYMM string, validate with isdigit() and len==6, and store that normalized value in the "year_month" field instead of the current incorrect slice logic.

============================================================================
File: scripts/create_partitions.py
Line: 47 to 77
Type: potential_issue
Severity: critical

Comment:
Update date parsing to handle 'YYYY-MM' format correctly.

Lines 54-55 extract year and month assuming YYYYMM format (6 characters), but after fixing Line 26 to generate 'YYYY-MM' format (as required by the SQL function), this parsing logic will fail. For example, year_month = '2026-05' would produce month = '-05' instead of '05'.




🐛 Proposed fix to parse YYYY-MM format

 def create_partition(conn, table_name: str, year_month: str) -> bool:
     """
     Create a partition for the given table and YYYYMM string.

     Returns True if partition was created, False if it already existed.
     """
     partition_name = f"{table_name}_{year_month}"
-    year = year_month[:4]
-    month = year_month[4:6]
+    # Parse YYYY-MM format
+    year, month = year_month.split('-')

     # PostgreSQL partition bounds
     start_date = f"{year}-{month}-01"


Also update the docstring:

 def create_partition(conn, table_name: str, year_month: str) -> bool:
     """
-    Create a partition for the given table and YYYYMM string.
+    Create a partition for the given table and YYYY-MM string.

     Returns True if partition was created, False if it already existed.
     """

Prompt for AI Agent:
Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @scripts/create_partitions.py around lines 47 - 77, The create_partition function currently slices year_month as if it's "YYYYMM" which breaks when year_month is "YYYY-MM"; update parsing in create_partition to split on '-' (e.g., year, month = year_month.split('-')) or otherwise strip the hyphen before slicing so month becomes "05" for "2026-05", then recompute start_date and end_dt using the corrected year and month values; also update the docstring to state the function expects a "YYYY-MM" string and that it returns True if created and False if it already existed.

============================================================================
File: db/init/005_add_sources_table.sql
Line: 26 to 27
Type: potential_issue
Severity: minor

Comment:
Remove redundant unique index - the UNIQUE constraint already creates one.

Line 27 explicitly creates a unique index on domain, but the UNIQUE constraint declared at Line 17 already creates a unique index automatically. This results in a duplicate index, wasting storage and slowing down writes.




🗑️ Proposed fix to remove the redundant index

 );

--- Index on domain for fast lookups (unique constraint already creates an index)
-CREATE UNIQUE INDEX idx_sources_domain ON sources (domain);
-
 -- Index on country_code for geographic queries and reporting
 CREATE INDEX idx_sources_country_code ON sources (country_code);

Prompt for AI Agent:
Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @db/init/005_add_sources_table.sql around lines 26 - 27, The migration creates a redundant unique index "idx_sources_domain" on the "sources" table even though a UNIQUE constraint on the domain column already creates an index; remove the explicit "CREATE UNIQUE INDEX idx_sources_domain ON sources (domain);" statement from the migration (or, if this migration may already have been applied in some environments, add a counterpart DROP INDEX IF EXISTS idx_sources_domain before or in a new migration) so that only the UNIQUE constraint provides the index.

Review completed: 13 findings ✔
