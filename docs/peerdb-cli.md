# PeerDB CLI

The `peerdb` commands wrap the `PeerDB` client in `src/dw_lib/peerdb.py`. They read `peerdb.yaml`, call the PeerDB REST API and, for some checks, connect directly to the source and destination databases. The commands target PeerDB v0.37.10.

## Configuration

- The CLI uses `PEERDB_CONFIG_FILE` when set. Otherwise it searches upward from the working directory for `peerdb.yaml`.
- The API base URL is `client.peerdb_ui_url` joined with `api`.
- Client timeouts are flat keys under `client`. All are optional and have defaults; see [Timeouts](#timeouts).
- `debug` expects peers named `source` and `destination`. Publication and replication-slot checks use the `source` peer.
- Mirror creation requires the source peer to use the Postgres adapter.
- The config file is resolved when the CLI starts. `--help` therefore needs a discoverable `peerdb.yaml`.

## Commands

| Command | Purpose |
|---|---|
| `cli peerdb debug` | Check the API, database connections, publications, peers, mirrors and replication slots. |
| `cli peerdb up [--if-exists MODE]` | Apply settings, create all configured peers and create all configured mirrors. |
| `cli peerdb settings update` | Apply all settings from `peerdb.yaml`. |
| `cli peerdb peer create [NAME] [--all] [--if-exists MODE]` | Create one configured peer or all configured peers. |
| `cli peerdb peer drop [NAME] [--all] [--drop-destination-tables] [--if-exists]` | Drop one peer or all configured peers, including their mirrors. |
| `cli peerdb mirror create [NAME] [--all] [--if-exists MODE]` | Create one configured mirror or all configured mirrors. |
| `cli peerdb mirror drop [NAME] [--all] [--drop-destination-tables] [--if-exists]` | Drop one server mirror or all server mirrors. |
| `cli peerdb mirror pause [NAME] [--all]` | Pause one running mirror or all running mirrors. |
| `cli peerdb mirror resume [NAME] [--all]` | Resume one paused mirror or all paused mirrors; a pausing mirror is resumed after it pauses. |
| `cli peerdb mirror resync [NAME] [--all] [--if-exists]` | Resync one server mirror or all server mirrors. |

Append `--help` to any command to see its options.

### Common options

- Every command that takes `NAME` also takes `--all`. Provide exactly one of them.
- `--all` uses the local config for `peer create`, `peer drop` and `mirror create`. It uses the server mirror list for `mirror drop`, `mirror pause`, `mirror resume` and `mirror resync`.
- For create commands, `--if-exists` accepts `fail`, `keep` or `replace`. The default is `keep`.
  - `fail` raises when the peer or mirror exists.
  - `keep` returns without changing the existing object.
  - `replace` drops the existing object before creating it. For peers and mirrors, this also drops destination tables.
- For drop and resync commands, `--if-exists/--no-if-exists` defaults to true. When true, a missing object is skipped. When false, a missing object raises.
- `--drop-destination-tables/--no-drop-destination-tables` defaults to false.

## `peerdb debug`

```shell
cli peerdb debug
```

Checks, in order:

1. The PeerDB API, by requesting dynamic settings.
2. The source and destination database connections.
3. The source Postgres settings `max_replication_slots >= 4`, `max_wal_senders >= 1` and `wal_level = logical`.
4. Missing and unused publications, by comparing the local config with `pg_publication_tables`.
5. Peers on the server.
6. Mirrors on the server, with their current status and replication-slot name.
7. Replication slots. It reports `Not OK` when no mirror has a replication slot and at least one mirror is `Running`.

The command does not check table mappings, destination schemas or whether a sync is healthy beyond the reported status. It also does not wait for any workflow to change state.

Missing publications only include config entries with an explicit `publication_name`. PeerDB-managed publications are ignored. Unused publications can include PeerDB-managed publications when the config leaves `publication_name` empty.

`debug` requires configured peers named `source` and `destination`, and the source must be Postgres.

**Blocking:** fully synchronous. It waits for every API and database check and one status request per mirror. It returns a snapshot of the current state.

## `peerdb up`

```shell
cli peerdb up [--if-exists fail|keep|replace]
```

Runs three steps in order:

1. Apply every setting from `peerdb.yaml`.
2. Create every configured peer, in config order.
3. Create every configured mirror, in config order.

The same `--if-exists` value applies to peers and mirrors. The default, `keep`, leaves existing peers and mirrors untouched and creates missing ones. Use `mirror resync` to pick up added or removed columns and changed types on an existing mirror.

Creating a mirror starts PeerDB's setup workflow. That workflow creates the publication and replication slot on the source and the required objects on the destination. `up` does not wait for setup, snapshot or sync to finish.

**Blocking:** synchronous through settings, peers and mirrors. Each mirror create performs source-table validation and destination-table cleanup, then starts the workflow. `up` returns when the last create request returns, not when the mirror reaches `Running`. A failure in any step stops the command before later steps.

**Warning:** `--if-exists replace` drops existing peers or mirrors and their destination tables before recreating them.

## `peerdb settings update`

```shell
cli peerdb settings update
```

Applies every setting from `peerdb.yaml` with a separate `POST v1/dynamic_settings` request.

Settings with `APPLY_MODE_IMMEDIATE` take effect at once. Settings with `APPLY_MODE_AFTER_RESUME` or `APPLY_MODE_NEW_MIRROR` take effect later. The command does not wait for those modes.

**Blocking:** synchronous. The first failed setting aborts the remaining settings.

## `peerdb peer create`

```shell
cli peerdb peer create [NAME] [--all] [--if-exists fail|keep|replace]
```

Creates one peer from the local config, or all configured peers. A named peer must exist in `peerdb.yaml`; otherwise the command raises `PeerNotFoundException`.

PeerDB validates the peer connection during creation. The command does not start a mirror or wait for a workflow.

**Blocking:** synchronous until PeerDB validates and creates the peer. No lifecycle wait.

## `peerdb peer drop`

```shell
cli peerdb peer drop [NAME] [--all] [--drop-destination-tables] [--if-exists]
```

Drops one peer, or all peers from the local config.

Before deleting the peer, the command lists server mirrors and drops every mirror whose source or destination is the peer. Each mirror drop waits for the mirror to disappear. The peer delete then runs. PeerDB rejects a peer delete while a mirror still references the peer.

Dropping a mirror normally removes PeerDB's publication and replication slot for that mirror. User destination tables are dropped only when `--drop-destination-tables` is set.

**Blocking:** synchronous. It drops dependent mirrors one at a time, polls each until it disappears, then deletes the peer. With `--all`, it repeats this for each configured peer.

## `peerdb mirror create`

```shell
cli peerdb mirror create [NAME] [--all] [--if-exists fail|keep|replace]
```

Creates one mirror from the local config, or all configured mirrors. A named mirror must exist in `peerdb.yaml`; otherwise the command raises `MirrorNotFoundException`.

For each mirror that it creates, the command:

1. Checks whether the mirror exists and applies `--if-exists`.
2. Checks that the source peer uses the Postgres adapter.
3. Checks that every mapped source table exists, using a direct database connection.
4. Best-effort drops the mapped destination tables, so the initial snapshot starts clean.
5. Sends `POST v1/flows/cdc/create` and requires a workflow ID in the response.

The destination-table drop in step 4 happens even for a new mirror. Use `keep` to avoid touching an existing mirror, or `replace` to drop the existing mirror and its destination tables first.

**Blocking:** synchronous through source-table validation, destination-table cleanup and the create request. It returns after PeerDB starts the workflow. Setup, snapshot and sync continue asynchronously.

## `peerdb mirror drop`

```shell
cli peerdb mirror drop [NAME] [--all] [--drop-destination-tables] [--if-exists]
```

Drops one server mirror, or all server mirrors. A missing mirror is skipped when `--if-exists` is true, which is the default.

The command sends `STATUS_TERMINATING` with `dropMirrorStats=True` and polls until the mirror no longer exists. PeerDB cleans up its own source and destination objects during termination, except for a flow that already completed an `initial_snapshot_only` run. It does not drop user destination tables.

A mirror that is already `Terminated` cannot be dropped through the PeerDB API. The command raises a client-side error instead of waiting for a timeout.

With `--drop-destination-tables`, the command drops the mapped destination tables after the mirror disappears. This step needs the mirror in the local config. If the mirror is missing from the config, the command prints a skip message and leaves the tables in place.

**Blocking:** synchronous until the mirror disappears, the mirror reports `Terminated`, or the polling timeout expires. A timeout does not cancel the backend termination workflow; the mirror may still disappear later.

## `peerdb mirror pause`

```shell
cli peerdb mirror pause [NAME] [--all]
```

Pauses one server mirror, or all server mirrors.

The command reads the current status first. It only sends `STATUS_PAUSED` when the mirror is `Running`. For any other status it returns a no-op message. PeerDB may report `Pausing` while the current sync finishes, then `Paused`. A mirror that is already `Terminated` raises a client-side error.

**Blocking:** the no-op path returns immediately. Otherwise the command waits until the mirror reports `Paused` or the polling timeout expires. It does not pause a mirror during setup or snapshot.

## `peerdb mirror resume`

```shell
cli peerdb mirror resume [NAME] [--all]
```

Resumes one server mirror, or all server mirrors.

The command reads the current status first. A mirror that is `Paused` receives `STATUS_RUNNING` immediately. A mirror that is `Pausing` first waits for `Paused`, then receives `STATUS_RUNNING`. For any other status it returns a no-op message. A mirror that is already `Terminated` raises a client-side error.

**Blocking:** the no-op path returns immediately. Otherwise the command waits for `Paused` when needed, then waits until the mirror reports `Running` or the polling timeout expires.

## `peerdb mirror resync`

```shell
cli peerdb mirror resync [NAME] [--all] [--if-exists]
```

Resyncs one server mirror, or all server mirrors. A missing mirror is skipped when `--if-exists` is true, which is the default.

The command sends `STATUS_RESYNC` with `dropMirrorStats=True`, then waits for a resync-started status: `Resync`, `Setup` or `Snapshot`. It does not wait for the resync to finish.

PeerDB resyncs a CDC mirror by dropping and recreating the flow. A running mirror normally moves through `Resync`, `Setup`, `Snapshot`, `Resync` and then `Running`. For a mirror in a terminal state (`Completed` or `Failed`), PeerDB recreates the flow before the API returns, so the command also accepts `Completed` and `Running` as signs that the new flow has started.

A mirror that is `Terminating` or `Terminated` cannot be resynced. The command raises a client-side error before sending the request.

**Blocking:** synchronous until a resync-started status appears, a stopped status raises, or the polling timeout expires.

**Caveat:** `--all` uses the server mirror list. A non-CDC mirror causes the API to reject the resync request, and the command stops before processing the remaining mirrors.

## Lifecycle events and statuses

PeerDB records a flow status in the catalog `flows.status` column. The API returns that value as `currentFlowState`. The status can lag the actual Temporal workflow by a moment. State-change commands poll at `client.operation_interval`, which defaults to one second.

### Events

- **Create:** The API creates a flow row and starts a CDC workflow. The initial status is `Setup`.
- **Setup:** PeerDB checks connections, creates metadata tables, the publication and replication slot on the source, and destination objects.
- **Snapshot:** PeerDB copies the mapped tables. During the initial snapshot, the mirror is not applying changes yet.
- **Sync:** The workflow enters the CDC loop and applies changes in batches. Status is `Running`.
- **Pause:** A pause signal stops the current sync activity. Status moves through `Pausing` to `Paused`.
- **Resume:** A resume signal restarts the sync. Status returns to `Running`. A mirror that is still pausing must reach `Paused` first.
- **Resync:** PeerDB drops and recreates the flow, takes a new snapshot and swaps the destination tables. Status uses `Resync`, `Setup`, `Snapshot` and `Resync`.
- **Table changes:** Added tables use a child snapshot (`Snapshot`). Removed tables use `Modifying`.
- **Terminate:** A termination signal removes the flow and normally cleans up source and destination objects. Status is `Terminating`.
- **Failure:** A failed setup, snapshot, rename or configuration update sets `Failed`. Sync errors retry with backoff and keep the mirror in `Running`. A resync can recreate a failed flow.

### Statuses

| Status | Code | Meaning |
|---|---:|---|
| `STATUS_UNKNOWN` | 0 | No known state. `has_mirror()` treats this as a missing mirror. |
| `STATUS_RUNNING` | 1 | The snapshot is finished and the CDC sync loop is active. This is the healthy steady state. |
| `STATUS_PAUSED` | 2 | Sync is stopped. The workflow waits for resume, resync or termination. |
| `STATUS_PAUSING` | 3 | A pause signal was received and the current sync is finishing. Transient. |
| `STATUS_SETUP` | 4 | The flow was created. PeerDB checks connections and creates metadata, the publication, the replication slot and destination objects. |
| `STATUS_SNAPSHOT` | 5 | The initial snapshot, a resync snapshot or a table-addition snapshot is running. |
| `STATUS_TERMINATING` | 6 | Termination was requested. PeerDB normally cleans up source and destination objects and mirror stats. |
| `STATUS_TERMINATED` | 7 | The workflow stopped or was cancelled. Terminal. Operations that require an active flow raise a client-side error. |
| `STATUS_COMPLETED` | 8 | The flow finished because `initial_snapshot_only` was set. Terminal. |
| `STATUS_RESYNC` | 9 | A resync is in progress: either the drop/recreate phase or the final table swap after the resync snapshot. |
| `STATUS_FAILED` | 10 | Setup, snapshot, rename or a configuration update failed. Terminal until a resync recreates the flow. |
| `STATUS_MODIFYING` | 11 | Table removals are being applied. Table additions use `Snapshot` instead. |

`debug` prints these statuses as title-cased labels, such as `Running`, `Pausing` and `Failed`.

### Typical transitions

| Event | Typical transition |
|---|---|
| Create a mirror | `Setup` -> `Snapshot` -> `Running` |
| Create with `initial_snapshot_only` | `Setup` -> `Snapshot` -> `Completed` |
| Pause | `Running` -> `Pausing` -> `Paused` |
| Resume | `Paused` -> `Running` |
| Resync from a non-terminal state | `Resync` -> `Setup` -> `Snapshot` -> `Resync` -> `Running` |
| Resync from `Completed` or `Failed` | `Terminating` -> `Setup` -> `Snapshot` -> `Resync` -> `Running` |
| Add tables | `Snapshot` -> `Running` |
| Remove tables | `Modifying` -> `Running` |
| Drop a mirror | `Terminating` -> mirror removed |
| Cancel a workflow | `Terminated` |
| Setup, snapshot or rename failure | `Failed` |

### Commands and lifecycle events

| Command | Lifecycle effect |
|---|---|
| `peerdb up`, `peerdb peer create` | Creates peers. No flow status. |
| `peerdb up`, `peerdb mirror create` | Creates flows, which enter `Setup`. |
| `peerdb mirror pause` | Sends a pause signal. Terminated mirrors raise an error. |
| `peerdb mirror resume` | Waits for `Paused` when the mirror is pausing, then sends a resume signal. Terminated mirrors raise an error. |
| `peerdb mirror resync` | Sends a resync signal, or recreates a terminal flow. Terminating and terminated mirrors raise an error. |
| `peerdb mirror drop`, `peerdb peer drop` | Sends a termination signal and removes the flow. Terminated mirrors raise an error. |
| `peerdb settings update`, `peerdb up` | Updates dynamic settings. |
| `peerdb debug` | Read-only. |

## Blocking behavior

Two layers matter:

- **PeerDB API:** most flow state changes are asynchronous. The API accepts a signal and returns before the workflow acts.
- **CLI wrapper:** some commands add polling on top of the API. These commands block until a target status appears, the mirror disappears or the timeout expires.

For a mirror in a terminal state (`Completed` or `Failed`), the API may drop or recreate the flow before it returns. The state-change request itself can therefore take longer than usual. A `Terminated` mirror cannot be changed and raises a client-side error.

### Timeouts

Client timeouts are flat keys under `client`. Every key is optional and has a default.

| Key | Default | Used by |
|---|---:|---|
| `connect_timeout` | 5 | Every API request, as the TCP connect timeout. |
| `read_timeout` | 60 | Read-only API calls: version, settings read, peer info/type, peer list, mirror list, mirror status. |
| `operation_interval` | 1.0 | Interval between polling requests. |
| `settings_update_timeout` | 60 | Settings updates, including `up`. |
| `peer_create_timeout` | 90 | Peer creation, including `up`. |
| `peer_drop_timeout` | 60 | Peer deletion, including `--if-exists replace`. |
| `mirror_create_timeout` | 300 | Mirror creation, including `up`. |
| `mirror_drop_timeout` | 900 | Mirror deletion, including `peer drop` and `--if-exists replace`. |
| `mirror_pause_timeout` | 60 | Mirror pause requests. |
| `mirror_resume_timeout` | 60 | Mirror resume requests. |
| `mirror_resync_timeout` | 900 | Mirror resync requests. |
| `mirror_drop_operation_timeout` | 600 | Polling while a mirror is deleted. |
| `mirror_pause_operation_timeout` | 120 | Polling while a mirror pauses. |
| `mirror_resume_operation_timeout` | 180 | Polling while a mirror resumes. |
| `mirror_resync_operation_timeout` | 300 | Polling until a resync starts. |

`up` uses the timeouts of the operations it calls: settings update, peer creation and mirror creation. `debug` uses `read_timeout`. Nested operations use their own keys; for example, `peer drop` uses `mirror_drop_timeout` and `mirror_drop_operation_timeout` for dependent mirrors.

A request timeout does not cancel the backend operation. The command raises after the timeout, but PeerDB may continue processing. Direct database checks have no wrapper-level timeout. `--all` processes items sequentially. One failure stops the remaining items.

### Command summary

| Command | Blocks on | Returns when | Async work after return |
|---|---|---|---|
| `debug` | API, database checks and per-mirror status requests | All checks finish | None |
| `up` | Settings, peer creation, source-table checks, destination-table cleanup and mirror creation | The last create request returns | Setup, snapshot and sync |
| `settings update` | Every setting POST | All settings are posted | Settings with deferred apply modes |
| `peer create` | Peer validation and creation | The peer is created | None |
| `peer drop` | Dependent mirror drops and peer deletion | The peer is deleted | None |
| `mirror create` | Source-table checks, destination-table cleanup and creation | PeerDB starts the workflow | Setup, snapshot and sync |
| `mirror drop` | Termination request and mirror disappearance | The mirror is gone, a stopped status raises, or the timeout expires | Termination may continue after a timeout |
| `mirror pause` | Status check and pause polling when running | The mirror is `Paused`, a stopped status raises, or the timeout expires | Signal processing if the poll times out |
| `mirror resume` | Status check, wait for `Paused` when pausing, and resume polling | The mirror is `Running`, a stopped status raises, or the timeout expires | Signal processing if the poll times out |
| `mirror resync` | Resync request and resync-status polling | A resync-started status appears, a stopped status raises, or the timeout expires | Drop, setup, snapshot, swap and sync |

## Known limitations

- `up` does not wait for mirrors to reach `Running`. Check `debug` or the PeerDB UI before relying on replication.
- The `up` docstring says it adds replication slots. The command itself creates peers and mirrors. PeerDB creates the publication and replication slot later, during setup.
- `mirror resync` waits for a resync-started status, not for the resync to finish.
- `mirror drop`, `mirror pause`, `mirror resume` and `mirror resync` raise a client-side error for terminated mirrors. The PeerDB API cannot remove terminated rows.
- `peer drop` and `create --if-exists replace` propagate the terminated-mirror error when a dependent mirror is terminated.
- `create --if-exists keep` and `up --if-exists keep` still report a terminated mirror as kept. `replace` raises because the terminated row cannot be removed.
- `mirror drop` can time out while the backend continues termination.
- `--drop-destination-tables` only works when the mirror is in the local config.
- `peer drop --all` uses the local config, so peers that exist only on the server are not dropped.
- `mirror drop`, `mirror pause`, `mirror resume` and `mirror resync` with `--all` use the server mirror list, so they can include mirrors that are not in the local config.
- `--if-exists replace` is destructive for peers and mirrors: it drops destination tables.

## Source references

- CLI commands: `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/`
- Client and polling: `src/dw_lib/peerdb.py` (`FlowStatus`, `create_peer`, `drop_peer`, `create_mirror`, `drop_mirror`, `pause_mirror`, `resume_mirror`, `resync_mirror`, `wait_for_mirror_status`)
- Status enum: `vendor/peerdb/protos/flow.proto`
- State changes: `vendor/peerdb/flow/cmd/handler.go` (`FlowStateChange`)
- CDC workflow: `vendor/peerdb/flow/workflows/cdc_flow.go`
- Drop workflow: `vendor/peerdb/flow/workflows/drop_flow.go`
- Mirror status API: `vendor/peerdb/flow/cmd/mirror_status.go`
