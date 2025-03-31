#!/bin/sh
set -e

minio server /data --console-address=":9001" & /wait-for-it.sh minio:9000
mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc mb local/iceberg
wait
