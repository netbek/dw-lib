# PeerDB Serial Mirror Operations Design

> **Status:** Last updated 2026-10-24.

## Context

The CLI currently processes multiple mirrors with simple loops. `create_mirror` and `resync_mirror` return after PeerDB accepts the request and starts the workflow, not after the snapshot or resync finishes. A loop that calls them one after another therefore still starts every snapshot almost immediately in the background.

This matters for large sources. At 500GB–1TB, partition discovery and the initial copy can take hours to tens of hours. Resync repeats the full snapshot, and Postgres destinations can add a soft-delete anti-join during the rename. The existing timeout design records this in `docs/plans/peerdb-client-timeouts/design.md` under “Long-running operations (500GB–1TB)”.

`drop_mirror`, `pause_mirror`, and `resume_mirror` already wait for their target states and use the existing configured timeouts. `drop_mirrors_of_peer` already loops over dependent mirrors serially.

This change adds no new timeout parameters, CLI flags, or configuration settings.

## Goals

1. Make every multi-mirror operation process mirrors one at a time.
2. Make serial create and resync wait for each mirror to settle before starting the next.
3. Preserve the existing configured timeouts for drop, pause, and resume.
4. Preserve single-mirror behaviour.
5. Fail fast without rolling back completed work.

## Non-goals

- Adding a parallel execution mode.
- Adding new timeout parameters, CLI flags, or configuration settings.
- Changing PeerDB server-side validation, workflow, or timeout behaviour.
- Cancelling server-side workflows when a client wait times out.
- Adding waits to single-mirror create or resync calls.
- Changing peer creation when the peer is not being replaced.
- Reworking shared publications, replication slots, or destination tables.

## Terminology

| Term | Meaning |
|---|---|
| Serial batch | A multi-mirror operation that processes one mirror at a time. |
| Settled state | `STATUS_RUNNING`, `STATUS_PAUSED`, or `STATUS_COMPLETED`. |
| Terminal failure state | `STATUS_FAILED` or `STATUS_TERMINATED`. |
| Configured wait timeout | The existing `mirror_*_wait_timeout_seconds` client settings. |
| Multi-mirror operation | Create, drop, pause, resume, or resync over several mirrors; peer drop; peer replace; `peerdb up`. |

## Architecture

### Serial batch methods

Add these methods to `PeerDB`:

```python
create_mirrors(mirrors, *, if_exists="fail") -> list[CreateMirrorResponse]
drop_mirrors(names, *, drop_destination_tables=False, if_exists=False) -> list[DropMirrorResponse]
pause_mirrors(names) -> list[PauseMirrorResponse]
resume_mirrors(names) -> list[ResumeMirrorResponse]
resync_mirrors(names, *, if_exists=False) -> list[ResyncMirrorResponse]
```

Each method loops over its input in order and returns responses in the same order.

- `create_mirrors` calls `create_mirror`, then `wait_for_mirror_settled`.
- `resync_mirrors` calls `resync_mirror`, then `wait_for_mirror_settled`.
- `drop_mirrors` calls `drop_mirror`, which already waits for the mirror to disappear.
- `pause_mirrors` calls `pause_mirror`, which already waits for `STATUS_PAUSED`.
- `resume_mirrors` calls `resume_mirror`, which already waits for `STATUS_RUNNING`.

### Settle wait

Add `wait_for_mirror_settled(flow_job_name)`.

It polls `get_mirror_status` until the mirror reaches a settled state. It raises `MirrorTerminalStateException` on a terminal failure state. It has no completion deadline.

### No-deadline polling

Extend the internal `_poll_mirror_status` helper so its timeout argument accepts `None` as “no deadline”. The public `wait_for_mirror_status` keeps its current contract: `None` means use `config.client.mirror_status_wait_timeout_seconds`.

The poll loop keeps the existing terminal-state fail-fast and transient-error retry behaviour. Without a deadline, a persistent status error retries indefinitely; the caller can interrupt the process.

### Existing configured timeouts

| Operation | Wait behaviour |
|---|---|
| Create or resync completion | No deadline |
| Resync initiation | Uses `mirror_resync_wait_timeout_seconds` |
| Drop | Uses `mirror_drop_wait_timeout_seconds` |
| Pause | Uses `mirror_pause_wait_timeout_seconds` |
| Resume | Uses `mirror_resume_wait_timeout_seconds` |
| Create with `if_exists="replace"` | Uses `mirror_drop_wait_timeout_seconds` for the old mirror |
| Public status wait | Uses `mirror_status_wait_timeout_seconds`, unchanged |

No new timeout option is exposed by the batch methods or CLI.

### Peer operations

- `drop_mirrors_of_peer` selects dependent mirrors and passes them to `drop_mirrors`.
- `drop_peer` keeps its existing signature and inherits the configured drop timeout.
- `create_peer(if_exists="replace")` keeps using `drop_peer`; it inherits serial behaviour and the configured drop timeout.

### CLI

Add no new options.

- `mirror create --all`, `drop --all`, `pause --all`, `resume --all`, and `resync --all` call the batch methods.
- `peer drop --all` continues to call `drop_peer`, which drops dependent mirrors serially.
- `peerdb up` calls `create_mirrors` after creating peers.
- Single-mirror commands keep their current behaviour.

The underlying single-mirror methods print their progress messages as the batch runs. The CLI prints the returned response messages after the batch returns. On failure, it prints the error and exits with a non-zero status. A long create or resync batch can be interrupted with Ctrl-C.

### Ordering

- `create_mirrors` preserves the input order, which is the YAML configuration order.
- Server-list commands use the order returned by `list_mirrors`, which is sorted by name.

### Missing mirrors

- `drop_mirrors(if_exists=True)` skips a mirror that is already gone.
- `resync_mirrors(if_exists=True)` skips a mirror that is already gone.
- `create_mirrors(if_exists="keep")` still waits for an existing mirror to settle. If that mirror is failed or terminated, the batch fails fast.

## Code layout

| Module | Responsibility |
|---|---|
| `src/dw_lib/peerdb.py` | Serial batch methods, `wait_for_mirror_settled`, no-deadline polling, peer integration. |
| `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/mirror.py` | Use batch methods for `--all` commands; keep the existing option set. |
| `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/__init__.py` | Use `create_mirrors` in `peerdb up`. |
| `tests/peerdb/test_serial_batches.py` | Serial order, settle waits including the no-deadline path, and failure behaviour. |
| `tests/peerdb/test_timeouts.py` | Existing configured waits and peer drop delegation. |
| `examples/cli/README.md` | Document the `peerdb up` behaviour change. |

## Design decisions

### D1: Serial is the only mode

**Decision.** Do not add a `mode` parameter, worker count, thread pool, or parallel execution path. Multi-mirror operations always run serially.

**Rationale.** Serial execution avoids overlapping snapshots, limits source and destination load, and reduces concurrent WAL accumulation. The user explicitly excluded parallel mode.

**Consequences.** A batch of many large mirrors takes the sum of their snapshot times. Callers who want concurrency must orchestrate separate processes.

### D2: Wait for a settled state after create and resync

**Decision.** `create_mirrors` and `resync_mirrors` wait for `STATUS_RUNNING`, `STATUS_PAUSED`, or `STATUS_COMPLETED` before starting the next mirror.

**Rationale.** `create_mirror` and `resync_mirror` return after workflow start. Without an explicit wait, a serial loop still launches all snapshots at once. `STATUS_PAUSED` is settled because a paused mirror is not doing snapshot work.

**Consequences.** Serial create and resync become long-running commands. That is the intended trade-off for large sources.

### D3: No completion deadline for create and resync

**Decision.** Create and resync completion waits have no deadline.

**Rationale.** A 500GB–1TB snapshot can take hours to tens of hours. Any fixed default is either too short for large sources or too long for failures. Terminal states still stop the wait immediately.

**Consequences.** A stuck mirror can block a batch indefinitely. Callers can interrupt the process. A later requirement can add a configurable deadline if needed.

### D4: Keep the existing configured timeouts for drop, pause, and resume

**Decision.** Drop, pause, and resume continue to use `mirror_drop_wait_timeout_seconds`, `mirror_pause_wait_timeout_seconds`, and `mirror_resume_wait_timeout_seconds`.

**Rationale.** These operations normally finish quickly, and the existing settings already bound them. Reusing them avoids new configuration surface.

**Consequences.** A drop that blocks on replication-slot cleanup can still time out. The timeout does not cancel server-side cleanup; a later retry may find the mirror gone.

### D5: No new timeout options

**Decision.** Do not add timeout parameters to the batch methods, do not add a CLI `--timeout` flag, and do not add a new configuration setting.

**Rationale.** Snapshot duration is unpredictable, and the existing configuration already covers the control-plane waits. A per-call timeout would add API and CLI surface with subtle semantics: it would be per mirror, per wait, and would not cancel server-side work.

**Consequences.** Create and resync batches can wait indefinitely. Users interrupt the process or apply an external process timeout. If a bound becomes necessary, add one configuration setting rather than duplicating it across the library and CLI.

### D6: Fail fast

**Decision.** A serial batch stops at the first error and propagates that error. It does not collect errors or continue with later mirrors.

**Rationale.** Stopping avoids starting more long-running work after a failure. The underlying exceptions already identify the mirror.

**Consequences.** Earlier mirrors remain in their completed state. Rerunning is safe for create with `if_exists="keep"`, drop with `if_exists=True`, and resync.

### D7: Library batch methods, CLI as a thin wrapper

**Decision.** Put serial execution in `PeerDB` batch methods and have the CLI call them.

**Rationale.** The behaviour belongs to the client library, not only to the example CLI. Programmatic callers get the same guarantees, and the logic is testable without the CLI.

**Consequences.** The library gains five batch methods and one public settle-wait method.

### D8: The CLI keeps its existing option set

**Decision.** Do not add CLI options. The `--all` commands call the batch methods, and single-mirror commands keep their current behaviour.

**Rationale.** The feature changes execution order, not the inputs. Keeping the option set unchanged avoids new flags with unclear timeout semantics.

**Consequences.** A long create or resync batch can be interrupted with Ctrl-C. Users who need a hard bound can use an external process timeout.

### D9: `peerdb up` waits by default

**Decision.** `peerdb up` creates mirrors serially and waits for each to settle.

**Rationale.** `peerdb up` is a multi-mirror create operation and must follow the same serial rule.

**Consequences.** Bootstrap can now take hours on a large source. This is a behaviour change from the current fire-and-forget loop.

### D10: Reuse existing exceptions

**Decision.** Use `MirrorTimeoutException`, `MirrorTerminalStateException`, and `MirrorNotFoundException`. Do not add a batch-specific exception.

**Rationale.** The existing exceptions already include the mirror name and the last observed status where relevant. Fail-fast means there is no aggregate error to report.

**Consequences.** The CLI handles the first error and exits non-zero. No partial-result object is returned.

### D11: Preserve deterministic order

**Decision.** Create batches preserve configuration order. Batches built from the server mirror list use the list's name order.

**Rationale.** Deterministic order makes serial batches predictable and reproducible.

**Consequences.** Reordering the YAML configuration changes create order. Server-list commands follow `list_mirrors` sorting.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Add parallel mode | Excluded by the user. It would multiply source load, WAL accumulation, and destination merge work. |
| Serialise calls without waiting for completion | Does not prevent overlapping snapshots because create and resync return after workflow start. |
| Add per-mirror timeout parameters and CLI flags | Not necessary for the feature. Snapshot duration is unpredictable, and the timeout would not cancel server-side work. |
| Use a fixed default completion timeout | Snapshot duration depends on data volume, throughput, table count, and destination load. No fixed value fits 500GB–1TB. |
| Put the loops only in the CLI | Duplicates logic and gives programmatic callers no serial guarantee. |
| Collect errors and continue | Starts more long-running work after a failure and complicates partial-progress reporting. |
| Add a `mode` parameter that only accepts `serial` | Adds API surface for a choice that does not exist. |
| Cancel the server-side workflow on timeout | Client timeouts cannot reliably cancel PeerDB workflows and would hide the real state. |

## Test strategy

| Layer | Scope | Examples |
|---|---|---|
| Unit (offline) | Serial order | Create, drop, pause, resume, and resync call one mirror at a time. |
| Unit (offline) | Settle waits | Create waits through `SETUP` and `SNAPSHOT`; snapshot-only waits for `COMPLETED`; paused mirror settles at `PAUSED`. |
| Unit (offline) | No completion deadline | A mirror that stays in `SNAPSHOT` beyond the configured status wait timeout is still polled until settled. |
| Unit (offline) | Terminal states | `FAILED` and `TERMINATED` stop the batch; later mirrors are not called. |
| Unit (offline) | Existing configured waits | Drop, pause, and resume still use their configured timeouts and raise `MirrorTimeoutException` when those expire. |
| Unit (offline) | Missing mirrors | `drop_mirrors(if_exists=True)` and `resync_mirrors(if_exists=True)` skip missing mirrors. |
| Unit (offline) | Peer operations | `drop_peer` drops dependent mirrors serially and waits before deleting the peer. |
| Manual (CLI) | Command wiring | `--all` commands call the batch methods; single-mirror commands keep their current behaviour. |
| Integration (Docker) | Real API behaviour | Existing Postgres and ClickHouse mirror tests still pass; a small serial create and drop batch works end to end. |
| Static | Lint and format | Ruff check and format, plus the repository's pre-commit hooks. |

## References

- Client implementation: `src/dw_lib/peerdb.py`
- Existing configured timeouts: `src/dw_lib/peerdb.py:56-89`
- Existing mirror waits: `src/dw_lib/peerdb.py:1229-1377`
- Existing mirror lifecycle methods: `src/dw_lib/peerdb.py:2032-2708`
- Existing peer mirror drop: `src/dw_lib/peerdb.py:1845-1934`
- CLI mirror commands: `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/mirror.py`
- CLI peer commands: `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/peer.py`
- CLI bootstrap: `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/__init__.py`
- Long-running operations research: `docs/plans/peerdb-client-timeouts/design.md`
- PeerDB create returns after workflow start: `vendor/peerdb/flow/cmd/handler.go:158-250`
- Snapshot status and wait: `vendor/peerdb/flow/workflows/cdc_flow.go:729,757-770,840`
- Large-table partition warning: `vendor/peerdb/flow/activities/flowable.go:657-665`
- QRep partition and replication timeouts: `vendor/peerdb/flow/workflows/qrep_flow.go:203,228`
- Postgres resync rename: `vendor/peerdb/flow/connectors/postgres/postgres_destination.go:626-723`
