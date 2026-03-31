#!/bin/sh
set -eu

# Source: https://github.com/temporalio/samples-server/blob/21ba633df78cd0f4a02096d620c19eb2d17ef900/compose/scripts/create-namespace.sh
NAMESPACE=${DEFAULT_NAMESPACE:-default}
TEMPORAL_ADDRESS=${TEMPORAL_ADDRESS:-temporal-server:7233}

echo "Waiting for Temporal server port to be available..."
nc -z -w 10 $(echo $TEMPORAL_ADDRESS | cut -d: -f1) $(echo $TEMPORAL_ADDRESS | cut -d: -f2)
echo 'Temporal server port is available'

echo 'Waiting for Temporal server to be healthy...'
max_attempts=3
attempt=0

until temporal operator cluster health --address $TEMPORAL_ADDRESS; do
    attempt=$((attempt + 1))
    if [ $attempt -ge $max_attempts ]; then
        echo "Server did not become healthy after $max_attempts attempts"
        exit 1
    fi
    echo "Server not ready yet, waiting... (attempt $attempt/$max_attempts)"
    sleep 5
done

echo "Server is healthy, creating namespace '$NAMESPACE'..."
temporal operator namespace describe -n $NAMESPACE --address $TEMPORAL_ADDRESS || temporal operator namespace create -n $NAMESPACE --address $TEMPORAL_ADDRESS
echo "Namespace '$NAMESPACE' created"

# Source: https://github.com/PeerDB-io/peerdb/blob/v0.36.9/scripts/mirror-name-search.sh
echo "Checking visibility for '$NAMESPACE'..."
for i in {1..10}; do
    if temporal operator search-attribute list --namespace "$NAMESPACE" --address "$TEMPORAL_ADDRESS" >/dev/null 2>&1; then
        echo "Namespace visibility is ready."
        break
    fi
    echo "Waiting for namespace visibility..."
    sleep 2
done

if ! temporal operator search-attribute list | grep -w MirrorName >/dev/null 2>&1; then
    echo "Creating MirrorName attribute..."
    temporal operator search-attribute create --name MirrorName --type Text --namespace $NAMESPACE
    echo "MirrorName attribute created"
fi

echo "Temporal setup complete"
