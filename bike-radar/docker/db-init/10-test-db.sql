-- Separate database for the integration tests, so `make check` never touches real rides.
CREATE DATABASE bikeradar_test OWNER bikeradar;
\connect bikeradar_test
CREATE EXTENSION IF NOT EXISTS postgis;
