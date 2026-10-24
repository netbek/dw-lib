# PeerDB Client Timeouts Design

> **Status:** Last updated 2026-10-24.

## Context

`Config` currently exposes one timing setting, `operation_timeout`, at the top level alongside `peerdb_ui_url`, `settings`, `peers`, and `mirrors` (`src/dw_lib/peerdb.py:889-915`). The implementation has several problems:

- `operation_timeout` is a poll-iteration count, not a wall-clock deadline. `wait_for_mirror_status` loops `range(timeout)` and sleeps one second per iteration (`src/dw_lib/peerdb.py:1753-1768`). Each iteration also performs an HTTP request with a hardcoded five-second timeout (`src/dw_lib/peerdb.py:1713-1715`), so a 15-second setting can take roughly 90 seconds.
- `drop_peer` applies the timeout to each dependent mirror drop (`src/dw_lib/peerdb.py:1584-1589`, `:1633-1639`), so dropping N mirrors can take N times the configured value.
- State-change requests use `timeout=None` (`src/dw_lib/peerdb.py:1603`, `:1946`, `:2028`, `:2092`, `:2154`), which waits forever if the server hangs.
- Request handlers catch `(requests.HTTPError, requests.ConnectionError)` but not `requests.Timeout` (for example `src/dw_lib/peerdb.py:1343`, `:1522`). `ReadTimeout` is not a `ConnectionError`, so it escapes as a raw `requests` exception. The same gap exists in `can_connect` (`src/dw_lib/peerdb.py:1093`).
- `has_mirror` treats `STATUS_UNKNOWN` as missing (`src/dw_lib/peerdb.py:1683`) even though a successful status response means the mirror exists.
- `resume_mirror` accepts `STATUS_PAUSING` (`src/dw_lib/peerdb.py:2142`), but PeerDB only sends a resume signal from `STATUS_PAUSED` (`vendor/peerdb/flow/cmd/handler.go:498-500`). The client then waits for `STATUS_RUNNING` until timeout.
- `resync_mirror` waits for the transient `STATUS_RESYNC` (`src/dw_lib/peerdb.py:2039`). PeerDB recreates failed or completed mirrors synchronously, and the new flow starts in `STATUS_SETUP` (`vendor/peerdb/flow/workflows/cdc_state/state.go:75-80`). For a running mirror, resync can also pass through `RESYNC` faster than the poll interval.

Server-side budgets that shape the client defaults:

| PeerDB behavior | Budget | Evidence |
|---|---:|---|
| Peer validation | 15s Postgres; 60s ClickHouse | `vendor/peerdb/flow/cmd/validate_peer.go:31-37` |
| Peer info/type request | 30s | `vendor/peerdb/flow/cmd/peer_data.go:50,91` |
| Synchronous drop/shutdown wait | 5 minutes | `vendor/peerdb/flow/cmd/handler.go:406` |
| Drop activity | 5 minutes per activity, up to 50 retries | `vendor/peerdb/flow/workflows/drop_flow.go:20-22,50-95` |
| CDC idle timeout | 60s client default; 10s backend default when zero | `vendor/peerdb/flow/activities/flowable.go:61-66` |
| HTTP gateway read-header timeout | 5 minutes | `vendor/peerdb/flow/cmd/api.go:161` |

## Goals

1. Move the PeerDB UI URL and all client timing settings under one top-level `client` group.
2. Give every timeout and interval a documented default and a config-file override.
3. Bound each API request and lifecycle wait by an explicit, operation-specific budget.
4. Make lifecycle waits wall-clock based, configurable, and reliable across pause, resume, resync, and drop.
5. Surface terminal mirror states and request timeouts as clear library errors.

## Non-goals

- Changing PeerDB's server-side validation, workflow, or drop timeouts.
- Adding connect or statement timeouts to the local Postgres and ClickHouse adapters.
- Retrying peer or mirror creation requests automatically.
- Backward compatibility for the old top-level `operation_timeout` and `peerdb_ui_url` keys.
- Renaming `ConfigMirror.idle_timeout_seconds`; it is a PeerDB CDC setting, not a client timeout.

## Terminology

| Term | Meaning |
|---|---|
| Request timeout | Maximum time a single HTTP request may spend connecting or waiting for a response. |
| Wait timeout | Maximum wall-clock time a lifecycle operation spends polling for a target state. |
| Poll interval | Minimum sleep between two status polls inside a wait timeout. |
| Fast request | A short API call such as status, list, settings, or peer info/type. |
| Long request | Peer creation, mirror creation, or a mirror state-change request that may trigger server-side validation or synchronous cleanup. |
| Terminal status | A mirror status that ends a wait, such as `STATUS_FAILED` or `STATUS_TERMINATED`. |
| Progress status | A resync status that proves the request was accepted, such as `STATUS_RESYNC`, `STATUS_SETUP`, or `STATUS_SNAPSHOT`. |

## Architecture

```
peerdb.yaml
    │
    ├── client
    │     ├── peerdb_ui_url
    │     ├── api_connect_timeout_seconds
    │     ├── api_read_timeout_seconds
    │     ├── ... request and wait timeouts ...
    │     └── status_poll_interval_seconds
    ├── settings
    ├── peers
    └── mirrors
          │
          ▼
    Config (pydantic)
          │
          ▼
    PeerDB client
          ├── fast request helper  ──► connect + read timeouts
          ├── long request helper  ──► operation-specific request timeout
          └── wall-clock poll helper ──► wait timeout + poll interval
          │
          ▼
    PeerDB API (grpc-gateway)
```

1. `PeerDB.config` renders the YAML template, loads the `client` group, and builds `Config`.
2. Every HTTP call goes through a shared request helper that selects the fast or operation-specific timeout and wraps `requests.RequestException` in the library exception for that operation.
3. Lifecycle methods use a shared poll helper that compares `time.monotonic()` against a deadline, sleeps at most the remaining time, and inspects the mirror status.
4. `drop_peer` computes one total deadline and passes the remaining budget to each dependent `drop_mirror`.

## Configuration reference

```yaml
client:
  peerdb_ui_url: http://localhost:3000
  api_connect_timeout_seconds: 5
  api_read_timeout_seconds: 30
  peer_create_request_timeout_seconds: 90
  peer_drop_request_timeout_seconds: 30
  peer_drop_wait_timeout_seconds: 600
  mirror_create_request_timeout_seconds: 300
  mirror_state_change_request_timeout_seconds: 420
  mirror_status_wait_timeout_seconds: 600
  mirror_pause_wait_timeout_seconds: 120
  mirror_resume_wait_timeout_seconds: 120
  mirror_resync_wait_timeout_seconds: 300
  mirror_drop_wait_timeout_seconds: 300
  status_poll_interval_seconds: 1
```

| Key | Type | Default | Scope |
|---|---|---:|---|
| `peerdb_ui_url` | URL | required | PeerDB UI base URL; the API URL is derived by appending `api`. |
| `api_connect_timeout_seconds` | integer ≥ 1 | 5 | TCP/TLS connect for every API request. |
| `api_read_timeout_seconds` | integer ≥ 1 | 30 | Read budget for fast API requests. |
| `peer_create_request_timeout_seconds` | integer ≥ 1 | 90 | `create_peer`; covers 60s ClickHouse validation. |
| `peer_drop_request_timeout_seconds` | integer ≥ 1 | 30 | Final peer-drop request. |
| `peer_drop_wait_timeout_seconds` | integer ≥ 1 | 600 | Total wait across all dependent mirror drops. |
| `mirror_create_request_timeout_seconds` | integer ≥ 1 | 300 | `create_mirror`; covers synchronous source/destination validation. |
| `mirror_state_change_request_timeout_seconds` | integer ≥ 1 | 420 | Pause, resume, resync, and drop state-change requests; covers PeerDB's 5-minute synchronous shutdown path. |
| `mirror_status_wait_timeout_seconds` | integer ≥ 1 | 600 | Default wait for the public mirror-status wait operation. |
| `mirror_pause_wait_timeout_seconds` | integer ≥ 1 | 120 | Poll until `STATUS_PAUSED`. |
| `mirror_resume_wait_timeout_seconds` | integer ≥ 1 | 120 | Poll until `STATUS_RUNNING` after resume. |
| `mirror_resync_wait_timeout_seconds` | integer ≥ 1 | 300 | Poll for resync progress. |
| `mirror_drop_wait_timeout_seconds` | integer ≥ 1 | 300 | Poll until the mirror disappears. |
| `status_poll_interval_seconds` | integer ≥ 1 | 1 | Sleep between status polls. |

## Lifecycle reference

| Operation | PeerDB behavior | Client wait |
|---|---|---|
| Create peer | Validate peer, then insert. Validation is 15s for Postgres and 60s for ClickHouse. | None; use `peer_create_request_timeout_seconds`. |
| Create mirror | Validate source/destination synchronously, then start the workflow. Setup and snapshot run asynchronously. | None; use `mirror_create_request_timeout_seconds`. Optional status wait uses `mirror_status_wait_timeout_seconds`. |
| Pause | Signal; `RUNNING → PAUSING → PAUSED`. | Wait for `PAUSED` with `mirror_pause_wait_timeout_seconds`. |
| Resume | Signal only from `PAUSED`; `PAUSED → RUNNING`. | If `PAUSING`, wait for `PAUSED`, then resume and wait for `RUNNING` with `mirror_resume_wait_timeout_seconds`. |
| Resync | Signal for `RUNNING`, `PAUSED`, `SETUP`, and `SNAPSHOT`; synchronous recreate for `FAILED` and `COMPLETED`. | Failed/completed: return after the synchronous request. Others: wait for a progress status with `mirror_resync_wait_timeout_seconds`. |
| Drop mirror | Signal for active states; synchronous drop or shutdown for `FAILED` and `COMPLETED`; cleanup removes the catalog entry. | Wait until the mirror is no longer reported with `mirror_drop_wait_timeout_seconds`. |
| Drop peer | Drop dependent mirrors, then delete the peer. | Share `peer_drop_wait_timeout_seconds` across all dependent mirrors; final request uses `peer_drop_request_timeout_seconds`. |

## Code layout

| Module | Responsibility |
|---|---|
| `src/dw_lib/peerdb.py` | Add the `client` config model and defaults; parse the group; add request and poll helpers; update lifecycle methods. |
| `src/dw_lib/exceptions.py` | Add a terminal-state exception for fail-fast lifecycle waits. |
| `tests/peerdb/test_config.py` | Defaults, overrides, validation, and confirmation that old top-level keys are not read. |
| `tests/peerdb/test_timeouts.py` | Wall-clock polling, terminal states, resync/resume transitions, request-timeout wrapping. |
| `tests/peerdb/fixtures/*.yaml` | Replace `operation_timeout` with the `client` group. |
| `tests/peerdb/test_postgres.py`, `tests/peerdb/test_clickhouse.py` | Update expected parsed config. |
| `examples/cli/peerdb.yaml` | Document the `client` group. |

## Design decisions

### D1: Use a top-level `client` group

**Decision.** Move `peerdb_ui_url` and every timeout and interval into a top-level `client` group.

**Rationale.** The group owns the PeerDB client's endpoint and timing behavior. `client` is short, and inside `peerdb.yaml` it clearly refers to the PeerDB client rather than the database adapters. Names such as `api`, `connection`, and `timeouts` either misdescribe the contents or cannot hold the URL. `settings` is already used for PeerDB dynamic settings.

**Consequences.** Existing configurations must move `peerdb_ui_url` under `client`. The key keeps its existing name as `client.peerdb_ui_url`. Old top-level keys are not read; a configuration without `client` fails validation.

### D2: Per-operation matrix with flat keys inside `client`

**Decision.** Keep the keys flat inside `client` and give each operation its own request and wait budget.

**Rationale.** Peer creation, mirror creation, state changes, pause, resync, and drop have materially different server-side budgets. A single `operation_timeout` cannot describe all of them without either being too short or hiding long waits.

**Consequences.** The configuration has more keys, but each name states its scope. Defaults are documented in the configuration reference.

### D3: No backward compatibility for legacy top-level keys

**Decision.** Read timeout and interval settings only from `client`. Do not provide aliases, fallbacks, or migration shims for the old top-level `operation_timeout` and `peerdb_ui_url` keys.

**Rationale.** The user does not need backward compatibility for these keys, and a single authoritative location keeps the parser simple and the configuration unambiguous.

**Consequences.** This is a breaking configuration change. A configuration that uses only the old top-level keys fails because `client` is missing. Old keys placed alongside a valid `client` group are not read.

### D4: Wall-clock deadlines

**Decision.** Lifecycle waits use `time.monotonic()` with a deadline. Each loop computes the remaining time and sleeps at most `min(poll_interval, remaining)`.

**Rationale.** The current iteration-count loop can exceed the configured timeout by the duration of every HTTP request plus one extra sleep. A wall-clock deadline makes the setting mean what its name says.

**Consequences.** Slow status requests consume the wait budget. The poll interval is a minimum sleep, not a guarantee of one poll per interval. Tests must use a fake clock rather than counting iterations.

### D5: Fail fast on terminal states

**Decision.** Lifecycle waits raise a terminal-state exception when they observe `STATUS_FAILED` or `STATUS_TERMINATED`, unless those statuses are explicit targets. `STATUS_COMPLETED` is not treated as a failure because snapshot-only mirrors legitimately complete.

**Rationale.** Waiting the full timeout after a mirror has already failed hides the real outcome and wastes time.

**Consequences.** A new exception is needed. The public status-wait operation accepts a failure-status set so callers can override the default.

### D6: Robust pause and resume

**Decision.** Pause from `STATUS_PAUSING` waits for `STATUS_PAUSED`. Resume from `STATUS_PAUSING` waits for `STATUS_PAUSED`, then sends the resume signal and waits for `STATUS_RUNNING`.

**Rationale.** PeerDB ignores a resume request while the mirror is still pausing. The current client accepts `PAUSING` and then waits for `RUNNING` until timeout.

**Consequences.** Resume can take up to the pause wait plus the resume wait. Both waits are independently bounded and configurable.

### D7: Robust resync

**Decision.** Capture the previous status before requesting resync. For `STATUS_FAILED` and `STATUS_COMPLETED`, return after the synchronous recreate request succeeds. For other states, wait for `STATUS_RESYNC`, `STATUS_SETUP`, or `STATUS_SNAPSHOT`, and treat `STATUS_RUNNING` as success only when the previous status was not `STATUS_RUNNING`.

**Rationale.** `STATUS_RESYNC` is transient and may be missed. Failed and completed mirrors are recreated synchronously and start in `STATUS_SETUP`, so waiting for `STATUS_RESYNC` can block until the snapshot finishes.

**Consequences.** Resync confirms initiation, not completion. Callers that need completion must wait for `STATUS_RUNNING` separately with `mirror_status_wait_timeout_seconds` or a larger override.

### D8: Mirror existence means a successful status response

**Decision.** `has_mirror` returns `True` for any successful status response and `False` only when the status endpoint reports not found.

**Rationale.** Existence and status are different questions. A mirror can exist with `STATUS_UNKNOWN`, especially during creation.

**Consequences.** Create and drop no longer treat an unknown status as a missing mirror. The status value is still available to callers that need it.

### D9: Centralize request handling

**Decision.** Route every PeerDB API call through a shared request helper that selects the timeout, initializes the response variable, and catches `requests.RequestException`.

**Rationale.** `requests.Timeout` is not a `ConnectionError`; the current handlers miss `ReadTimeout` and can reference an unbound `response` after a connection failure. Centralizing the logic removes duplicated error handling.

**Consequences.** Every operation maps its request failures to its existing library exception. The connectivity check returns `False` on any request exception instead of leaking a raw timeout.

### D10: Peer drop uses one total budget

**Decision.** `drop_peer` computes a single deadline from `peer_drop_wait_timeout_seconds` and passes the remaining time to each dependent mirror drop.

**Rationale.** The current implementation applies the full timeout per mirror, so total wait grows with the number of mirrors.

**Consequences.** The `drop_peer` timeout argument now means total dependent-mirror wait, not per-mirror wait. A mirror drop still receives at most `mirror_drop_wait_timeout_seconds` or the remaining peer budget, whichever is smaller.

### D11: Retry transient status errors until the deadline

**Decision.** During a lifecycle wait, retry transient status errors such as connection failures and server errors until the wait deadline. Include the last error in the timeout message.

**Rationale.** A single transient error should not abort a long lifecycle wait. A persistent outage still surfaces as a timeout with the underlying error.

**Consequences.** A long wait timeout also means a long wait before a persistent error is reported. Callers can lower the wait timeout when fast failure is preferred.

### D12: Keep `idle_timeout_seconds` as a mirror setting

**Decision.** Do not move `ConfigMirror.idle_timeout_seconds` into the `client` group and do not rename it.

**Rationale.** It is a PeerDB CDC batch setting sent in the mirror payload, not a client-side request or polling timeout. It already has a default and a config override.

**Consequences.** Documentation must distinguish the PeerDB-side idle timeout from the client-side wait timeouts.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Keep `operation_timeout` as a deprecated alias | It is ambiguous and does not map cleanly to the per-operation waits. No backward compatibility is required for the old top-level keys. |
| Keep the timeout keys at the top level | The user chose a `client` group to separate client endpoint and timing settings from peers, mirrors, and dynamic settings. |
| Use one generic poll timeout | Pause, resume, resync, and drop have very different server-side durations; one value is either too short or too long for some operations. |
| Keep iteration-count polling | It cannot enforce a wall-clock deadline and can exceed the configured timeout by the sum of request durations. |
| Wait for the exact `STATUS_RESYNC` state | It is transient for running mirrors and appears only after the snapshot for recreated failed/completed mirrors. |
| Treat `STATUS_UNKNOWN` as missing | It conflates status with existence and can cause duplicate creates or skipped drops. |
| Catch only `HTTPError` and `ConnectionError` | `ReadTimeout` is a `Timeout`, not a `ConnectionError`, so it escapes as a raw exception. |
| Apply the peer drop timeout per mirror | Total wait grows linearly with the number of mirrors. |

## Test strategy

| Layer | Scope | Examples |
|---|---|---|
| Unit (offline) | Config parsing | Defaults; every override; zero and negative values rejected; old top-level keys are not read. |
| Unit (offline) | Timeout behavior | Wall-clock deadline with a fake clock; slow status calls; terminal-state fail-fast; transient error recovery; persistent error at deadline; `ReadTimeout` wrapping; `can_connect` returns `False` on timeout. |
| Unit (offline) | Lifecycle transitions | Resume from `PAUSING`; pause from `PAUSING`; resync from `FAILED`/`COMPLETED`; resync progress for running mirrors; drop timeout includes last status; `has_mirror` with `STATUS_UNKNOWN`. |
| Integration (Docker) | Real API behavior | Existing Postgres and ClickHouse mirror tests pass with the `client` group; pause, resume, resync, and drop still work end to end. |
| Static | Lint and format | Ruff check and format, plus the repository's pre-commit hooks. |

## References

- Client implementation: `src/dw_lib/peerdb.py`
- Client exceptions: `src/dw_lib/exceptions.py`
- Peer validation: `vendor/peerdb/flow/cmd/validate_peer.go:31-37`
- Flow state changes: `vendor/peerdb/flow/cmd/handler.go:430-573`
- Peer info/type timeouts: `vendor/peerdb/flow/cmd/peer_data.go:50,91`
- CDC pause/resume/resync: `vendor/peerdb/flow/workflows/cdc_flow.go:554-612`
- Workflow state defaults: `vendor/peerdb/flow/workflows/cdc_state/state.go:75-80`
- Drop workflow: `vendor/peerdb/flow/workflows/drop_flow.go:20-22,50-95,181-183`
- CDC idle timeout: `vendor/peerdb/flow/activities/flowable.go:61-66`
- Existing plan style: `docs/plans/peerdb-table-mapping-fields/spec.md`, `docs/plans/peerdb-table-mapping-fields/design.md`
