# PeerDB Mirror Wait Design

> **Status:** Last updated 2026-10-24.

## Context

The PeerDB CLI creates and resyncs mirrors from the example CLI in `examples/cli/packages/example_cli/src/example_cli/peerdb_cli`. Today, `mirror create` returns as soon as PeerDB returns a `workflowId` (`src/dw_lib/peerdb.py:2143`; CLI loop at `mirror.py:27`). `mirror create --all` therefore starts every initial snapshot concurrently. On a source database with 100+ GB tables and many mirrors, that can overload the source.

`mirror resync` is different. It waits for `STATUS_RESYNC` (`src/dw_lib/peerdb.py:2365`), but that status is ambiguous. PeerDB sets it in two places:

1. **Before the new snapshot starts.** A resync makes the CDC workflow continue-as-new into `DropFlowWorkflow(Resync=true)`, which sets the catalog status to `STATUS_RESYNC` during cleanup (`vendor/peerdb/flow/workflows/drop_flow.go:137`, `:183`).
2. **After the snapshot finishes.** The new CDC run sets `STATUS_SNAPSHOT`, runs the snapshot, then sets `STATUS_RESYNC` again immediately before `RenameTables` (`vendor/peerdb/flow/workflows/cdc_flow.go:729`, `:774`).

`get_mirror_status` reads the catalog status (`vendor/peerdb/flow/internal/workflow.go:19`), so the CLI cannot distinguish the two. The PeerDB e2e test confirms the first meaning: “Wait until DropFlowWorkflow has started (catalog status = RESYNC)” (`vendor/peerdb/flow/e2e/drop_flow_test.go:75-84`). The unambiguous completion states are `STATUS_RUNNING` for normal CDC mirrors and `STATUS_COMPLETED` for initial-snapshot-only mirrors (`vendor/peerdb/flow/workflows/cdc_flow.go:837`, `:840`). PeerDB's own resync tests wait for `STATUS_RUNNING` (`vendor/peerdb/flow/e2e/api_test.go:1743`).

The `client.mirror_resync_start_wait_timeout_seconds` default is 30 seconds (`src/dw_lib/peerdb.py:98`). It bounds only the resync start guard, not the snapshot completion wait.

## Goals

1. Add `--wait` and `--no-wait` to `mirror create`, `mirror resync`, and `up`.
2. Make `--wait` wait for snapshot completion: `STATUS_RUNNING` or `STATUS_COMPLETED`.
3. Make `--wait` work for a single named mirror and for `--all`, with `--all --wait` sequential.
4. Preserve existing behaviour under `--no-wait`, which is the default.
5. Handle resyncs that complete before an intermediate status is observed.
6. Avoid adding a new wait timeout or configuration key.

## Non-goals

- No `wait_timeout` configuration field and no `--timeout` CLI option.
- No `--max-concurrent` or concurrency-pool option.
- No changes to the PeerDB API or to the vendored PeerDB source.
- No changes to pause, resume, drop, peer, or debug commands.
- No changes to per-mirror snapshot parallelism settings such as `snapshot_num_tables_in_parallel`.
- No protection against two separate CLI invocations running at the same time.
- No change to `--if-exists` semantics.

## Terminology

| Term | Meaning |
|------|---------|
| Snapshot completion | The mirror reaches `STATUS_RUNNING` for a normal CDC mirror, or `STATUS_COMPLETED` for an initial-snapshot-only mirror. |
| Wait mode | `--wait` on `mirror create`, `mirror resync`, or `up`. |
| No-wait mode | `--no-wait`, or the default when neither flag is given. |
| Resync initiation | The mirror reaches `STATUS_RESYNC`, which is the existing `mirror resync` wait condition. It does not guarantee that the resync snapshot has finished. |
| Start transition | After a resync request, the mirror leaves its pre-request state and enters `STATUS_SETUP`, `STATUS_SNAPSHOT`, or `STATUS_RESYNC`. |
| Fast-resync fallback | If the start transition is not observed within the existing operation timeout and the mirror is `STATUS_RUNNING` or `STATUS_COMPLETED`, the wait treats the resync as complete. |
| Mirror resync start wait timeout | The `client.mirror_resync_start_wait_timeout_seconds` config, used for the resync start guard and fast-resync fallback. |

## Architecture

The CLI passes the wait mode to the library, which owns the polling logic:

```text
mirror create --wait
  -> PeerDB.create_mirror(wait=True)
       -> POST /v1/flows/cdc/create
       -> PeerDB.wait_for_mirror_snapshot()
            -> _poll_mirror_status(RUNNING, COMPLETED, timeout=None)

mirror create --no-wait
  -> PeerDB.create_mirror(wait=False)
       -> POST /v1/flows/cdc/create
       -> return

mirror resync --wait
  -> PeerDB.resync_mirror(wait=True)
       -> get_mirror_status()                  # initial status
       -> POST /v1/mirrors/state_change (RESYNC)
       -> if initial status is RUNNING:
            wait for SETUP, SNAPSHOT, or RESYNC for `client.mirror_resync_start_wait_timeout_seconds`
            on timeout: fast-resync fallback check
       -> _poll_mirror_status(RUNNING, COMPLETED, timeout=None)

mirror resync --no-wait
  -> PeerDB.resync_mirror(wait=False)
       -> POST /v1/mirrors/state_change (RESYNC)
       -> wait for STATUS_RESYNC
       -> return
```

Status sequences:

```text
create:                 SETUP -> SNAPSHOT -> RUNNING
create snapshot-only:   SETUP -> SNAPSHOT -> COMPLETED
resync from RUNNING:    RUNNING -> RESYNC (cleanup) -> SETUP -> SNAPSHOT -> RESYNC (post-snapshot) -> RUNNING
resync from SNAPSHOT:   SNAPSHOT -> RESYNC (cleanup) -> SETUP -> SNAPSHOT -> RESYNC (post-snapshot) -> RUNNING
```

The wait uses `STATUS_RUNNING` and `STATUS_COMPLETED`, not `STATUS_RESYNC`. For resync from `RUNNING`, the initial status guard prevents the pre-resync `RUNNING` from being mistaken for completion. For resyncs starting in any other status, the completion wait naturally spans the resync.

`up --wait` runs settings, peers, and mirrors in order. Each mirror is created with `wait=True`, so the mirror loop is sequential. `up --no-wait` preserves the current behaviour.

## Code layout

| Module | Responsibility |
|--------|----------------|
| `src/dw_lib/exceptions.py` | Add `MirrorFailedException`. |
| `src/dw_lib/peerdb.py` | Add `_poll_mirror_status`, extend `wait_for_mirror_status` with `fail_statuses`, add `wait_for_mirror_snapshot`, add `wait` to `create_mirror` and `resync_mirror`. |
| `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/mirror.py` | Add `--wait/--no-wait` to `create` and `resync`. |
| `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/__init__.py` | Add `--wait/--no-wait` to `up`. |
| `docs/peerdb-cli.md` | Update command reference, blocking table, and safety notes. |
| `tests/peerdb/test_wait.py` | Offline unit tests for wait sequences and the fast-resync fallback. |
| `tests/peerdb/test_postgres.py` | Integration coverage for Postgres destinations. |
| `tests/peerdb/test_clickhouse.py` | Integration coverage for ClickHouse destinations. |

## Design decisions

### D1: Wait for snapshot completion, not `STATUS_RESYNC`

**Decision.** Wait mode waits for `STATUS_RUNNING` or `STATUS_COMPLETED`.

**Rationale.** `STATUS_RESYNC` is set during resync cleanup before the new snapshot starts and again after the snapshot finishes. Waiting for it alone can return before the snapshot has begun. `STATUS_RUNNING` and `STATUS_COMPLETED` are unambiguous completion states.

**Consequences.** Wait mode also waits through the destination rename. The rename is small compared with a 100+ GB snapshot, and the stronger barrier removes the ambiguity. `--no-wait` keeps the existing `STATUS_RESYNC` wait for compatibility.

### D2: Default to no-wait

**Decision.** `mirror create`, `mirror resync`, and `up` default to `--no-wait`.

**Rationale.** This preserves existing behaviour and keeps commands fast unless waiting is requested explicitly. No-wait remains the default for both create and resync.

**Consequences.** Users must pass `--wait` to serialise snapshots. `--all` without `--wait` can still start concurrent snapshots.

### D3: Two-phase status polling with a fast-resync fallback

**Decision.** For resync in wait mode, capture the initial status before sending the request. If it is `STATUS_RUNNING`, wait up to `client.mirror_resync_start_wait_timeout_seconds` for a start transition to `STATUS_SETUP`, `STATUS_SNAPSHOT`, or `STATUS_RESYNC`. If the guard times out and the current status is `STATUS_RUNNING` or `STATUS_COMPLETED`, accept it as the fast-resync fallback. Then poll indefinitely for `STATUS_RUNNING` or `STATUS_COMPLETED`.

**Rationale.** The start guard prevents the pre-resync `STATUS_RUNNING` from being treated as completion. The fallback handles resyncs that finish before the transition is observed. The existing operation timeout is sufficient for the start guard because the workflow processes the resync signal quickly.

**Consequences.** A resync that completes faster than the polling interval may be detected only by the fallback. A resync signal delayed beyond `client.mirror_resync_start_wait_timeout_seconds` while the mirror remains `STATUS_RUNNING` could be treated as complete prematurely. Large snapshots are unaffected because the start transition remains visible for a long time.

### D4: No new wait timeout

**Decision.** The snapshot-completion wait has no timeout. Within wait mode, the existing `client.mirror_resync_start_wait_timeout_seconds` is used only for the start guard.

**Rationale.** Large snapshots can take hours, so any fixed wait timeout would cause false failures. A new wait timeout and a `--timeout` option are therefore excluded.

**Consequences.** `--wait` can block indefinitely; Ctrl-C is the escape hatch. The start guard still uses `client.mirror_resync_start_wait_timeout_seconds`, but it is not a snapshot wait timeout.

### D5: Failure and paused semantics

**Decision.** Fail on `STATUS_FAILED` and `STATUS_TERMINATED`. Treat `STATUS_PAUSED` and `STATUS_PAUSING` as not complete.

**Rationale.** A failed or terminated mirror cannot complete. A paused mirror is not running and should not be reported as snapshot-complete.

**Consequences.** `--wait` blocks on a paused mirror until it is resumed, fails, or is terminated. This is documented in the CLI reference.

### D6: Encapsulate wait logic in the library

**Decision.** Add a `wait` parameter to `create_mirror` and `resync_mirror`. Add `wait_for_mirror_snapshot`. Refactor polling into `_poll_mirror_status` with an optional timeout and fail statuses. Add `MirrorFailedException`. `resync_mirror(wait=False)` keeps the `STATUS_RESYNC` wait and uses `client.mirror_resync_start_wait_timeout_seconds`. `resync_mirror(wait=True)` returns the message `Resynced mirror 'x'`; wait mode reports completion, no-wait mode keeps `Resync of mirror 'x' has been initiated`.

**Rationale.** The CLI should only translate flags into library calls. Keeping the polling and fallback logic in the library makes it reusable and testable. Defaulting `wait` to `False` preserves existing library behaviour.

**Consequences.** `wait=True` makes the methods long-running. `wait_for_mirror_snapshot` prints a progress line before polling. No snapshot wait timeout is added; client timeouts live in `ClientConfig`.

### D7: Wait scope is independent of `--all`

**Decision.** `--wait` applies to a single named mirror and to every mirror when `--all` is used. `--all --wait` is sequential because the CLI waits inside the loop.

**Rationale.** `--wait` should mean the same thing regardless of scope. Making the flag scope-dependent would be surprising.

**Consequences.** `mirror create NAME --wait` and `mirror resync NAME --wait` wait for one mirror. `--all --wait` waits for each mirror in turn. `--all --no-wait` keeps the current concurrent-snapshot behaviour.

## Alternatives considered

| Alternative | Why rejected |
|-------------|--------------|
| Wait for `STATUS_RESYNC` in wait mode | Ambiguous: set during cleanup before the snapshot and again after the snapshot. |
| Use PeerDB's `InitialLoadSummary` snapshot status | Deterministic, but adds a new API method and models. Option A is sufficient for large tables; keep as a future option if fast resyncs need deterministic detection. |
| Fixed delay between mirror creations | Unreliable; does not guarantee the previous snapshot has finished. |
| Add a resync generation or run ID to the PeerDB API | Requires an upstream PeerDB change; out of scope. |
| Add `wait_timeout` and `--timeout` | Large snapshots need indefinite waits; a fixed timeout would cause false failures. |
| Default `--wait` for `--all` | No-wait remains the default for create and resync to preserve existing behaviour. |
| Add `--max-concurrent N` | More flexible but more complex; sequential `--all --wait` covers the stated need. |
| Wait for post-snapshot `STATUS_RESYNC` instead of `RUNNING`/`COMPLETED` | Returns earlier but requires distinguishing two `STATUS_RESYNC` phases; `RUNNING`/`COMPLETED` is the chosen completion signal. |

## Test strategy

| Layer | Scope | Examples |
|-------|-------|----------|
| Unit (offline) | Wait sequences with mocked status responses | Create normal and snapshot-only; resync from `RUNNING` and `SNAPSHOT`; fast-resync fallback; failure; paused mirror; no timeout. |
| Integration (Docker) | Real PeerDB API | `create_mirror(wait=True)` reaches `RUNNING`; `resync_mirror(wait=True)` reaches `RUNNING`; `resync_mirror(wait=False)` returns at `STATUS_RESYNC`. |
| CLI (manual) | Flag parsing and `--all` ordering | `mirror create --all --wait`, `mirror resync --all --wait`, `--no-wait` defaults. |
| Static | Lint and formatting | `make lint`. |

Unit tests should monkeypatch `get_mirror_status` and `time.sleep` so they run without PeerDB. The completion wait has no timeout; verify that a long `STATUS_SNAPSHOT` sequence still completes.

## References

- Feature specification: `docs/plans/peerdb-mirror-wait/spec.md`
- CLI behaviour documentation: `docs/peerdb-cli.md`
- Current wait implementation: `src/dw_lib/peerdb.py:1935`
- Current create implementation: `src/dw_lib/peerdb.py:2143`
- Current resync implementation: `src/dw_lib/peerdb.py:2365`
- CLI mirror commands: `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/mirror.py:15`, `:106`
- CLI `up` command: `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/__init__.py:27`
- PeerDB resync cleanup status: `vendor/peerdb/flow/workflows/drop_flow.go:137`, `:183`
- PeerDB snapshot and completion statuses: `vendor/peerdb/flow/workflows/cdc_flow.go:729`, `:774`, `:837`, `:840`
- PeerDB catalog status query: `vendor/peerdb/flow/internal/workflow.go:19`
- PeerDB resync e2e evidence: `vendor/peerdb/flow/e2e/drop_flow_test.go:75-84`, `vendor/peerdb/flow/e2e/api_test.go:1743`
- AGENTS.md, PeerDB dependency management
