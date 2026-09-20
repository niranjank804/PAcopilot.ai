-- Runs once, when the docker-compose Postgres volume is first created.
-- The application database is POSTGRES_DB (enterprise_ai); this second
-- one is what the backend test suite connects to, so that a local
-- development database and the tests never share a schema or its rows.
CREATE DATABASE enterprise_ai_test;
