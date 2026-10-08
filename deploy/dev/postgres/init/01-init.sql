-- Runs once, on first start of the pg-data volume, as the superuser `ops` in database `ops`.
CREATE EXTENSION IF NOT EXISTS vector;
-- incident-sim keeps its own database (BUILD_SPEC §3); its role and grants arrive with the walking skeleton (T08).
CREATE DATABASE incident;
