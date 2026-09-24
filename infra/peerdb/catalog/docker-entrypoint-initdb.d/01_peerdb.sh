#!/bin/sh
set -e

psql -tAc "SELECT 1 FROM pg_user WHERE usename = 'peerdb'" | grep -q 1 || \
    psql -c "CREATE USER peerdb WITH REPLICATION LOGIN PASSWORD 'peerdb';"

psql -tAc "SELECT 1 FROM pg_database WHERE datname='peerdb'" | grep -q 1 || \
    createdb --echo --owner=peerdb peerdb

psql <<EOF
    GRANT USAGE ON SCHEMA public TO peerdb;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO peerdb;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO peerdb;
EOF

echo "host replication peerdb 0.0.0.0/0 trust" >> "$PGDATA/pg_hba.conf"
