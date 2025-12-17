#!/bin/bash
set -e

psql -tc "SELECT 1 FROM pg_user WHERE usename = 'temporal'" | grep -q 1 || \
    psql -c "CREATE USER temporal WITH PASSWORD 'temporal';"

createdb --echo --owner=temporal temporal
createdb --echo --owner=temporal temporal_visibility
