# PeerDB Mirror Processing Design

> **Status:** Last updated 2026-10-22.

## Context

The example CLI creates and resyncs mirrors in Python loops:

- `peerdb up` creates every configured mirror after creating peers (`examples/cli/packages/example_cli/src/example_cli/peerdb_cli/__init__.py:46-47`).
- `mirror create --all` and `mirror create <name>` call the shared create helper (`examples/cli/packages/example_cli/src/example_cli/peerdb_cli/mirror.py:33-42`).
- `mirror resync --all` and `mirror resync <name>` call the shared resync helper (`examples/cli/packages/example_cli/src/example_cli/peerdb_cli/mirror.py:127-132`).

The loops are sequential, but the underlying operations are not:

- `create_mirror()` returns as soon as PeerDB accepts the flow and returns a workflow ID (`src/dw_lib/peerdb.py:2122-2237`). PeerDB then runs the initial snapshot asynchronously. Creating `cdc_one` and `cdc_many` back to back therefore runs both snapshots concurrently.
- `resync_mirror()` waits for the resync to start before returning (`src/dw_lib/peerdb.py:2331-2429`). Waiting only for `STATUS_RESYNC` is insufficient because it is transient:
  - A running CDC mirror is signaled to resync, enters `STATUS_RESYNC` while the old flow is dropped, then recreates the flow and runs setup/snapshot (`STATUS_SETUP`/`STATUS_SNAPSHOT`) before entering `STATUS_RESYNC` again during the rename swap. If a poll misses the drop-phase `STATUS_RESYNC`, the next `STATUS_RESYNC` only appears after the snapshot.
  - A failed drop can leave the mirror in `STATUS_RESYNC` indefinitely, so an unbounded wait on `STATUS_RESYNC` can hang.
  - A `STATUS_COMPLETED` or `STATUS_FAILED` mirror is recreated synchronously by `resyncByRecreatingFlow` (`vendor/peerdb/flow/cmd/handler.go:506-509,676-733`). Its new flow starts at `STATUS_SETUP` and only reaches `STATUS_RESYNC` after the snapshot.
  - The start wait therefore looks for the recreated flow's `STATUS_SETUP`/`STATUS_SNAPSHOT`/`STATUS_COMPLETED`, or `STATUS_RUNNING` after a non-initial status, and is bounded by `resync_start_timeout` (default 15 minutes).
- `drop_mirror()` already sends `STATUS_TERMINATING` and polls until the flow disappears (`src/dw_lib/peerdb.py:2239-2329`). PeerDB's `DropFlowWorkflow` drops the source replication slot and publication before removing the flow row (`vendor/peerdb/flow/workflows/drop_flow.go:19-124,126,231-250`). Drops are already serial and need no change.

PeerDB reports a CDC flow as `STATUS_RUNNING` after setup and the initial snapshot, or `STATUS_COMPLETED` when `initial_snapshot_only` is set (`vendor/peerdb/flow/workflows/cdc_flow.go:835-840`). `STATUS_SETUP` and `STATUS_SNAPSHOT` mean the initial load is in progress. `STATUS_RESYNC` is transitional: it is set during the drop phase of a running-mirror resync and again during the rename swap after the snapshot. It is never a ready state.

Constraints:

- The library supports one PeerDB version at a time and does not aim for backward compatibility (`AGENTS.md`).
- The default `operation_timeout` is 15 seconds, which is too short for real initial snapshots.
- Wait settings default to module constants and can be overridden by YAML keys: `resync_start_timeout`, `status_poll_interval`, `status_poll_max_interval`, `status_error_window`, `status_heartbeat_interval`, and `status_unknown_grace`.
- The example CLI is not covered by the repository's test suite; library methods are covered by `tests/peerdb`.
- Serial processing is the default and global across all mirrors. The readiness wait has no timeout. The resync start wait is bounded by `resync_start_timeout` (default 15 minutes); transient status-query errors are retried with backoff, and waits report status changes and periodic heartbeats. Drop behaviour is unchanged. `--parallel` opts out for a run.

## Goals

1. Make serial processing the default for `peerdb up`, `mirror create`, and `mirror resync`.
2. Wait for each created or resynced mirror to become ready before starting the next.
3. Fail fast when a mirror reaches a failure state or disappears.
4. Add `--parallel` to opt out and preserve the previous concurrent behaviour.
5. Bound the resync start wait and make long waits resilient and observable.
6. Document that mirror drops are already serial.

## Non-goals

- Adding a YAML configuration option or environment variable for serial or parallel mode.
- Grouping serialization by source peer; both modes are global.
- Serializing peer creation or mirror drops.
- Limiting CDC concurrency after the initial load finishes.
- Changing PeerDB server behaviour or dynamic settings.
- Waiting for mirrors that are kept by `if_exists=keep`.
- Adding a timeout to the snapshot wait.
- Adding a `--parallel` option to mirror drops.

## Terminology

| Term | Meaning |
|------|---------|
| Mirror | A PeerDB CDC flow created from a local mirror definition. |
| Serial processing | The default CLI behaviour that waits for each mirror to become ready before starting the next. |
| Parallel mode | CLI mode enabled by `--parallel` that starts mirror operations without waiting. |
| Initial load | PeerDB's setup and snapshot work before a CDC mirror reaches a ready state. |
| Resync | A requested re-run of a mirror's initial snapshot. |
| Ready | A mirror whose flow state is `STATUS_RUNNING` or `STATUS_COMPLETED`. |
| Failure state | A flow state of `STATUS_FAILED`, `STATUS_TERMINATED`, or `STATUS_TERMINATING`, or `STATUS_UNKNOWN` beyond the readiness grace period. |
| Kept mirror | An existing mirror left in place by `if_exists=keep` instead of being recreated. |

## Architecture

```text
CLI command
  │  --parallel?
  ▼
create/resync helper ──► PeerDB.create_mirror() / PeerDB.resync_mirror()
  │                         │
  │                         ├─ create returns after PeerDB accepts the request
  │                         └─ resync waits up to 15 min for the recreated flow
  │                            (SETUP/SNAPSHOT), or returns after the request in
  │                            parallel mode and for completed/failed mirrors
  │
  └─ if not parallel and a new workflow started:
        PeerDB.wait_for_mirror_ready(name)
          │
          ├─ get_mirror_status() with backoff
          ├─ STATUS_RUNNING/STATUS_COMPLETED → return
          ├─ STATUS_FAILED/STATUS_TERMINATED/STATUS_TERMINATING → MirrorFailedException
          ├─ STATUS_UNKNOWN beyond grace → MirrorFailedException
          └─ otherwise → keep polling, retrying transient errors
```

Numbered flow:

1. The command validates its name/`--all` arguments as it does today.
2. For each mirror, it calls `create_mirror()` or `resync_mirror()`.
3. If `--parallel` is set, create returns after PeerDB accepts the request, and resync returns without observing the resync start. The helper prints the response and continues.
4. Otherwise, create waits for a new workflow, and resync waits up to `resync_start_timeout` (default 15 minutes) for the recreated flow (`STATUS_SETUP`/`STATUS_SNAPSHOT`/`STATUS_COMPLETED`, or `STATUS_RUNNING` after a non-initial status). Completed/failed mirrors are recreated synchronously and skip the start wait. The helper prints a waiting message and calls `wait_for_mirror_ready()`.
5. `wait_for_mirror_ready()` polls `get_mirror_status()` with backoff until the mirror is ready, fails, or disappears. Transient status errors are retried; status changes and periodic heartbeats are reported.
6. The command prints a ready message and proceeds to the next mirror.

For a kept mirror, the create helper detects that `CreateMirrorResponse.response` is `None` and does not wait. For resync of a completed or failed mirror, `resync_mirror()` returns after PeerDB recreates the flow, and the helper waits for the recreated mirror. For a missing mirror with `if_exists=True`, the helper checks `has_mirror()` before waiting so that the skip does not turn into a 404 failure.

## Code layout

| Module | Responsibility |
|--------|----------------|
| `src/dw_lib/exceptions.py` | `MirrorFailedException`. |
| `src/dw_lib/peerdb.py` | `Config` wait settings; `wait_for_mirror_ready()`, `wait_for_mirror_resync_started()`, and the shared status poller; reuse `get_mirror_status()`. |
| `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/utils.py` | Shared create/resync helpers that apply the default wait and the `--parallel` opt-out, and print waiting, progress, and ready messages. |
| `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/__init__.py` | Add `--parallel` to `up`; use the create helper. |
| `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/mirror.py` | Add `--parallel` to `create` and `resync`; use the helpers. |
| `examples/cli/README.md` | Document default serial processing, `--parallel`, and the drop behaviour. |
| `tests/peerdb/test_peerdb.py` | Offline tests for readiness and resync-start waits. |

## Design decisions

### D1: Serial by default, `--parallel` opt-out

**Decision.** Serial processing is the default for `peerdb up`, `mirror create`, and `mirror resync`. `--parallel` disables the wait for a run. There is no YAML setting or environment variable.

**Rationale.** Serial processing is the safer default because it protects source databases from concurrent snapshots. Parallel processing is an explicit speed trade-off. A CLI flag avoids changing the config schema and keeps both behaviours available without a second default.

**Consequences.** Default commands now block until each mirror is ready; scripts that relied on the previous non-waiting behaviour must pass `--parallel`. Operators choose the behaviour per run.

### D2: Wait for STATUS_RUNNING or STATUS_COMPLETED

**Decision.** A mirror is ready when its flow state is `STATUS_RUNNING` or `STATUS_COMPLETED`.

**Rationale.** PeerDB sets `STATUS_RUNNING` after setup and the initial snapshot for normal CDC mirrors, and `STATUS_COMPLETED` when `initial_snapshot_only` is enabled. Treating either as ready covers both mirror shapes without inspecting snapshot details.

**Consequences.** The wait does not distinguish between a mirror that is running CDC and one that has finished its only snapshot; both are safe points to start the next mirror. For resync, a completed or failed mirror is recreated first, and the wait applies to the recreated flow.

### D3: Fail fast on failure states

**Decision.** `wait_for_mirror_ready()` raises `MirrorFailedException` on `STATUS_FAILED`, `STATUS_TERMINATED`, or `STATUS_TERMINATING`, and wraps `MirrorNotFoundException` when the mirror disappears.

**Rationale.** Continuing the series after a failure would start more source load without producing a working mirror. For a create wait, `STATUS_TERMINATING` means the mirror is being removed and will never become ready.

**Consequences.** The CLI stops at the first failure and leaves already-created mirrors in place for inspection. The operator can fix the problem and rerun with `if_exists=keep` or `replace`. A completed/failed resync may transiently terminate the old flow during recreation; the client starts waiting only after the recreate request returns, so it does not treat that transient state as a failure.

### D4: No readiness timeout; bounded resync start

**Decision.** The readiness wait has no timeout and polls until the mirror becomes ready, fails, or disappears. The resync start wait is bounded by `config.resync_start_timeout` (default 15 minutes) and accepts the recreated flow's `STATUS_SETUP`/`STATUS_SNAPSHOT`/`STATUS_COMPLETED`, or `STATUS_RUNNING` after a non-initial status. A mirror already in `STATUS_SETUP` or `STATUS_SNAPSHOT` must first be observed in `STATUS_RESYNC`. A completed/failed resync returns from `resync_mirror()` after PeerDB recreates the flow, before the readiness wait starts.

**Rationale.** Initial snapshots can run for hours; the existing `operation_timeout` defaults to 15 seconds and is unsuitable. A finite timeout would either be too short for large tables or arbitrarily large. A resync start, however, should be observable quickly. Waiting only for `STATUS_RESYNC` is unsafe: it is transient and a failed drop can leave it in place forever. The bounded start phase detects a signal that was never processed or a failed drop without limiting the snapshot wait.

**Consequences.** A stalled snapshot blocks the CLI indefinitely. Ctrl-C is the escape hatch. A stalled resync start fails after `resync_start_timeout` with a clear error. The timeout is configurable in YAML; a future CLI flag could expose it.

### D5: Global behaviour

**Decision.** Serial processing and parallel mode apply to all mirrors across all source peers.

**Rationale.** A global rule is simplest to reason about and conserves every source database. Parallel mode is also global so that `--parallel` has one meaning.

**Consequences.** By default, mirrors on unrelated sources wait for each other. Pass `--parallel` when independent sources should run concurrently. Per-source grouping can be added later.

### D6: Skip kept mirrors

**Decision.** In serial processing, a mirror kept by `if_exists=keep` is not waited on.

**Rationale.** No new workflow is started for a kept mirror, and the existing mirror may be paused, failed, or already running. Waiting could hang or produce a misleading failure.

**Consequences.** A kept mirror that is still mid-snapshot from a previous interrupted run is not waited on, so its snapshot can overlap the next mirror's snapshot. Use `if_exists=replace` for a guaranteed fresh serial run.

### D7: Drop remains unchanged

**Decision.** `mirror drop` gets no `--parallel` flag. It continues to drop mirrors one at a time and waits up to `operation_timeout` for each flow to disappear.

**Rationale.** `drop_mirror()` already blocks until PeerDB removes the flow (or the timeout expires), and PeerDB's `DropFlowWorkflow` drops the source slot/publication before removing the flow row. A flag would not change behaviour.

**Consequences.** The CLI surface stays smaller. The README explains that drops already wait, subject to `operation_timeout`.

### D8: Single mirror waits by default

**Decision.** Without `--parallel`, `mirror create <name>` and `mirror resync <name>` wait for that mirror to become ready. With `--parallel`, they return as soon as PeerDB accepts the operation. `resync_mirror(..., wait=False)` skips the resync start wait.

**Rationale.** Applying the default uniformly is easier to explain than silently ignoring it for a single mirror. It also gives operators a way to block until a specific mirror is ready.

**Consequences.** `mirror create cdc_one` waits for the initial load, while `mirror create cdc_one --parallel` returns as soon as PeerDB accepts the flow. `mirror resync cdc_one --parallel` returns after the request, while `mirror resync cdc_one` waits for the resync to start and then for the mirror to become ready.

### D9: Recreated resyncs skip the resync start wait

**Decision.** When the mirror is `STATUS_COMPLETED` or `STATUS_FAILED`, `resync_mirror()` does not wait for the resync start. PeerDB recreates the flow synchronously, and the CLI waits for the recreated flow to become ready in serial mode.

**Rationale.** The recreate path returns after the new flow has started; its new flow starts at `STATUS_SETUP` and only reaches `STATUS_RESYNC` after the snapshot. Waiting for the start would be redundant, and waiting for `STATUS_RESYNC` would block until the snapshot finishes.

**Consequences.** Serial resync waits for the recreated flow's readiness; parallel resync returns after the recreate request. A terminated or terminating mirror is rejected before the request because PeerDB cannot resync it.

### D10: Retry transient status errors

**Decision.** The long waits retry `GetMirrorStatusException` and `requests.RequestException` with exponential backoff, capped at the poll interval. The readiness wait backs off to `status_poll_max_interval` (default 15s); the resync start wait stays at `status_poll_interval` (default 1s) to catch the transition. Both waits fail after `status_error_window` (default 10 minutes) of consecutive status-query failures; the start wait is also bounded by its deadline. `ReadTimeout` is wrapped in `GetMirrorStatusException` by `get_mirror_status()`.

**Rationale.** A single 5-second read timeout or a PeerDB restart should not abort an hours-long run. A sustained outage should fail rather than hang.

**Consequences.** Transient errors are invisible apart from the delay; sustained errors abort with the last status-query error.

### D11: Report progress

**Decision.** `wait_for_mirror_ready()` and `wait_for_mirror_resync_started()` accept an optional callback invoked on status changes and every `status_heartbeat_interval` (default five minutes) while the status is unchanged. The CLI prints status and elapsed time.

**Rationale.** A multi-hour snapshot otherwise produces no output after the initial waiting message. Operators need to distinguish progress from a stuck mirror.

**Consequences.** The library remains silent by default; the CLI supplies the printer.

### D12: Unknown status grace

**Decision.** `wait_for_mirror_ready()` treats `STATUS_UNKNOWN` as a failure after `status_unknown_grace` (default 60 seconds). `wait_for_mirror_resync_started()` lets its deadline handle `STATUS_UNKNOWN`.

**Rationale.** Normal flows are inserted as `STATUS_SETUP`; a persistent `STATUS_UNKNOWN` means the catalog row is legacy or broken. `has_mirror()` already treats `STATUS_UNKNOWN` as absent.

**Consequences.** Legacy unknown rows fail with a clear error instead of hanging the readiness wait.

### D13: Wait settings are configurable

**Decision.** `Config` exposes `resync_start_timeout`, `status_poll_interval`, `status_poll_max_interval`, `status_error_window`, `status_heartbeat_interval`, and `status_unknown_grace`. Missing YAML keys use the module constants. `status_poll_max_interval` must be greater than or equal to `status_poll_interval`.

**Rationale.** Operators need to tune waits per environment without code changes. Keeping the module constants as defaults preserves current behaviour and matches `operation_timeout`.

**Consequences.** `status_poll_interval` also sets the fixed resync-start poll interval; increasing it may make the transient `STATUS_RESYNC` window easier to miss, so the default 1s is recommended. `status_unknown_grace` applies to the readiness wait only; the resync start wait keeps its deadline behaviour.

## Alternatives considered

| Alternative | Why rejected |
|-------------|--------------|
| Keep `--serial` as an opt-in flag | Serial processing is now the default; an opt-in flag would be redundant and the default would remain unsafe. |
| YAML `parallel: true` setting | The requested interface is a CLI flag; a config setting would require schema and test changes and would make the behaviour easy to forget. |
| Per-source serialization | Global behaviour was requested; grouping adds complexity for no immediate benefit. |
| Reuse `wait_for_mirror_status()` with a very large timeout | Still finite, and the existing method does not fail fast on `STATUS_FAILED`; a dedicated method keeps the no-timeout and failure semantics explicit. |
| Wait only for `STATUS_RESYNC` | It is transient; a missed window can block for the whole snapshot, and a failed drop can leave it forever. |
| Unbounded resync start wait | A signal that is never processed or a failed drop would hang the CLI forever. |
| Fixed 1s polling for the readiness wait | Wasteful over hours; backoff keeps detection within seconds while reducing load. |
| Wait for `STATUS_RESYNC` for completed/failed resyncs | PeerDB only sets it after the snapshot, so the wait would time out before the snapshot finishes. |
| Sleep between creates | A fixed delay does not guarantee that the previous snapshot has finished and wastes time when it has. |
| Add `--parallel` to `mirror drop` | Drop already waits for PeerDB to finish; the flag would be redundant. |
| Server-side concurrency limit | PeerDB v0.37.10 has no cross-mirror concurrency setting; changing the server is out of scope. |

## Test strategy

| Layer | Scope | Examples |
|-------|-------|----------|
| Unit | `wait_for_mirror_ready()` status handling with monkeypatched `get_mirror_status()` and `time.sleep()` | `STATUS_SNAPSHOT` → `STATUS_RUNNING`; `STATUS_SETUP` → `STATUS_COMPLETED`; `STATUS_FAILED` raises; `STATUS_TERMINATED` raises; `MirrorNotFoundException` raises; transient errors are retried; `STATUS_UNKNOWN` raises after the grace period; callback reports changes and heartbeats. |
| Unit | No-timeout behaviour | A long sequence of `STATUS_SNAPSHOT` responses still returns when `STATUS_RUNNING` appears; `wait_for_mirror_status(timeout=None)` returns when its target appears; no timeout exception is raised. |
| Unit | `wait_for_mirror_resync_started()` with a fake clock | `RUNNING` → `SETUP` accepted; `RESYNC` → `SETUP`/`SNAPSHOT` accepted; `RUNNING` unchanged raises after timeout; stuck `RESYNC` raises; failure/disappearance raises; initial `SETUP` requires `RESYNC`; completed/failed skip. |
| Unit | `resync_mirror()` wait paths with monkeypatched `get_mirror_status()`, `requests.post()`, and `wait_for_mirror_resync_started()` | Running mirror waits for the start; completed/failed mirror does not; `wait=False` returns after the request; terminated mirror is rejected; missing mirror with `if_exists=True` is skipped. |
| Unit | `get_mirror_status()` error wrapping | `requests.ReadTimeout` raises `GetMirrorStatusException`. |
| Unit | Config wait settings | Defaults match the module constants; overrides are accepted; `status_poll_max_interval < status_poll_interval` raises; both wait methods pass configured values to the poller. |
| Integration | Example stack with two configured mirrors | `cli peerdb up` creates `cdc_one`, waits for it to be ready, then creates `cdc_many`; `cli peerdb up --parallel` starts both before either is ready. The PeerDB UI shows the expected order. |
| Integration | Resync of completed/failed mirror | A snapshot-only or failed mirror is resynced and becomes ready without hitting the resync-start timeout. |
| Regression | Existing tests | `uv run --frozen pytest tests/peerdb` and `uv run --frozen ruff check --config pyproject.toml`. |

## References

- `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/__init__.py`
- `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/mirror.py`
- `src/dw_lib/peerdb.py`
- `tests/peerdb/test_peerdb.py`
- `vendor/peerdb/flow/cmd/handler.go`
- `vendor/peerdb/flow/workflows/cdc_flow.go`
- `vendor/peerdb/flow/workflows/cdc_state/state.go`
- `vendor/peerdb/flow/workflows/drop_flow.go`
- `vendor/peerdb/protos/flow.proto` (`FlowStatus`)
