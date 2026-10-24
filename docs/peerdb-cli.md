# PeerDB CLI Behaviour

> **Status:** Last updated 2026-10-24. Covers the `cli peerdb` commands in `examples/cli`.

## Scope

This document describes what each `cli peerdb` command does, when it returns, and which PeerDB objects it changes. It covers the example CLI in `examples/cli/packages/example_cli/src/example_cli/peerdb_cli`. The dbt and loader commands are out of scope.

The CLI is a thin wrapper around `dw_lib.peerdb.PeerDB`. The PeerDB server performs validation and state transitions; the CLI sends requests and polls. This document notes server behaviour only where it affects what the CLI waits for.

## Configuration

Every CLI invocation resolves a PeerDB config file before it parses arguments:

1. If `PEERDB_CONFIG_FILE` is set, that path must exist.
2. Otherwise the CLI searches upward from the current working directory for `peerdb.yaml`.

A missing file stops the CLI with `FileNotFoundError` or `ConfigFileNotFoundException`. Resolution happens at import time, so even `--help` needs a discoverable config file.

The YAML is rendered as a Jinja template, and `+defaults` blocks are merged into sibling peer and mirror entries. Relevant settings:

| Setting | Meaning | Default |
|---------|---------|---------|
| `peerdb_ui_url` | PeerDB UI base URL; the client calls `<peerdb_ui_url>/api/v1/...` | Required |
| `operation_timeout` | Seconds spent polling long-running operations | 15, minimum 1 |
| `settings` | Dynamic settings applied by `settings update` and `up` | Empty |
| `peers` | Peer definitions; the YAML key is the peer name | Empty |
| `mirrors` | Mirror definitions; the YAML key is the mirror name (`flow_job_name`) | Empty |

Peers and mirrors are addressed by their YAML keys. A `[NAME]` argument for `peer create` or `mirror create` must match a config key. For the other commands, the name is looked up on the PeerDB server.

## Blocking behaviour at a glance

**Blocking** means the command does not return until the stated condition is met. **Non-blocking** means it returns once the server accepts the request; the server continues the work.

| Command | Sends | Blocking? | Returns when | Does not block for |
|---------|-------|-----------|--------------|--------------------|
| `settings update` | One POST per setting | Blocking | Every setting request has succeeded | A read-back; no polling |
| `peer create` | POST create | Blocking | The API returns status `CREATED` | Nothing else; the API creates the peer before responding |
| `peer drop` | Drop each dependent mirror, then POST peer drop | Blocking | Every dependent mirror has disappeared and the peer-drop request returns | A post-drop poll of the peer; the API deletes it before responding |
| `mirror create` | POST CDC create | Non-blocking | The API returns a `workflowId` | Setup, initial snapshot, or `RUNNING` |
| `mirror drop` | POST terminate | Blocking | The status endpoint reports the mirror is gone | Nothing else |
| `mirror pause` | POST pause, only when running | Blocking | The status is `PAUSED` | Nothing else |
| `mirror resume` | POST resume, only when paused or pausing | Blocking | The status is `RUNNING` | Nothing else |
| `mirror resync` | POST resync | Blocking until `RESYNC` | The status is `RESYNC` | Completion of the resync (return to `RUNNING`) |

Three blocking categories appear in the table:

- **Blocking request.** The command does not return until the HTTP response arrives. `settings update` and `peer create` work this way.
- **Blocking with polling.** The command does not return until the target state is reached or `operation_timeout` expires. `mirror drop`, `mirror pause`, `mirror resume`, `mirror resync`, and each dependent mirror drop in `peer drop` work this way.
- **Non-blocking.** The command returns when the server accepts the request; the server continues the work. `mirror create` works this way, and `up` is non-blocking for mirror readiness.

No command blocks until a newly created or resynced mirror reaches `RUNNING`. Use `cli peerdb debug` or the PeerDB UI to follow progress.

`mirror resync` is blocking until `STATUS_RESYNC` but non-blocking for the rest of the resync. `STATUS_RESYNC` is set after the resync snapshot finishes and immediately before PeerDB renames the destination tables. The command therefore blocks for the expensive part of the resync, but it returns before the mirror is running again. It is not merely an acknowledgment.

`up` chains `settings update`, `peer create --all`, and `mirror create --all` in that order. `debug` is read-only. Both are described below.

## Common argument rules

For every command that accepts `[NAME]` and `--all`:

- Exactly one is required. Providing both, or neither, raises a Typer `BadParameter` and exits with status 2.
- Processing is sequential: config order for creates and config-based drops, server name order for the other `--all` commands. The command stops at the first error.

The source of names for `--all` differs by command:

| Command | `--all` iterates |
|---------|------------------|
| `peer create` | Peers in the local config |
| `peer drop` | Peers in the local config |
| `mirror create` | Mirrors in the local config |
| `mirror drop` | Mirrors on the PeerDB server |
| `mirror pause` | Mirrors on the PeerDB server |
| `mirror resume` | Mirrors on the PeerDB server |
| `mirror resync` | Mirrors on the PeerDB server |

Creates need a config payload, so they iterate the config. The other commands act on server state, so they list the server. A peer that exists on the server but not in the config is therefore not dropped by `peer drop --all`.

## Option defaults

| Option | Commands | CLI default | Accepted values |
|--------|----------|-------------|-----------------|
| `--if-exists` | `peer create`, `mirror create`, `up` | `keep` | `fail`, `keep`, `replace` |
| `--if-exists` / `--no-if-exists` | `peer drop`, `mirror drop`, `mirror resync` | On | Boolean |
| `--drop-destination-tables` / `--no-drop-destination-tables` | `peer drop`, `mirror drop` | Off | Boolean |

The create commands use `keep` by default, so an existing peer or mirror is left untouched. The library defaults differ: `fail` for creates and `False` for the drop and resync `if_exists` flags. The CLI overrides both to be more forgiving.

## Commands

### `cli peerdb settings update`

Applies every setting under `settings:` in the config.

1. Reads the settings into a name/value map.
2. Sends one `POST /api/v1/dynamic_settings` per setting, in YAML order.
3. Stops at the first failure with `SetDynamicSettingsException`.

The command is blocking: it returns after each POST returns. It does not read the settings back and does not poll. Applying a setting is immediate on the server, though some settings take effect only for new mirrors or after a resume, according to PeerDB's `apply_mode`.

Options: none.

### `cli peerdb peer create [NAME] [--all] [--if-exists fail|keep|replace]`

Creates one configured peer, or all configured peers.

For each peer:

1. Checks the server peer list.
2. Applies `--if-exists`:
   - `keep` (default): skips a peer that already exists.
   - `replace`: drops the existing peer with all its mirrors and their destination tables, then creates it again.
   - `fail`: raises `PeerExistsException`.
3. Sends `POST /api/v1/peers/create`.
4. Requires the response status `CREATED`; any other status raises `CreatePeerException`.

The command is blocking until the API has created the peer. The PeerDB API validates the peer and writes it to its metadata store before responding, so no polling is needed.

If `[NAME]` is not in the config, the command raises `PeerNotFoundException`. `--all` uses the config list, not the server list.

Note that `replace` is destructive: it removes the peer's mirrors and their destination tables before recreating the peer.

### `cli peerdb peer drop [NAME] [--all] [--drop-destination-tables] [--if-exists]`

Drops one peer, or all configured peers, and their mirrors.

For each peer:

1. Lists the server mirrors and drops every mirror whose source or destination is the peer. Each mirror drop blocks until the mirror disappears from the server.
2. Checks whether the peer still exists. If it is missing and `--if-exists` is set, the peer is skipped with a message; otherwise `PeerNotFoundException` is raised.
3. Sends `POST /api/v1/peers/drop` and blocks until the response arrives. The API deletes the peer before responding, so the client does not poll afterwards.

Defaults: `--if-exists` is on, `--drop-destination-tables` is off. Both accept the negative form (`--no-if-exists`, `--no-drop-destination-tables`).

`--drop-destination-tables` is passed to each dependent mirror drop. Destination tables are dropped only for mirrors present in the local config; if a mirror or its destination peer is missing from the config, or the adapter is unsupported, the table drop is skipped with a message.

The peer name does not have to appear in the local config. Only `--all` is limited to config peers.

If a dependent mirror cannot be dropped within `operation_timeout`, the command stops before attempting to drop the peer. PeerDB also refuses to drop a peer that is still referenced by a flow.

### `cli peerdb mirror create [NAME] [--all] [--if-exists fail|keep|replace]`

Creates one configured mirror, or all configured mirrors.

For each mirror:

1. Checks the server for an existing mirror with the same name.
2. Applies `--if-exists`:
   - `keep` (default): skips an existing mirror.
   - `replace`: drops the existing mirror and its destination tables, then continues.
   - `fail`: raises `MirrorExistsException`.
3. Validates the source:
   - The source peer must exist in the config.
   - Its adapter must be Postgres; otherwise `UnsupportedAdapterException`.
   - Each mapped source table must exist in the source database; otherwise `TableNotFoundException`.
4. Best-effort drops the destination tables listed in the mirror's table mappings. Tables that do not exist are ignored. If the mirror or destination peer is missing from the config, or the adapter is unsupported, the drop is skipped with a message.
5. Sends `POST /api/v1/flows/cdc/create` with `{"connection_configs": <mirror>}`.
6. Requires a `workflowId` in the response; otherwise `CreateMirrorException`.

The command is non-blocking with respect to mirror creation: it returns when PeerDB has accepted the request and started the workflow. It does not block for setup, the initial snapshot, or `STATUS_RUNNING`.

Two behaviours need emphasis:

- Creating a mirror always attempts to drop the mapped destination tables first, even when the mirror is new. Any existing tables at those names are removed when the destination peer is in the config.
- Source-table validation uses a direct connection to the source Postgres database, not the PeerDB API.

### `cli peerdb mirror drop [NAME] [--all] [--drop-destination-tables] [--if-exists]`

Drops one mirror, or all mirrors on the server.

For each mirror:

1. Checks whether the mirror exists. If it is missing and `--if-exists` is set, it is skipped with a message; otherwise `MirrorNotFoundException` is raised.
2. Sends `POST /api/v1/mirrors/state_change` with `requestedFlowState=STATUS_TERMINATING`, `dropMirrorStats=true`, and `skipDestinationDrop=false`.
3. Polls the status endpoint once per second until the mirror is no longer found, or until `operation_timeout` expires. On expiry, raises `MirrorTimeoutException`.
4. If `--drop-destination-tables` is set, drops the mapped destination tables from the local config. Missing config entries and unsupported adapters are skipped with a message.

Defaults: `--if-exists` is on, `--drop-destination-tables` is off.

The command is blocking until PeerDB has terminated and removed the mirror. `skipDestinationDrop=false` lets PeerDB clean up its internal destination objects, such as the raw table. User destination tables are dropped only with `--drop-destination-tables`.

`--all` lists the server, so it also drops mirrors that are not in the local config. A named mirror that is absent from the config can still be dropped. In both cases, destination tables are not dropped unless the mirror is defined in the config.

### `cli peerdb mirror pause [NAME] [--all]`

Pauses one running mirror, or all mirrors on the server.

For each mirror:

1. Checks whether the mirror exists; if not, raises `MirrorNotFoundException`. There is no `--if-exists` option.
2. Reads the current status. If it is not `STATUS_RUNNING`, the command prints a no-op message and sends no request. This includes mirrors that are already paused, snapshotting, or failed.
3. Sends `POST /api/v1/mirrors/state_change` with `requestedFlowState=STATUS_PAUSED`.
4. Polls once per second until the status is `STATUS_PAUSED`, or until `operation_timeout` expires.

The command is blocking until the status is `STATUS_PAUSED` or `operation_timeout` expires.

Because `--all` lists the server, it visits every mirror and prints a no-op message for each one that is not running.

### `cli peerdb mirror resume [NAME] [--all]`

Resumes one paused or pausing mirror, or all mirrors on the server.

For each mirror:

1. Checks whether the mirror exists; if not, raises `MirrorNotFoundException`. There is no `--if-exists` option.
2. Reads the current status. If it is neither `STATUS_PAUSED` nor `STATUS_PAUSING`, the command prints a no-op message and sends no request.
3. Sends `POST /api/v1/mirrors/state_change` with `requestedFlowState=STATUS_RUNNING`.
4. Polls once per second until the status is `STATUS_RUNNING`, or until `operation_timeout` expires.

The command is blocking until the status is `STATUS_RUNNING` or `operation_timeout` expires.

### `cli peerdb mirror resync [NAME] [--all] [--if-exists]`

Resyncs one mirror, or all mirrors on the server. A resync picks up added or removed columns and changed column types.

For each mirror:

1. Checks whether the mirror exists. If it is missing and `--if-exists` is set, it is skipped with a message; otherwise `MirrorNotFoundException` is raised.
2. Sends `POST /api/v1/mirrors/state_change` with `requestedFlowState=STATUS_RESYNC` and `dropMirrorStats=true`.
3. Polls once per second until the status is `STATUS_RESYNC`, or until `operation_timeout` expires.

Default: `--if-exists` is on.

The command is blocking until `STATUS_RESYNC` but non-blocking for the rest of the resync. PeerDB sets `STATUS_RESYNC` after the resync snapshot completes and immediately before it renames the destination tables. The command returns at that point, before the rename and the return to `STATUS_RUNNING`. A large table can keep the command polling for a long time; set `operation_timeout` accordingly.

For a mirror in `STATUS_COMPLETED` or `STATUS_FAILED`, PeerDB recreates the flow to resync it. The client still blocks until `STATUS_RESYNC`.

### `cli peerdb up [--if-exists fail|keep|replace]`

Brings the configured peers and mirrors up in one pass:

1. Applies all settings with blocking requests, like `settings update`.
2. Creates all config peers in config order, like `peer create --all`.
3. Creates all config mirrors in config order, like `mirror create --all`.

`--if-exists` defaults to `keep` and applies to both peers and mirrors. With `replace`, each peer is dropped with its mirrors and destination tables before being recreated; mirrors are then recreated from config.

The command is non-blocking for mirror readiness: it does not block for mirrors to finish setup or snapshot. PeerDB provisions publications and replication slots as part of mirror setup. The command stops at the first error.

### `cli peerdb debug`

Performs read-only checks and prints the results:

- PeerDB API reachability, using the dynamic settings endpoint.
- Source and destination database connections.
- Source Postgres prerequisites: `max_replication_slots >= 4`, `max_wal_senders >= 1`, and `wal_level = logical`.
- Missing publications: publications configured with a name but absent from the source database.
- Unused publications: publications in the source database that are absent from the config.
- Peers on the server.
- Mirrors on the server with their current status.
- Replication slots for mirrors. A running mirror without a slot is flagged.

The command requires config peers named `source` and `destination`, plus direct access to both databases. It does not change PeerDB or either database.

## Mirror status reference

The CLI uses these PeerDB flow states when it decides whether to act and what to wait for:

| Status | Value | Relevance |
|--------|-------|-----------|
| `STATUS_UNKNOWN` | 0 | The CLI treats this as a missing mirror |
| `STATUS_RUNNING` | 1 | `pause` acts only from this state; `resume` waits for it |
| `STATUS_PAUSED` | 2 | `pause` waits for it; `resume` acts from it |
| `STATUS_PAUSING` | 3 | `resume` acts from it |
| `STATUS_SETUP` | 4 | Created mirror is still setting up |
| `STATUS_SNAPSHOT` | 5 | Initial or resync snapshot is running |
| `STATUS_TERMINATING` | 6 | `drop` has requested termination and is polling |
| `STATUS_TERMINATED` | 7 | Flow is terminated |
| `STATUS_COMPLETED` | 8 | Flow completed; `resync` recreates it |
| `STATUS_RESYNC` | 9 | `resync` waits for it; set after the resync snapshot, before the rename |
| `STATUS_FAILED` | 10 | Flow failed; `resync` recreates it |
| `STATUS_MODIFYING` | 11 | Flow is applying a configuration change |

## Timeouts, errors, and output

- **Polling.** Each poll sleeps for one second. `operation_timeout` is both the number of attempts and roughly the number of seconds. It defaults to 15 and must be at least 1.
- **Per-mirror cost.** `peer drop` applies the timeout to each dependent mirror separately, so the worst case is the number of mirrors multiplied by `operation_timeout`.
- **HTTP timeouts.** Most requests use a fixed five-second HTTP timeout. State-change requests (`drop`, `pause`, `resume`, `resync`) and the peer-drop request have no HTTP timeout, so an unresponsive server can block the command.
- **Errors.** The CLI does not catch exceptions. PeerDB errors such as `MirrorTimeoutException`, `CreateMirrorException`, or `PeerNotFoundException` propagate as a traceback and exit status 1. Argument errors exit with status 2.
- **Output.** The library prints progress lines such as `Creating peer 'x'` before requests. The CLI then prints a green result message from the response, for example `Created peer 'x'` or `Not pausing mirror 'x' because its status is 'STATUS_PAUSED'`.
- **Concurrency.** All operations are sequential. `--all` stops at the first failure, leaving later entries untouched.

## Safety notes

- `mirror create` always attempts to drop the mapped destination tables before creating the mirror. Do not point a new mirror at tables that must survive.
- `--if-exists replace` destroys data. For peers it drops dependent mirrors and their destination tables; for mirrors it drops destination tables.
- `peer drop --all` is narrower than `mirror drop --all`: the former covers config peers, the latter covers every mirror on the server.
- `mirror resync` can block for as long as the resync snapshot takes, even though it does not wait for the final rename.
- `peer drop`, `mirror drop`, and `mirror resync` skip missing objects by default. See [Option defaults](#option-defaults).

## Source references

| Behaviour | Location |
|-----------|----------|
| Command registration and `up` | `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/__init__.py:11` |
| Peer commands | `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/peer.py:14` |
| Mirror commands | `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/mirror.py:14` |
| Settings command | `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/settings.py:11` |
| Config resolution | `src/dw_lib/peerdb.py:2452` |
| HTTP request timeout | `src/dw_lib/peerdb.py:54` |
| Operation timeout default | `src/dw_lib/peerdb.py:57` |
| Debug checks | `src/dw_lib/peerdb.py:1096` |
| Update settings | `src/dw_lib/peerdb.py:1354` |
| Create peer | `src/dw_lib/peerdb.py:1476` |
| Drop peer | `src/dw_lib/peerdb.py:1545` |
| Drop dependent mirrors | `src/dw_lib/peerdb.py:1614` |
| Poll mirror status | `src/dw_lib/peerdb.py:1734` |
| Create mirror | `src/dw_lib/peerdb.py:1770` |
| Drop mirror | `src/dw_lib/peerdb.py:1887` |
| Resync mirror | `src/dw_lib/peerdb.py:1979` |
| Pause mirror | `src/dw_lib/peerdb.py:2045` |
| Resume mirror | `src/dw_lib/peerdb.py:2107` |
| Drop destination tables | `src/dw_lib/peerdb.py:2169` |
