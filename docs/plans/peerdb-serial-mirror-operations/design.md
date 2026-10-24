# PeerDB Serial Mirror Operations Design

> **Status:** Last updated 2026-10-24.

## Context

The CLI currently processes multiple mirrors with simple loops. `create_mirror` and `resync_mirror` return after PeerDB accepts the request and starts the workflow, not after the snapshot or resync finishes. A loop that calls them one after another therefore still starts every snapshot almost immediately in the background.

This matters for large sources. At 500GB–1TB, partition discovery and the initial copy can take hours to tens of hours. Resync repeats the full snapshot, and Postgres destinations can add a soft-delete anti-join during the rename. The existing timeout design records this in `docs/plans/peerdb-client-timeouts/design.md` under “Long-running operations (500GB–1TB)”.

`drop_mirror`, `pause_mirror`, and `resume_mirror` already wait for their target states. `drop_mirrors_of_peer` already loops over dependent mirrors serially.

## Goals

1. Make every multi-mirror operation process mirrors one at a time.
2. Make serial create and resync wait for each mirror to settle before starting the next.
3. Add an optional per-mirror timeout to the library and the CLI.
4. Preserve single-mirror behaviour.
5. Fail fast without rolling back completed work.

## Non-goals

- Adding a parallel execution mode.
- Changing PeerDB server-side validation, workflow, or timeout behaviour.
- Cancelling server-side workflows when a client timeout expires.
- Adding waits to single-mirror create or resync calls.
- Changing peer creation when the peer is not being replaced.
- Reworking shared publications, replication slots, or destination tables.

## Terminology

| Term | Meaning |
|---|---|
| Serial batch | A multi-mirror operation that processes one mirror at a time. |
| Settled state | `STATUS_RUNNING`, `STATUS_PAUSED`, or `STATUS_COMPLETED`. |
| Terminal failure state | `STATUS_FAILED` or `STATUS_TERMINATED`. |
| Settle timeout | Per-mirror deadline for create or resync completion. |
| Operation timeout | Per-mirror deadline for drop, pause, or resume. |
| Multi-mirror operation | Create, drop, pause, resume, or resync over several mirrors; peer drop; peer replace; `peerdb up`. |

## Architecture

### Serial batch methods

Add these methods to `PeerDB`:

```python
create_mirrors(mirrors, *, if_exists="fail", timeout=None) -> list[CreateMirrorResponse]
drop_mirrors(names, *, drop_destination_tables=False, if_exists=False, timeout=None) -> list[DropMirrorResponse]
pause_mirrors(names, *, timeout=None) -> list[PauseMirrorResponse]
resume_mirrors(names, *, timeout=None) -> list[ResumeMirrorResponse]
resync_mirrors(names, *, if_exists=False, timeout=None) -> list[ResyncMirrorResponse]
```

Each method loops over its input in order and returns responses in the same order.

- `create_mirrors` calls `create_mirror`, then `wait_for_mirror_settled`.
- `resync_mirrors` calls `resync_mirror`, then `wait_for_mirror_settled`.
- `drop_mirrors` calls `drop_mirror`, which already waits for the mirror to disappear.
- `pause_mirrors` calls `pause_mirror`, which already waits for `STATUS_PAUSED`.
- `resume_mirrors` calls `resume_mirror`, which already waits for `STATUS_RUNNING`.

### Settle wait

Add `wait_for_mirror_settled(flow_job_name, timeout=None)`.

It polls `get_mirror_status` until the mirror reaches a settled state. It raises `MirrorTerminalStateException` on a terminal failure state and `MirrorTimeoutException` when a supplied timeout expires. `timeout=None` means no deadline.

### No-deadline polling

Extend `_poll_mirror_status` so `timeout: int | None` accepts `None` as “no deadline”. The public `wait_for_mirror_status` keeps its current contract: `None` means use `config.client.mirror_status_wait_timeout_seconds`.

The poll loop keeps the existing terminal-state fail-fast and transient-error retry behaviour. Without a deadline, a persistent status error retries indefinitely; the caller can interrupt the process.

### Timeout mapping

| Operation | `timeout` supplied | `timeout` omitted |
|---|---|---|
| `create_mirrors` | Bounds each mirror's settle wait | No completion deadline |
| `resync_mirrors` | Bounds the initiation wait and the settle wait separately | Initiation uses the configured default; no completion deadline |
| `drop_mirrors` | Overrides the drop wait | Uses the configured drop wait |
| `pause_mirrors` | Overrides the pause wait | Uses the configured pause wait |
| `resume_mirrors` | Overrides the resume wait | Uses the configured resume wait |

A timeout stops the client wait. It does not cancel the PeerDB workflow.

`create_mirrors` with `if_exists="replace"` first drops the existing mirror using the configured drop timeout. The supplied timeout applies to the settle wait after the new mirror starts.

### Peer operations

- Add `timeout=None` to `drop_mirrors_of_peer` and `drop_peer`.
- `drop_mirrors_of_peer` selects dependent mirrors and passes them to `drop_mirrors`.
- `drop_peer` passes its timeout to `drop_mirrors_of_peer`.
- `create_peer(if_exists="replace")` keeps using `drop_peer`; it inherits serial behaviour and the configured drop timeout.

### CLI

Add `--timeout` to the multi-mirror paths:

| Command | Timeout meaning |
|---|---|
| `mirror create --all` | Per-mirror settle wait |
| `mirror drop --all` | Per-mirror drop wait |
| `mirror pause --all` | Per-mirror pause wait |
| `mirror resume --all` | Per-mirror resume wait |
| `mirror resync --all` | Per-mirror initiation and settle wait |
| `peer drop --all` | Per-mirror drop wait for dependent mirrors |
| `peerdb up` | Per-mirror settle wait for mirror creation |

`--timeout` requires `--all` on `mirror` and `peer` commands. Single-mirror commands do not accept it. `peerdb up` does not use `--all`.

The CLI passes the timeout to the corresponding batch method. When omitted, the batch method applies the defaults in the table above.

The underlying single-mirror methods print their progress messages as the batch runs. The CLI prints the returned response messages after the batch returns. On failure, it prints the error and exits with a non-zero status.

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
| `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/mirror.py` | Use batch methods and add `--timeout` to `--all` commands. |
| `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/peer.py` | Add `--timeout` to `peer drop --all`. |
| `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/__init__.py` | Use `create_mirrors` and add `--timeout` to `peerdb up`. |
| `tests/peerdb/test_serial_batches.py` | Serial order, settle waits, timeouts, and failure behaviour. |
| `tests/peerdb/test_timeouts.py` | No-deadline polling. |
| `examples/cli/README.md` | Document the new option and the bootstrap behaviour change. |

## Design decisions

### D1: Serial is the only mode

**Decision.** Do not add a `mode` parameter, worker count, thread pool, or parallel execution path. Multi-mirror operations always run serially.

**Rationale.** Serial execution avoids overlapping snapshots, limits source and destination load, and reduces concurrent WAL accumulation. The user explicitly excluded parallel mode.

**Consequences.** A batch of many large mirrors takes the sum of their snapshot times. Callers who want concurrency must orchestrate separate processes.

### D2: Wait for a settled state after create and resync

**Decision.** `create_mirrors` and `resync_mirrors` wait for `STATUS_RUNNING`, `STATUS_PAUSED`, or `STATUS_COMPLETED` before starting the next mirror.

**Rationale.** `create_mirror` and `resync_mirror` return after workflow start. Without an explicit wait, a serial loop still launches all snapshots at once. `STATUS_PAUSED` is settled because a paused mirror is not doing snapshot work.

**Consequences.** Serial create and resync become long-running commands. That is the intended trade-off for large sources.

### D3: No completion deadline by default

**Decision.** When `timeout` is omitted, create and resync completion waits have no deadline.

**Rationale.** A 500GB–1TB snapshot can take hours to tens of hours. Any fixed default is either too short for large sources or too long for failures. Terminal states still stop the wait immediately.

**Consequences.** A stuck mirror can block a batch indefinitely. Callers can pass a timeout or interrupt the process.

### D4: Keep control-plane timeouts for drop, pause, and resume

**Decision.** When `timeout` is omitted, drop, pause, and resume use their existing configured wait timeouts. A supplied timeout overrides them.

**Rationale.** These operations normally finish quickly, and the existing defaults already bound them. Keeping the defaults avoids new hangs for control-plane work.

**Consequences.** A drop that blocks on replication-slot cleanup can still time out. The timeout does not cancel server-side cleanup; a later retry may find the mirror gone.

### D5: Fail fast

**Decision.** A serial batch stops at the first error and propagates that error. It does not collect errors or continue with later mirrors.

**Rationale.** Stopping avoids starting more long-running work after a failure. The underlying exceptions already identify the mirror.

**Consequences.** Earlier mirrors remain in their completed state. Rerunning is safe for create with `if_exists="keep"`, drop with `if_exists=True`, and resync.

### D6: Library batch methods, CLI as a thin wrapper

**Decision.** Put serial execution in `PeerDB` batch methods and have the CLI call them.

**Rationale.** The behaviour belongs to the client library, not only to the example CLI. Programmatic callers get the same guarantees, and the logic is testable without the CLI.

**Consequences.** The library gains five batch methods and one public settle-wait method.

### D7: Timeout is per mirror and per wait

**Decision.** The timeout applies to each wait performed for a mirror, not to the whole batch. For resync, the initiation wait and the settle wait are each bounded by the same value.

**Rationale.** Batch duration grows with the number of mirrors, so a total deadline would be arbitrary. Per-wait bounds are predictable and match the existing single-mirror timeout parameters.

**Consequences.** A batch of N mirrors can take up to N times the timeout, plus request time. The CLI help and docs must say the timeout is per mirror.

### D8: CLI timeout is limited to multi-mirror paths

**Decision.** Add `--timeout` only to `mirror ... --all`, `peer drop --all`, and `peerdb up`. Single-mirror commands are unchanged.

**Rationale.** The feature concerns multi-mirror operations. Single-mirror create and resync do not wait for completion, so a timeout there would have no clear meaning without changing existing behaviour.

**Consequences.** Users who need a timeout on a single mirror can call the batch method with one mirror or use the configuration settings.

### D9: `peerdb up` waits by default

**Decision.** `peerdb up` creates mirrors serially and waits for each to settle. `--timeout` bounds each mirror's settle wait.

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
| Unit (offline) | Terminal states | `FAILED` and `TERMINATED` stop the batch; later mirrors are not called. |
| Unit (offline) | Timeouts | Omitted timeout waits without a deadline; supplied timeout raises `MirrorTimeoutException`; drop, pause, and resume use configured defaults when omitted. |
| Unit (offline) | Missing mirrors | `drop_mirrors(if_exists=True)` and `resync_mirrors(if_exists=True)` skip missing mirrors. |
| Unit (offline) | Peer operations | `drop_peer` drops dependent mirrors serially and waits before deleting the peer. |
| CLI (offline) | Option parsing | `--timeout` is accepted with `--all`, rejected without `--all`, rejected on single-mirror commands, and rejects zero or negative values. |
| Integration (Docker) | Real API behaviour | Existing Postgres and ClickHouse mirror tests still pass; a small serial create and drop batch works end to end. |
| Static | Lint and format | Ruff check and format, plus the repository's pre-commit hooks. |

## References

- Client implementation: `src/dw_lib/peerdb.py`
- Existing mirror waits: `src/dw_lib/peerdb.py:1227-1372`
- Existing mirror lifecycle methods: `src/dw_lib/peerdb.py:2020-2512`
- Existing peer mirror drop: `src/dw_lib/peerdb.py:1840-1925`
- CLI mirror commands: `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/mirror.py`
- CLI peer commands: `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/peer.py`
- CLI bootstrap: `examples/cli/packages/example_cli/src/example_cli/peerdb_cli/__init__.py`
- Long-running operations research: `docs/plans/peerdb-client-timeouts/design.md`
- PeerDB create returns after workflow start: `vendor/peerdb/flow/cmd/handler.go:158-250`
- Snapshot status and wait: `vendor/peerdb/flow/workflows/cdc_flow.go:729,757-770,840`
- Large-table partition warning: `vendor/peerdb/flow/activities/flowable.go:657-665`
- QRep partition and replication timeouts: `vendor/peerdb/flow/workflows/qrep_flow.go:203,228`
- Postgres resync rename: `vendor/peerdb/flow/connectors/postgres/postgres_destination.go:626-723`
