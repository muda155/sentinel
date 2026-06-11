-- seed_demo_hotspots.sql — demo data that produces visible, high-confidence hotspots.
--
-- Seeds 3 tightly-clustered event groups (Kyiv, Taiwan Strait, Red Sea) with
-- diverse source domains and country codes so the consensus scorer
-- (0.6·source_density + 0.4·geopolitical_diversity) yields green (>70) hotspots.
--
-- Usage:
--   PGPASSWORD=sentinel_pass psql -h localhost -p 5433 -U sentinel_user -d sentinel \
--     -f scripts/seed_demo_hotspots.sql
--
-- Then run the pipeline (grid-cell → DBSCAN → scoring) to materialize hotspots:
--   docker compose exec -T api python3 -c "from pipeline.clustering import GridCellRepository, bin_to_grid, load_events_for_convergence, ClusterRepository, load_recent_events, run_clustering_pipeline; from pipeline.scoring import ScoringRepository; from pipeline.db import get_pooled_connection; c,p=get_pooled_connection();
--   df=load_events_for_convergence(c,lookback_hours=24); GridCellRepository(c).upsert_cells(bin_to_grid(df)) if not df.empty else None;
--   e=load_recent_events(c,lookback_hours=24); run_clustering_pipeline(e, repository=ClusterRepository(c));
--   ScoringRepository(c).score_all_hotspots(); p.return_connection(c)"

-- 12 diverse source domains across different countries (trust_tier drives trust_score).
INSERT INTO sources (domain, country_code, country_name, trust_tier) VALUES
  ('reuters.com', 'GBR', 'United Kingdom', 'A'),
  ('bbc.co.uk', 'GBR', 'United Kingdom', 'A'),
  ('aljazeera.net', 'QAT', 'Qatar', 'B'),
  ('france24.com', 'FRA', 'France', 'B'),
  ('dw.com', 'DEU', 'Germany', 'A'),
  ('nytimes.com', 'USA', 'United States', 'A'),
  ('reuters.in', 'IND', 'India', 'B'),
  ('tass.ru', 'RUS', 'Russia', 'C'),
  ('xinhuanet.com', 'CHN', 'China', 'C'),
  ('jpost.com', 'ISR', 'Israel', 'B'),
  ('kyivindependent.com', 'UKR', 'Ukraine', 'B'),
  ('al-monitor.com', 'TUR', 'Turkey', 'C')
ON CONFLICT (domain) DO NOTHING;

UPDATE sources SET trust_score = 0.95, trust_tier = 'A' WHERE domain IN ('reuters.com','bbc.co.uk','dw.com','nytimes.com');
UPDATE sources SET trust_score = 0.75, trust_tier = 'B' WHERE domain IN ('aljazeera.net','france24.com','reuters.in','jpost.com','kyivindependent.com');
UPDATE sources SET trust_score = 0.45, trust_tier = 'C' WHERE domain IN ('tass.ru','xinhuanet.com','al-monitor.com');

-- Cluster 1: Kyiv (~50.44, 30.52) — diverse country_code per source for high diversity.
INSERT INTO events (source_system, external_event_id, event_date, cameo_code, country_code, url, title, point_geom, source_id, grid_cell_id) VALUES
  ('GDELT','seed-kyiv-001','2026-06-10 08:00:00+00','14','GBR','https://reuters.com/article/kyiv1','Drone strike on Kyiv outskirts',ST_SetSRID(ST_MakePoint(30.50,50.44),4326),(SELECT source_id FROM sources WHERE domain='reuters.com'),'1x1_LAT50_LON30'),
  ('GDELT','seed-kyiv-002','2026-06-10 09:30:00+00','18','UKR','https://bbc.co.uk/article/kyiv2','Heavy artillery near Kyiv',ST_SetSRID(ST_MakePoint(30.53,50.45),4326),(SELECT source_id FROM sources WHERE domain='bbc.co.uk'),'1x1_LAT50_LON30'),
  ('GDELT','seed-kyiv-003','2026-06-10 10:00:00+00','19','FRA','https://france24.com/article/kyiv3','Large-scale military assault in Kyiv',ST_SetSRID(ST_MakePoint(30.51,50.43),4326),(SELECT source_id FROM sources WHERE domain='france24.com'),'1x1_LAT50_LON30'),
  ('GDELT','seed-kyiv-004','2026-06-10 11:00:00+00','17','DEU','https://dw.com/article/kyiv4','Coercive diplomatic action',ST_SetSRID(ST_MakePoint(30.54,50.46),4326),(SELECT source_id FROM sources WHERE domain='dw.com'),'1x1_LAT50_LON30'),
  ('GDELT','seed-kyiv-005','2026-06-10 12:00:00+00','15','USA','https://nytimes.com/article/kyiv5','Violent political clashes',ST_SetSRID(ST_MakePoint(30.52,50.44),4326),(SELECT source_id FROM sources WHERE domain='nytimes.com'),'1x1_LAT50_LON30'),
  ('GDELT','seed-kyiv-006','2026-06-10 13:00:00+00','14','UKR','https://kyivindependent.com/article/kyiv6','Missile attack aftermath',ST_SetSRID(ST_MakePoint(30.49,50.42),4326),(SELECT source_id FROM sources WHERE domain='kyivindependent.com'),'1x1_LAT50_LON30'),
  ('GDELT','seed-kyiv-007','2026-06-10 14:00:00+00','18','GBR','https://reuters.com/article/kyiv7','Infantry engagement near Bucha',ST_SetSRID(ST_MakePoint(30.48,50.47),4326),(SELECT source_id FROM sources WHERE domain='reuters.com'),'1x1_LAT50_LON30'),
  ('GDELT','seed-kyiv-008','2026-06-10 15:00:00+00','19','QAT','https://aljazeera.net/article/kyiv8','Russian forces mass near Kyiv border',ST_SetSRID(ST_MakePoint(30.55,50.45),4326),(SELECT source_id FROM sources WHERE domain='aljazeera.net'),'1x1_LAT50_LON30'),
  ('GDELT','seed-kyiv-009','2026-06-10 16:00:00+00','14','UKR','https://bbc.co.uk/article/kyiv9','Civilian casualties from drone strike',ST_SetSRID(ST_MakePoint(30.51,50.44),4326),(SELECT source_id FROM sources WHERE domain='bbc.co.uk'),'1x1_LAT50_LON30'),
  ('GDELT','seed-kyiv-010','2026-06-10 17:00:00+00','16','IND','https://reuters.in/article/kyiv10','Diplomatic relations reduced',ST_SetSRID(ST_MakePoint(30.50,50.43),4326),(SELECT source_id FROM sources WHERE domain='reuters.in'),'1x1_LAT50_LON30'),
  ('GDELT','seed-kyiv-011','2026-06-10 18:00:00+00','18','ISR','https://jpost.com/article/kyiv11','IDF advisory on Ukraine conflict',ST_SetSRID(ST_MakePoint(30.52,50.46),4326),(SELECT source_id FROM sources WHERE domain='jpost.com'),'1x1_LAT50_LON30'),
  ('GDELT','seed-kyiv-012','2026-06-10 19:00:00+00','17','DEU','https://dw.com/article/kyiv12','NATO coercion response',ST_SetSRID(ST_MakePoint(30.53,50.44),4326),(SELECT source_id FROM sources WHERE domain='dw.com'),'1x1_LAT50_LON30'),
  ('GDELT','seed-kyiv-013','2026-06-11 06:00:00+00','15','FRA','https://france24.com/article/kyiv13','Political assassinations reported',ST_SetSRID(ST_MakePoint(30.50,50.45),4326),(SELECT source_id FROM sources WHERE domain='france24.com'),'1x1_LAT50_LON30'),
  ('GDELT','seed-kyiv-014','2026-06-11 07:00:00+00','14','UKR','https://kyivindependent.com/article/kyiv14','Unconventional attack on Kyiv infrastructure',ST_SetSRID(ST_MakePoint(30.49,50.44),4326),(SELECT source_id FROM sources WHERE domain='kyivindependent.com'),'1x1_LAT50_LON30'),
  ('GDELT','seed-kyiv-015','2026-06-11 08:00:00+00','18','USA','https://nytimes.com/article/kyiv15','Assault brigade deployed to Kyiv front',ST_SetSRID(ST_MakePoint(30.51,50.43),4326),(SELECT source_id FROM sources WHERE domain='nytimes.com'),'1x1_LAT50_LON30')
ON CONFLICT (source_system, external_event_id, event_date) DO NOTHING;

-- Cluster 2: Taiwan Strait (~23.5, 119.0).
INSERT INTO events (source_system, external_event_id, event_date, cameo_code, country_code, url, title, point_geom, source_id, grid_cell_id) VALUES
  ('GDELT','seed-taiwan-001','2026-06-10 08:00:00+00','19','GBR','https://reuters.com/article/taiwan1','PLA Navy drills in Taiwan Strait',ST_SetSRID(ST_MakePoint(119.5,23.5),4326),(SELECT source_id FROM sources WHERE domain='reuters.com'),'1x1_LAT23_LON119'),
  ('GDELT','seed-taiwan-002','2026-06-10 09:00:00+00','17','GBR','https://bbc.co.uk/article/taiwan2','Coercive overflights near Taipei',ST_SetSRID(ST_MakePoint(119.3,23.6),4326),(SELECT source_id FROM sources WHERE domain='bbc.co.uk'),'1x1_LAT23_LON119'),
  ('GDELT','seed-taiwan-003','2026-06-10 10:00:00+00','18','DEU','https://dw.com/article/taiwan3','Fighter jets scramble in strait',ST_SetSRID(ST_MakePoint(119.7,23.4),4326),(SELECT source_id FROM sources WHERE domain='dw.com'),'1x1_LAT23_LON119'),
  ('GDELT','seed-taiwan-004','2026-06-10 11:00:00+00','14','FRA','https://france24.com/article/taiwan4','Unconventional cyber attack on Taiwan grid',ST_SetSRID(ST_MakePoint(119.4,23.5),4326),(SELECT source_id FROM sources WHERE domain='france24.com'),'1x1_LAT23_LON119'),
  ('GDELT','seed-taiwan-005','2026-06-10 12:00:00+00','19','USA','https://nytimes.com/article/taiwan5','Carrier group enters Taiwan Strait',ST_SetSRID(ST_MakePoint(119.6,23.3),4326),(SELECT source_id FROM sources WHERE domain='nytimes.com'),'1x1_LAT23_LON119'),
  ('GDELT','seed-taiwan-006','2026-06-10 13:00:00+00','15','QAT','https://aljazeera.net/article/taiwan6','Anti-CCP protests turn violent',ST_SetSRID(ST_MakePoint(119.2,23.6),4326),(SELECT source_id FROM sources WHERE domain='aljazeera.net'),'1x1_LAT23_LON119'),
  ('GDELT','seed-taiwan-007','2026-06-10 14:00:00+00','18','IND','https://reuters.in/article/taiwan7','Naval confrontation near Penghu',ST_SetSRID(ST_MakePoint(119.5,23.5),4326),(SELECT source_id FROM sources WHERE domain='reuters.in'),'1x1_LAT23_LON119'),
  ('GDELT','seed-taiwan-008','2026-06-10 15:00:00+00','17','ISR','https://jpost.com/article/taiwan8','Economic coercion against Taiwan',ST_SetSRID(ST_MakePoint(119.4,23.4),4326),(SELECT source_id FROM sources WHERE domain='jpost.com'),'1x1_LAT23_LON119'),
  ('GDELT','seed-taiwan-009','2026-06-10 16:00:00+00','14','GBR','https://reuters.com/article/taiwan9','Missile tests near Taiwan waters',ST_SetSRID(ST_MakePoint(119.6,23.5),4326),(SELECT source_id FROM sources WHERE domain='reuters.com'),'1x1_LAT23_LON119'),
  ('GDELT','seed-taiwan-010','2026-06-10 17:00:00+00','19','GBR','https://bbc.co.uk/article/taiwan10','Amphibious assault drills',ST_SetSRID(ST_MakePoint(119.3,23.5),4326),(SELECT source_id FROM sources WHERE domain='bbc.co.uk'),'1x1_LAT23_LON119'),
  ('GDELT','seed-taiwan-011','2026-06-10 18:00:00+00','18','TUR','https://al-monitor.com/article/taiwan11','China-Taiwan border escalation',ST_SetSRID(ST_MakePoint(119.5,23.6),4326),(SELECT source_id FROM sources WHERE domain='al-monitor.com'),'1x1_LAT23_LON119'),
  ('GDELT','seed-taiwan-012','2026-06-10 19:00:00+00','14','RUS','https://tass.ru/article/taiwan12','Russian report on Taiwan tensions',ST_SetSRID(ST_MakePoint(119.4,23.4),4326),(SELECT source_id FROM sources WHERE domain='tass.ru'),'1x1_LAT23_LON119'),
  ('GDELT','seed-taiwan-013','2026-06-11 06:00:00+00','16','CHN','https://xinhuanet.com/article/taiwan13','China reduces diplomatic relations',ST_SetSRID(ST_MakePoint(119.5,23.5),4326),(SELECT source_id FROM sources WHERE domain='xinhuanet.com'),'1x1_LAT23_LON119'),
  ('GDELT','seed-taiwan-014','2026-06-11 07:00:00+00','15','UKR','https://kyivindependent.com/article/taiwan14','Ukraine warns of Taiwan scenario',ST_SetSRID(ST_MakePoint(119.3,23.3),4326),(SELECT source_id FROM sources WHERE domain='kyivindependent.com'),'1x1_LAT23_LON119'),
  ('GDELT','seed-taiwan-015','2026-06-11 08:00:00+00','19','DEU','https://dw.com/article/taiwan15','PLA largest-ever exercise in strait',ST_SetSRID(ST_MakePoint(119.5,23.5),4326),(SELECT source_id FROM sources WHERE domain='dw.com'),'1x1_LAT23_LON119')
ON CONFLICT (source_system, external_event_id, event_date) DO NOTHING;

-- Cluster 3: Red Sea / Yemen (~15.0, 42.0).
INSERT INTO events (source_system, external_event_id, event_date, cameo_code, country_code, url, title, point_geom, source_id, grid_cell_id) VALUES
  ('GDELT','seed-redsea-001','2026-06-10 08:00:00+00','18','GBR','https://reuters.com/article/redsea1','Houthi drone attack on Red Sea vessel',ST_SetSRID(ST_MakePoint(42.0,15.0),4326),(SELECT source_id FROM sources WHERE domain='reuters.com'),'1x1_LAT15_LON42'),
  ('GDELT','seed-redsea-002','2026-06-10 09:00:00+00','14','GBR','https://bbc.co.uk/article/redsea2','Unconventional naval mine attack',ST_SetSRID(ST_MakePoint(42.1,14.9),4326),(SELECT source_id FROM sources WHERE domain='bbc.co.uk'),'1x1_LAT15_LON42'),
  ('GDELT','seed-redsea-003','2026-06-10 10:00:00+00','19','QAT','https://aljazeera.net/article/redsea3','US Navy engages Houthi missiles',ST_SetSRID(ST_MakePoint(41.9,15.1),4326),(SELECT source_id FROM sources WHERE domain='aljazeera.net'),'1x1_LAT15_LON42'),
  ('GDELT','seed-redsea-004','2026-06-10 11:00:00+00','18','DEU','https://dw.com/article/redsea4','Houthi ballistic missile toward Israel',ST_SetSRID(ST_MakePoint(42.0,15.0),4326),(SELECT source_id FROM sources WHERE domain='dw.com'),'1x1_LAT15_LON42'),
  ('GDELT','seed-redsea-005','2026-06-10 12:00:00+00','17','USA','https://nytimes.com/article/redsea5','US imposes coercive sanctions on Houthis',ST_SetSRID(ST_MakePoint(42.1,14.9),4326),(SELECT source_id FROM sources WHERE domain='nytimes.com'),'1x1_LAT15_LON42'),
  ('GDELT','seed-redsea-006','2026-06-10 13:00:00+00','17','FRA','https://france24.com/article/redsea6','French naval coercion in Red Sea',ST_SetSRID(ST_MakePoint(42.0,15.0),4326),(SELECT source_id FROM sources WHERE domain='france24.com'),'1x1_LAT15_LON42'),
  ('GDELT','seed-redsea-007','2026-06-10 14:00:00+00','19','IND','https://reuters.in/article/redsea7','Indian Navy joins Red Sea patrol',ST_SetSRID(ST_MakePoint(41.9,15.0),4326),(SELECT source_id FROM sources WHERE domain='reuters.in'),'1x1_LAT15_LON42'),
  ('GDELT','seed-redsea-008','2026-06-10 15:00:00+00','15','ISR','https://jpost.com/article/redsea8','Houthi political violence escalates',ST_SetSRID(ST_MakePoint(42.0,15.0),4326),(SELECT source_id FROM sources WHERE domain='jpost.com'),'1x1_LAT15_LON42'),
  ('GDELT','seed-redsea-009','2026-06-10 16:00:00+00','14','TUR','https://al-monitor.com/article/redsea9','Turkey monitors Red Sea crisis',ST_SetSRID(ST_MakePoint(42.0,14.9),4326),(SELECT source_id FROM sources WHERE domain='al-monitor.com'),'1x1_LAT15_LON42'),
  ('GDELT','seed-redsea-010','2026-06-10 17:00:00+00','18','RUS','https://tass.ru/article/redsea10','Russia condemns Red Sea attacks',ST_SetSRID(ST_MakePoint(42.1,15.0),4326),(SELECT source_id FROM sources WHERE domain='tass.ru'),'1x1_LAT15_LON42'),
  ('GDELT','seed-redsea-011','2026-06-11 06:00:00+00','18','CHN','https://xinhuanet.com/article/redsea11','China calls for Red Sea restraint',ST_SetSRID(ST_MakePoint(42.0,15.0),4326),(SELECT source_id FROM sources WHERE domain='xinhuanet.com'),'1x1_LAT15_LON42'),
  ('GDELT','seed-redsea-012','2026-06-11 07:00:00+00','19','GBR','https://reuters.com/article/redsea12','USS Eisenhower strike group deployed',ST_SetSRID(ST_MakePoint(42.0,15.0),4326),(SELECT source_id FROM sources WHERE domain='reuters.com'),'1x1_LAT15_LON42')
ON CONFLICT (source_system, external_event_id, event_date) DO NOTHING;
