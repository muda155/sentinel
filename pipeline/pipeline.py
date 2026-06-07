"""Pipeline orchestrator — triggered every 15 min by APScheduler (FR-0)."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from pipeline.db import get_pooled_connection
from pipeline.ingestion import GDELT2Ingestor

logger = logging.getLogger("sentinel.pipeline")


def run_pipeline() -> None:
    """Execute all 6 pipeline steps with error isolation."""
    cycle_start = datetime.now(timezone.utc)
    logger.info("Pipeline cycle starting", extra={"cycle": cycle_start.isoformat()})

    # Step 0: Partition maintenance + retention (M1, spec Section 6.2.1)
    try:
        step_start = time.monotonic()
        from pipeline.retention import apply_retention, ensure_partitions

        conn, pool = get_pooled_connection()
        try:
            ensured = ensure_partitions(conn)
            dropped = apply_retention(conn)
        finally:
            pool.return_connection(conn)
        logger.info("Step 0: Partition maintenance complete", extra={
            "step": "partition_maintenance", "duration_s": round(time.monotonic() - step_start, 2),
            "partitions_ensured": len(ensured), "partitions_dropped": dropped,
        })
    except Exception as e:  # never crash the cycle on maintenance
        logger.warning("Step 0 failed: partition maintenance (continuing)", extra={
            "step": "partition_maintenance", "error": str(e), "error_type": type(e).__name__,
        })

    # Step 1: GDELT Ingestion
    try:
        step_start = time.monotonic()
        ingestor = GDELT2Ingestor()
        military_df = ingestor.run_once()
        conn, pool = get_pooled_connection()
        try:
            inserted = ingestor.insert_to_db(military_df, conn)
        finally:
            pool.return_connection(conn)
        logger.info("Step 1: GDELT ingestion complete", extra={
            "step": "gdelt_ingestion", "duration_s": round(time.monotonic() - step_start, 2),
            "events": len(military_df), "inserted": inserted,
        })
    except Exception as e:
        logger.error("Step 1 failed: GDELT ingestion", extra={
            "step": "gdelt_ingestion", "error": str(e), "error_type": type(e).__name__,
        })
        return  # SchemaError or other critical failure -> skip entire cycle

    # Step 2: ACLED Ingestion (FR-1b) — failure must not abort the cycle
    try:
        step_start = time.monotonic()
        if not os.getenv("ACLED_API_KEY"):
            logger.info("Step 2: ACLED ingestion skipped (no ACLED_API_KEY)", extra={
                "step": "acled_ingestion", "duration_s": 0,
            })
        else:
            from pipeline.ingestion import ACLEDIngestor

            acled_days = int(os.getenv("SENTINEL_ACLED_FETCH_DAYS", "7"))
            acled = ACLEDIngestor()
            acled_df = acled.fetch_events(days=acled_days)
            conn, pool = get_pooled_connection()
            try:
                acled_inserted = acled.insert_to_db(acled_df, conn)
            finally:
                pool.return_connection(conn)
            logger.info("Step 2: ACLED ingestion complete", extra={
                "step": "acled_ingestion", "duration_s": round(time.monotonic() - step_start, 2),
                "events": len(acled_df), "inserted": acled_inserted,
            })
    except Exception as e:
        logger.warning("Step 2 failed: ACLED ingestion (continuing with GDELT-only)", extra={
            "step": "acled_ingestion", "error": str(e), "error_type": type(e).__name__,
        })

    # Reverse-geocode source countries (M1, Sprint 6) — feeds FR-8 diversity.
    try:
        step_start = time.monotonic()
        from pipeline.geocode import backfill_source_countries

        conn, pool = get_pooled_connection()
        try:
            geocoded = backfill_source_countries(conn)
        finally:
            pool.return_connection(conn)
        logger.info("Source reverse-geocoding complete", extra={
            "step": "reverse_geocode", "duration_s": round(time.monotonic() - step_start, 2),
            "sources_updated": geocoded,
        })
    except Exception as e:
        logger.warning("Source reverse-geocoding failed (continuing)", extra={
            "step": "reverse_geocode", "error": str(e), "error_type": type(e).__name__,
        })

    # Step 3: Grid-cell convergence
    try:
        step_start = time.monotonic()
        from pipeline.clustering import bin_to_grid, GridCellRepository
        from pipeline.clustering import load_events_for_convergence

        conn, pool = get_pooled_connection()
        try:
            lookback = int(os.getenv("SENTINEL_LOOKBACK_HOURS", "24"))
            events_df = load_events_for_convergence(conn, lookback_hours=lookback)
            if not events_df.empty:
                binned = bin_to_grid(events_df)
                grid_repo = GridCellRepository(conn)
                grid_repo.upsert_cells(binned)
            logger.info("Step 3: Grid-cell convergence complete", extra={
                "step": "grid_convergence", "duration_s": round(time.monotonic() - step_start, 2),
                "cells": len(binned) if not events_df.empty else 0,
            })
        finally:
            pool.return_connection(conn)
    except Exception as e:
        logger.error("Step 3 failed: Grid-cell convergence", extra={
            "step": "grid_convergence", "error": str(e),
        })
        return

    # Step 4: DBSCAN clustering per cell
    try:
        step_start = time.monotonic()
        from pipeline.clustering import run_clustering_pipeline, ClusterRepository
        from pipeline.clustering import load_recent_events

        conn, pool = get_pooled_connection()
        try:
            dbscan_window = int(os.getenv("SENTINEL_DBSCAN_WINDOW_HOURS", "2"))
            events_df = load_recent_events(conn, lookback_hours=dbscan_window)
            repo = ClusterRepository(conn)
            summary = run_clustering_pipeline(events_df, repository=repo)
            logger.info("Step 4: DBSCAN clustering complete", extra={
                "step": "dbscan_clustering", "duration_s": round(time.monotonic() - step_start, 2),
                **summary,
            })
        finally:
            pool.return_connection(conn)
    except Exception as e:
        logger.error("Step 4 failed: DBSCAN clustering", extra={
            "step": "dbscan_clustering", "error": str(e),
        })
        return

    # Step 5: Confidence scoring
    try:
        step_start = time.monotonic()
        from pipeline.scoring import ScoringRepository

        conn, pool = get_pooled_connection()
        try:
            repo = ScoringRepository(conn)
            results = repo.score_all_hotspots()
            logger.info("Step 5: Confidence scoring complete", extra={
                "step": "confidence_scoring", "duration_s": round(time.monotonic() - step_start, 2),
                "scored": len(results),
            })
        finally:
            pool.return_connection(conn)
    except Exception as e:
        logger.error("Step 5 failed: Confidence scoring", extra={
            "step": "confidence_scoring", "error": str(e),
        })
        return

    # Step 6: LLM Verification
    try:
        step_start = time.monotonic()
        from pipeline.llm_verifier import verify_hotspots_with_llm

        endpoint = os.getenv("NVIDIA_NIM_ENDPOINT", "")
        api_key = os.getenv("NVIDIA_NIM_API_KEY", "")
        model = os.getenv("NVIDIA_NIM_MODEL", "meta/llama-3.1-70b-instruct")
        ollama_endpoint = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
        threshold = float(os.getenv("SENTINEL_LLM_THRESHOLD", "40"))

        if not endpoint or not api_key:
            logger.warning("Step 6: LLM verification skipped (no NIM credentials)")
        else:
            conn, pool = get_pooled_connection()
            try:
                result = verify_hotspots_with_llm(
                    conn, endpoint=endpoint, api_key=api_key, model=model,
                    threshold=threshold, ollama_endpoint=ollama_endpoint,
                )
                logger.info("Step 6: LLM verification complete", extra={
                    "step": "llm_verification", "duration_s": round(time.monotonic() - step_start, 2),
                    **result,
                })
            finally:
                pool.return_connection(conn)
    except Exception as e:
        logger.error("Step 6 failed: LLM verification", extra={
            "step": "llm_verification", "error": str(e),
        })

    total_s = (datetime.now(timezone.utc) - cycle_start).total_seconds()
    logger.info("Pipeline cycle complete", extra={"total_duration_s": round(total_s, 2)})


def start_scheduler() -> BackgroundScheduler:
    """Start the APScheduler background scheduler (FR-0)."""
    interval = int(os.getenv("SENTINEL_POLL_INTERVAL_S", "900"))
    scheduler = BackgroundScheduler(
        job_defaults={"misfire_grace_time": 60, "coalesce": True},
    )
    scheduler.add_job(run_pipeline, "interval", seconds=interval, id="sentinel_pipeline")
    scheduler.start()
    logger.info(f"Scheduler started: pipeline every {interval}s")
    return scheduler


def main() -> int:
    """Run a single pipeline cycle immediately, then start the scheduler."""
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format='{"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}',
    )
    # Run once immediately
    run_pipeline()
    # Start scheduler for recurring execution
    scheduler = start_scheduler()
    try:
        import signal
        signal.pause()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
