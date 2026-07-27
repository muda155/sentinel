-- event_hotspot.is_noise was referenced by clustering.py, llm_verifier.py and
-- api/queries.py (FR-5 noise flagging, specs v1.1.1) but never created by any
-- migration — it existed on dev DBs only via an ad-hoc ALTER. Fresh databases
-- (CI, new deployments) lacked it, breaking every is_noise query.
ALTER TABLE event_hotspot ADD COLUMN IF NOT EXISTS is_noise BOOLEAN DEFAULT false;
