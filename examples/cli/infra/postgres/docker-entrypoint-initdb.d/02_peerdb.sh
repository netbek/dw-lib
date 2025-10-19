#!/bin/bash
set -e

psql -tc "SELECT 1 FROM pg_user WHERE usename = 'peerdb'" | grep -q 1 || \
    psql -c "CREATE USER peerdb WITH PASSWORD 'peerdb' SUPERUSER;"

createdb --echo --owner=peerdb peerdb

echo "host replication peerdb 0.0.0.0/0 trust" >> "$PGDATA/pg_hba.conf"
