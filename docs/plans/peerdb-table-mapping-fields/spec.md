# PeerDB Table Mapping Fields Specification

**Status:** Draft v0.1 — pending approval
**Approver:** —
**Date:** 2026-10-09

## Purpose

The mirror configuration currently exposes only the source table, destination table, and excluded columns of a PeerDB table mapping. PeerDB supports additional per-table options that control the shape of ClickHouse destination tables (engine, sorting key, partitioning, sharding, policy) and initial-snapshot partitioning. This feature lets users configure every table-mapping option the Postgres and ClickHouse destinations support, including all engine types the backend defines. Users can then create mirrors with the same per-table options as the PeerDB backend without hand-editing API payloads.

## Requirements

### Requirement: Complete table-mapping options

The config SHALL accept every table-mapping option PeerDB supports for Postgres and ClickHouse destinations: custom partitioning key, column settings, engine, sharding key, policy name, and partition-by expression, alongside the existing source table, destination table, and exclude options.

#### Scenario: Complete mapping accepted

- **WHEN** a table mapping sets a custom partitioning key, a column setting, an engine, a sharding key, a policy name, and a partition-by expression
- **THEN** parsing succeeds
- **AND** each value is available on the parsed mapping

#### Scenario: Minimal mapping accepted

- **WHEN** a table mapping sets only the source and destination table identifiers
- **THEN** parsing succeeds
- **AND** every new option is unset

### Requirement: Column settings

The config SHALL accept per-column settings with a source column name and optional destination column name, destination type, sorting order, partitioning order, and nullability.

#### Scenario: Column settings parsed

- **WHEN** a table mapping declares a column setting with all six values
- **THEN** parsing succeeds
- **AND** each value is available on the parsed column setting

#### Scenario: Column setting without source column

- **WHEN** a column setting omits the source column name
- **THEN** parsing fails with a validation error

### Requirement: All backend engine types

The config SHALL accept all six ClickHouse engine types the PeerDB backend defines, including the replicated engines that the PeerDB UI does not offer.

#### Scenario: Every engine value accepted

- **WHEN** the engine is set to `CH_ENGINE_REPLACING_MERGE_TREE`, `CH_ENGINE_MERGE_TREE`, `CH_ENGINE_NULL`, `CH_ENGINE_REPLICATED_REPLACING_MERGE_TREE`, `CH_ENGINE_REPLICATED_MERGE_TREE`, or `CH_ENGINE_COALESCING_MERGE_TREE`
- **THEN** parsing succeeds for each value

### Requirement: Unknown engine rejected

The config SHALL reject an engine value the PeerDB backend does not define.

#### Scenario: Unknown engine rejected

- **WHEN** the engine is set to `CH_ENGINE_UNKNOWN`
- **THEN** parsing fails with a validation error

### Requirement: Options forwarded to PeerDB

When creating a mirror, the client SHALL pass every configured table-mapping option to the PeerDB API so the mirror is created with those options.

#### Scenario: Options reach the destination table

- **WHEN** a mirror is created with a MergeTree engine, a custom sorting key, and a partition-by expression
- **THEN** the PeerDB API accepts the mirror
- **AND** the destination table is created with the configured engine, sorting key, and partitioning

#### Scenario: Invalid expression rejected by PeerDB

- **WHEN** a mirror is created with a partition-by expression that references an unknown column
- **THEN** mirror creation fails with a PeerDB API error

### Requirement: Backward compatibility

Mirror configurations that set none of the new options SHALL behave exactly as before, including parsing successfully and producing the same mirrors.

#### Scenario: Existing configuration unchanged

- **WHEN** a mirror is created from a configuration that sets none of the new options
- **THEN** creation succeeds
- **AND** the destination table uses the backend default engine, ReplacingMergeTree
