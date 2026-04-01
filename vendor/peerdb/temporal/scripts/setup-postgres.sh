#!/bin/sh
set -eu

# Source: https://github.com/temporalio/samples-server/blob/21ba633df78cd0f4a02096d620c19eb2d17ef900/compose/scripts/setup-postgres.sh
# Validate required environment variables
: "${POSTGRES_SEEDS:?ERROR: POSTGRES_SEEDS environment variable is required}"
: "${POSTGRES_USER:?ERROR: POSTGRES_USER environment variable is required}"
: "${POSTGRES_PWD:?ERROR: POSTGRES_PWD environment variable is required}"

SKIP_DB_CREATE="${SKIP_DB_CREATE:-false}"

echo "Starting PostgreSQL schema setup..."
echo "Waiting for PostgreSQL port to be available..."
until nc -z -v -w 3 $POSTGRES_SEEDS ${DB_PORT:-5432}; do
    sleep 2
done
echo "PostgreSQL port is available"

# Create and setup temporal database
if [ "$SKIP_DB_CREATE" != "true" ]; then
    temporal-sql-tool --plugin postgres12 --ep ${POSTGRES_SEEDS} -u ${POSTGRES_USER} --password ${POSTGRES_PWD} -p ${DB_PORT:-5432} --db temporal create
fi
temporal-sql-tool --plugin postgres12 --ep ${POSTGRES_SEEDS} -u ${POSTGRES_USER} --password ${POSTGRES_PWD} -p ${DB_PORT:-5432} --db temporal setup-schema -v 0.0
temporal-sql-tool --plugin postgres12 --ep ${POSTGRES_SEEDS} -u ${POSTGRES_USER} --password ${POSTGRES_PWD} -p ${DB_PORT:-5432} --db temporal update-schema -d /etc/temporal/schema/postgresql/v12/temporal/versioned

# Create and setup visibility database
if [ "$SKIP_DB_CREATE" != "true" ]; then
    temporal-sql-tool --plugin postgres12 --ep ${POSTGRES_SEEDS} -u ${POSTGRES_USER} --password ${POSTGRES_PWD} -p ${DB_PORT:-5432} --db temporal_visibility create
fi
temporal-sql-tool --plugin postgres12 --ep ${POSTGRES_SEEDS} -u ${POSTGRES_USER} --password ${POSTGRES_PWD} -p ${DB_PORT:-5432} --db temporal_visibility setup-schema -v 0.0
temporal-sql-tool --plugin postgres12 --ep ${POSTGRES_SEEDS} -u ${POSTGRES_USER} --password ${POSTGRES_PWD} -p ${DB_PORT:-5432} --db temporal_visibility update-schema -d /etc/temporal/schema/postgresql/v12/visibility/versioned

echo "PostgreSQL schema setup complete"
