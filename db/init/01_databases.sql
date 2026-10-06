-- Runs once when the Docker Postgres volume is first created.
-- One shared dev database (oddsmith, created by POSTGRES_DB) plus one test database per lane,
-- so lanes running tests in parallel never collide.
CREATE DATABASE oddsmith_test_ingestion;
CREATE DATABASE oddsmith_test_orchestrator;
CREATE DATABASE oddsmith_test_backend;
