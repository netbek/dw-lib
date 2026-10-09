# PeerDB Table Mapping Fields Design

**Last updated:** 2026-10-09
**Status:** Draft

## Context

`ConfigMirrorTableMapping` (src/dw_lib/peerdb.py:766) models three of the twelve fields of the PeerDB `TableMapping` proto message (vendor/peerdb/protos/flow.proto:43): `source_table_identifier`, `destination_table_identifier`, and `exclude`. The remaining fields are missing from the local YAML config, so users cannot configure ClickHouse destination table shape or initial-snapshot partitioning.

The vendored PeerDB source is v0.37.10 (vendor/peerdb tag `v0.37.10`), matching the version pinned across the repository. Field usage in that version:

| Proto field | Postgres destination | ClickHouse destination | Evidence (vendor/peerdb) |
|---|---|---|---|
| `partition_key` | initial snapshot partitioning | initial snapshot partitioning | flow/workflows/snapshot_flow.go:188-228,278 |
| `columns` | column rename | rename, type override, sorting, partitioning, nullability | flow/connectors/postgres/validate.go:347-354; flow/connectors/clickhouse/normalize.go:195-204,326,374 |
| `engine` | ignored | engine selection | flow/connectors/clickhouse/validate.go:131 |
| `sharding_key` | ignored | Distributed table sharding | flow/connectors/clickhouse/normalize.go:294 |
| `policy_name` | ignored | Distributed table policy | flow/connectors/clickhouse/normalize.go:297 |
| `partition_by_expr` | ignored | raw PARTITION BY, overrides `columns[].partitioning` | flow/connectors/clickhouse/normalize.go:261-272 |
| `bigquery_cdc_events_function` | — | — | BigQuery only |
| `query_cdc_watermark_column` | — | — | BigQuery only |
| `structured_ingestion_config` | — | — | BigQuery only |

The PeerDB UI confirms this mapping: Target Table, Engine, Custom Partitioning Key, Sharding Key, Partition By Expr, and Policy Name are per-mapping fields, while custom sorting key and partitioning columns are stored as `ordering` and `partitioning` on `ColumnSetting` entries (vendor/peerdb/ui/app/mirrors/create/handlers.ts:183-200, cdc/schemabox.tsx:468-575, cdc/sortingkey.tsx:228-315). The UI engine dropdown exposes only four of the six enum values (cdc/schemabox.tsx:358-362); the two replicated engines exist only in the backend.

Constraints:

- This library supports only one PeerDB version at a time and does not aim for backward compatibility across versions (AGENTS.md).
- `create_mirror` requires a Postgres source (src/dw_lib/peerdb.py:1757); destinations can be Postgres or ClickHouse.
- Config models are pydantic `BaseModel`s and the file's convention for enum-like fields is inline `Literal` (see `DynamicSetting`, `MirrorStatusResponse`).
- The mirror payload is `mirror.model_dump()` placed under `connection_configs` (src/dw_lib/peerdb.py:1790-1792). PeerDB serves the REST API through grpc-gateway, whose protojson decoder accepts snake_case proto field names, enum value names as strings, and treats `null` as unset (vendor/peerdb/flow/cmd/api.go:143-153).

## Goals

1. Expose every PeerDB table-mapping option usable by Postgres and ClickHouse destinations.
2. Expose all six ClickHouse engine values, including the two replicated engines the PeerDB UI omits.
3. Keep existing configurations and mirror payloads unchanged when the new options are absent.

## Non-goals

- BigQuery destinations and BigQuery-only mapping options: `bigquery_cdc_events_function`, `query_cdc_watermark_column`, `structured_ingestion_config`.
- Modelling the ClickHouse peer `cluster` and `replicated` settings (vendor/peerdb/protos/peers.proto:210-211). `sharding_key` and `policy_name` are forwarded, but only act on peers whose cluster is configured outside this library.
- Client-side validation of ClickHouse expressions (`partition_by_expr`, `sharding_key`) or of `ordering`/`partitioning` ranges; the backend validates these.
- Non-CDC flows (QRep) and non-Postgres sources.

## Terminology

| Term | Meaning |
|------|---------|
| Table mapping | One source-to-destination table entry in a mirror; mirrors the PeerDB `TableMapping` proto message. |
| Column setting | Per-column override inside a table mapping; mirrors the PeerDB `ColumnSetting` proto message. |
| Engine | ClickHouse table engine for the destination table; one of the six `TableEngine` enum values. |
| Sorting key | ClickHouse `ORDER BY` column order, expressed as `ordering` on column settings. |
| Partitioning columns | ClickHouse `PARTITION BY` columns, expressed as `partitioning` on column settings. |
| Custom partitioning key | Initial-snapshot partition/watermark column, expressed as `partition_key` on the table mapping. |
| Single-node destination | ClickHouse peer without `cluster`; PeerDB creates one local table per mapping. |
| Distributed destination | ClickHouse peer with `cluster` set; PeerDB creates a `<table>_shard` local table plus a `Distributed` table bearing the destination name (flow/connectors/clickhouse/normalize.go:160-184,288-303). |
| Replicated destination | Orthogonal peer flag `replicated` (not implied by `cluster`) that switches local engine DDL to `Replicated*` variants (flow/connectors/clickhouse/normalize.go:117-146). |

## Architecture

No new runtime component. Data flows through the existing config pipeline:

```
peerdb.yaml
    │  PeerDB.config: render Jinja, merge "+defaults"
    ▼
ConfigMirror / ConfigMirrorTableMapping  (pydantic)
    │  mirror.model_dump()
    ▼
PeerDB.create_mirror()
    │  POST /v1/flows/cdc/create  {"connection_configs": {...}}
    ▼
PeerDB API (grpc-gateway, protojson)
    │  FlowConnectionConfigsToCore: copies fields by number
    ▼
Postgres / ClickHouse destination connector
```

1. `PeerDB.config` renders the YAML as a Jinja template, merges `+defaults` blocks into sibling entries, and builds `ConfigMirror` objects containing `ConfigMirrorTableMapping` entries (src/dw_lib/peerdb.py:885-1009).
2. Callers serialize the mirror with `mirror.model_dump()` and pass it to `create_mirror` (examples/cli/packages/example_cli/src/example_cli/peerdb_cli/mirror.py:25).
3. `create_mirror` validates source tables, best-effort drops destination tables, then POSTs `{"connection_configs": mirror}` to `v1/flows/cdc/create` (src/dw_lib/peerdb.py:1749-1806).
4. The API decodes the payload with protojson and converts `FlowConnectionConfigs` to `FlowConnectionConfigsCore`; the conversion copies every set field with the same field number, so all `TableMapping` options survive (vendor/peerdb/flow/proto_conversions/flow_config_converter.go:17-45).
5. Destination connectors consume the options as listed in Context: ClickHouse reads them when creating and normalizing tables; Postgres reads `exclude`, `columns[].source_name`/`destination_name`, and `partition_key`; the generic snapshot flow reads `partition_key` for both destinations.

## Code layout

| Module | Responsibility |
|--------|----------------|
| src/dw_lib/peerdb.py | Add `ConfigMirrorColumnSetting`; extend `ConfigMirrorTableMapping`; docstrings with proto links |
| tests/peerdb/test_config.py | New offline tests: parsing, `model_dump()` shape, engine validation |
| tests/peerdb/data/peerdb.clickhouse.yaml | Non-breaking integration coverage through the real API |
| examples/cli/peerdb.yaml | Documented usage example |

## Configuration reference

| YAML key | Type | Default | Topology | Applies to |
|----------|------|---------|----------|------------|
| `partition_key` | string | unset | both | Postgres + ClickHouse (initial snapshot partitioning) |
| `columns` | list of column settings | unset | both | Postgres (rename) + ClickHouse (all) |
| `columns[].source_name` | string, required | — | both | both |
| `columns[].destination_name` | string | unset | both | both (rename) |
| `columns[].destination_type` | string | unset | both | ClickHouse (type override) |
| `columns[].ordering` | integer | unset | both | ClickHouse (ORDER BY, 1-based) |
| `columns[].partitioning` | integer | unset | both | ClickHouse (PARTITION BY, 1-based) |
| `columns[].nullable_enabled` | boolean | unset | both | ClickHouse (per-column nullability) |
| `engine` | enum string | unset, backend default ReplacingMergeTree | both, value-dependent (see D6) | ClickHouse |
| `sharding_key` | string | unset | distributed only | ClickHouse (clustered peers) |
| `policy_name` | string | unset | distributed only, requires `sharding_key` | ClickHouse (clustered peers) |
| `partition_by_expr` | string | unset | both | ClickHouse; overrides `columns[].partitioning` |
| `exclude` | list of strings | unset | both | both (existing) |

`Topology` classifies each option by destination shape: `both` applies to single-node and distributed destinations; `distributed only` options are emitted solely in the `cluster != ""` branch (flow/connectors/clickhouse/normalize.go:288-303) and are ignored otherwise (flow/pkg/clickhouse/validation.go:528-541).

## Design decisions

### D1: Nested pydantic model for column settings

**Decision.** Model column settings as a new `ConfigMirrorColumnSetting` model and add the new options as optional fields on `ConfigMirrorTableMapping`.

**Rationale.** Config parsing already validates through pydantic; a nested model keeps validation, typing, and discoverability consistent with the rest of the config.

**Consequences.** Unknown keys inside column settings are ignored (pydantic's default), so backend additions require explicit model updates. Acceptable for a single-version library.

### D2: Engine as inline `Literal` of backend enum names

**Decision.** Type `engine` as `Literal` over the six `CH_ENGINE_*` names, matching the proto exactly, including the replicated engines.

**Rationale.** The file already uses inline `Literal` for enum-like fields; enum names are readable in YAML and protojson accepts them; a `Literal` rejects typos at parse time.

**Consequences.** The `Literal` must be updated when PeerDB adds an engine; the single-version policy makes this a deliberate, low-cost edit.

### D3: `None` defaults preserve payload and behavior

**Decision.** Every new option defaults to `None`. An unset `engine` maps to the backend default (proto value 0, ReplacingMergeTree).

**Rationale.** Existing configurations and serialized payloads stay unchanged; protojson treats `null` as unset, so `model_dump()` emitting `null` for the new fields is harmless.

**Consequences.** Default engine semantics live in the backend, not the client. A future backend default change would apply automatically.

### D4: Exclude BigQuery-only fields

**Decision.** Do not model `bigquery_cdc_events_function`, `query_cdc_watermark_column`, or `structured_ingestion_config`.

**Rationale.** The library has no BigQuery adapter or peer type, and `create_mirror` requires a Postgres source, so these options are unusable here.

**Consequences.** Full proto parity would need a future change if BigQuery support is added.

### D5: No client-side expression or range validation

**Decision.** Accept any integer for `ordering`/`partitioning` and forward expression strings as given.

**Rationale.** The proto defines no constraints; the backend applies `> 0` semantics and validates expressions against the table columns (vendor/peerdb/flow/pkg/clickhouse/validation.go:543-581).

**Consequences.** Invalid expressions surface as PeerDB API errors at mirror creation, not as config parse errors.

### D6: Forward topology-dependent options without modelling peer topology

**Decision.** Forward `sharding_key`, `policy_name`, and every engine value to the API without client-side checks against the destination peer's `cluster` and `replicated` settings.

**Rationale.** The library does not model those peer fields (Non-goals). PeerDB already ignores `sharding_key`/`policy_name` on single-node peers (flow/connectors/clickhouse/normalize.go:288-303; flow/pkg/clickhouse/validation.go:528-541), and selects `Replicated*` engine DDL solely from the peer's `replicated` flag (flow/connectors/clickhouse/normalize.go:116-146), so forwarding is safe and keeps the config a faithful mirror of the proto.

**Consequences.** On single-node destinations, `sharding_key` and `policy_name` are silently ignored. `policy_name` has no effect even in distributed mode unless `sharding_key` is non-empty, because it is emitted only inside that branch (flow/connectors/clickhouse/normalize.go:294-300). `CH_ENGINE_REPLICATED_*` values materialise as Replicated engines only when the peer's `replicated` flag is set; otherwise they behave like their non-replicated twins. `CH_ENGINE_NULL` suppresses the Distributed wrapper on a distributed destination, so it behaves like a single-node table there (flow/connectors/clickhouse/normalize.go:160,177; flow/connectors/clickhouse/cdc.go:258-260).

## Alternatives considered

| Alternative | Why rejected |
|-------------|--------------|
| Pass new fields through as raw dicts without models | Loses validation and documentation; inconsistent with the existing model-based config |
| `IntEnum`/`StrEnum` for engine | Inconsistent with the file's `Literal` convention; verbose in YAML |
| Model all twelve proto fields for full parity | BigQuery-only fields are unusable by this library |
| Default `engine` explicitly to `CH_ENGINE_REPLACING_MERGE_TREE` | Changes existing serialized payloads for no behavioral gain; backend default already equals it |

## Test strategy

| Layer | Scope | Examples |
|-------|-------|----------|
| Unit (offline) | Config parsing and `model_dump()` | All new options round-trip; every engine value accepted; unknown engine rejected; column setting without `source_name` rejected; minimal mapping unchanged |
| Integration (Docker) | Real API acceptance | `cdc_one` with `partition_key`, explicit default engine, and an identity column rename; existing Postgres and ClickHouse mirror tests still pass |

## Open questions

- Should a follow-up feature model the ClickHouse peer's `cluster` and `replicated` settings so `sharding_key` and `policy_name` can be configured end-to-end from this library? Deferrable; it does not change this spec or its acceptance.

## References

- PeerDB `TableMapping` proto: https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/flow.proto#L43
- PeerDB `ColumnSetting` proto: https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/flow.proto#L25
- PeerDB `TableEngine` enum: https://github.com/PeerDB-io/peerdb/blob/v0.37.10/protos/flow.proto#L425
- Local vendored copy: vendor/peerdb/protos/flow.proto
- PeerDB UI table settings: vendor/peerdb/ui/app/mirrors/create/cdc/schemabox.tsx, cdc/sortingkey.tsx
- AGENTS.md, PeerDB dependency management (single-version support)
