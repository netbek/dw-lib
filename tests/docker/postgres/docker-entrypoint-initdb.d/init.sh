#!/bin/bash
set -e

psql -U $POSTGRES_USER -d $POSTGRES_DB <<-EOSQL
    create user iceberg with login password 'iceberg';
    create database iceberg owner iceberg;
EOSQL
