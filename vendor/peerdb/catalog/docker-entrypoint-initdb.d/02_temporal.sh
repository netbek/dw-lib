#!/bin/sh
set -e

psql -tAc "SELECT 1 FROM pg_user WHERE usename = 'temporal'" | grep -q 1 || \
    psql -c "CREATE USER temporal WITH LOGIN PASSWORD 'temporal';"

psql -tAc "SELECT 1 FROM pg_database WHERE datname='temporal'" | grep -q 1 || \
    createdb --echo --owner=temporal temporal

psql -tAc "SELECT 1 FROM pg_database WHERE datname='temporal_visibility'" | grep -q 1 || \
    createdb --echo --owner=temporal temporal_visibility
