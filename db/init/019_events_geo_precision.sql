-- GDELT ActionGeo_Type: 1=country centroid, 2=US state, 3=US city,
-- 4=world city, 5=world state. NULL = unknown (legacy rows) and is treated
-- as precise (fail-open). Country-centroid rows (1) are excluded from DBSCAN
-- micro-clustering (FR-5) but still count toward grid-cell convergence
-- (FR-WM-CONVERGENCE bins all events).
ALTER TABLE events ADD COLUMN IF NOT EXISTS geo_precision SMALLINT;
