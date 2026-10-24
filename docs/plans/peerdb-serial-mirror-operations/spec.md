# PeerDB Serial Mirror Operations Specification

> **Status:** Draft. Last updated 2026-10-24.

## Purpose

PeerDB operations that act on several mirrors currently start each mirror without waiting for the previous one to settle. Initial snapshots and resyncs can therefore run concurrently even when the caller processes mirrors one at a time. This change makes every multi-mirror operation serial and adds an optional per-mirror timeout to the CLI. Parallel execution is out of scope.

## Requirements

### Requirement: Serial multi-mirror execution

Multi-mirror operations SHALL process mirrors one at a time.

#### Scenario: Create several mirrors

- **WHEN** a caller creates several mirrors
- **THEN** each mirror is created only after the previous mirror has settled

#### Scenario: Drop several mirrors

- **WHEN** a caller drops several mirrors
- **THEN** each mirror is gone before the next drop starts

#### Scenario: Pause, resume, or resync several mirrors

- **WHEN** a caller pauses, resumes, or resyncs several mirrors
- **THEN** each mirror reaches the operation's target state before the next mirror is processed

### Requirement: Settle before the next create or resync

Serial create and resync operations SHALL wait for the current mirror to reach a settled state before starting the next mirror.

A settled state is `STATUS_RUNNING`, `STATUS_PAUSED`, or `STATUS_COMPLETED`.

#### Scenario: Create a mirror with an initial snapshot

- **WHEN** a serial create starts a mirror with an initial snapshot
- **THEN** the next mirror is not created while the current mirror is in `STATUS_SETUP` or `STATUS_SNAPSHOT`
- **AND** the next mirror is created only after the current mirror reaches `STATUS_RUNNING`

#### Scenario: Create a snapshot-only mirror

- **WHEN** a serial create starts a mirror that runs only an initial snapshot
- **THEN** the next mirror is created only after the current mirror reaches `STATUS_COMPLETED`

#### Scenario: Create a mirror that already exists and is paused

- **WHEN** a serial create keeps an existing mirror that is in `STATUS_PAUSED`
- **THEN** the next mirror is created without waiting for the paused mirror to run

#### Scenario: Resync a mirror

- **WHEN** a serial resync starts a mirror
- **THEN** the next mirror is not resynced while the current mirror is in `STATUS_RESYNC` or `STATUS_SNAPSHOT`
- **AND** the next mirror is resynced only after the current mirror reaches `STATUS_RUNNING` or `STATUS_COMPLETED`

### Requirement: Terminal states stop the batch

A serial batch SHALL stop when the current mirror reaches `STATUS_FAILED` or `STATUS_TERMINATED`.

#### Scenario: Mirror fails during a create batch

- **WHEN** a mirror in a serial create batch reaches `STATUS_FAILED`
- **THEN** the batch stops
- **AND** no later mirror is created
- **AND** the error identifies the failed mirror

#### Scenario: Mirror is terminated during a resync batch

- **WHEN** a mirror in a serial resync batch reaches `STATUS_TERMINATED`
- **THEN** the batch stops
- **AND** no later mirror is resynced

### Requirement: Earlier work survives a later failure

A failed serial batch SHALL leave mirrors that completed before the failure in place.

#### Scenario: Second mirror fails

- **WHEN** the first mirror in a serial batch succeeds and the second mirror fails
- **THEN** the first mirror remains in its completed state
- **AND** the batch does not roll back the first mirror

### Requirement: Existing waits for drop, pause, and resume

Serial drop, pause, and resume operations SHALL wait for each mirror's target state before starting the next mirror.

#### Scenario: Drop waits for the mirror to disappear

- **WHEN** a serial drop processes a mirror
- **THEN** the next mirror is not dropped until the current mirror is no longer reported

#### Scenario: Pause waits for the paused state

- **WHEN** a serial pause processes a mirror
- **THEN** the next mirror is not paused until the current mirror reaches `STATUS_PAUSED`

#### Scenario: Resume waits for the running state

- **WHEN** a serial resume processes a mirror
- **THEN** the next mirror is not resumed until the current mirror reaches `STATUS_RUNNING`

### Requirement: Per-mirror timeout

Every serial mirror batch operation SHALL accept an optional per-mirror timeout.

The timeout applies to each wait performed for that mirror. It does not cancel server-side work when it expires.

#### Scenario: Create without a timeout

- **WHEN** a serial create is called without a timeout
- **THEN** each mirror may wait through `STATUS_SETUP` and `STATUS_SNAPSHOT` for as long as needed
- **AND** no completion deadline is imposed

#### Scenario: Create with a timeout

- **WHEN** a serial create is called with a timeout
- **THEN** each mirror's settle wait is bounded by that timeout
- **AND** a timeout error reports the last observed status

#### Scenario: Resync without a timeout

- **WHEN** a serial resync is called without a timeout
- **THEN** no completion deadline is imposed
- **AND** the resync initiation wait keeps its configured default

#### Scenario: Resync with a timeout

- **WHEN** a serial resync is called with a timeout
- **THEN** the resync initiation wait and the completion wait are each bounded by that timeout

#### Scenario: Drop, pause, or resume without a timeout

- **WHEN** a serial drop, pause, or resume is called without a timeout
- **THEN** the existing configured wait timeout is used for each mirror

#### Scenario: Drop, pause, or resume with a timeout

- **WHEN** a serial drop, pause, or resume is called with a timeout
- **THEN** that timeout overrides the configured wait timeout for each mirror

#### Scenario: Timeout expires

- **WHEN** a per-mirror timeout expires
- **THEN** the batch stops with a timeout error
- **AND** the mirror may continue running on the server

### Requirement: CLI timeout option

The CLI SHALL expose a per-mirror `--timeout` option for multi-mirror commands.

#### Scenario: Timeout on mirror commands

- **WHEN** `--timeout` is supplied to `mirror create --all`, `mirror drop --all`, `mirror pause --all`, `mirror resume --all`, or `mirror resync --all`
- **THEN** the value is used as the per-mirror timeout for that batch

#### Scenario: Timeout on peer drop

- **WHEN** `--timeout` is supplied to `peer drop --all`
- **THEN** the value is used as the per-mirror drop timeout for every dependent mirror

#### Scenario: Timeout on bootstrap

- **WHEN** `--timeout` is supplied to `peerdb up`
- **THEN** the value is used as the per-mirror settle timeout for mirror creation

#### Scenario: Omitted timeout

- **WHEN** `--timeout` is omitted
- **THEN** create and resync completion waits have no deadline
- **AND** drop, pause, and resume use their configured wait timeouts

#### Scenario: Timeout without all

- **WHEN** `--timeout` is supplied to a mirror or peer command without `--all`
- **THEN** the command fails with a usage error

#### Scenario: Invalid timeout

- **WHEN** `--timeout` is zero or negative
- **THEN** the command fails with a usage error

### Requirement: Single-mirror commands are unchanged

The CLI SHALL reject `--timeout` on single-mirror commands.

#### Scenario: Timeout on a single mirror

- **WHEN** `--timeout` is supplied to `mirror resync NAME`
- **THEN** the command fails with a usage error

### Requirement: Peer operations are serial

Peer drop and peer replace SHALL drop dependent mirrors one at a time.

#### Scenario: Drop a peer with several mirrors

- **WHEN** a peer with several mirrors is dropped
- **THEN** each dependent mirror is dropped before the next dependent mirror is dropped
- **AND** the peer is dropped only after all dependent mirrors are gone

#### Scenario: Replace a peer with several mirrors

- **WHEN** a peer is replaced and has several mirrors
- **THEN** each dependent mirror is dropped before the next dependent mirror is dropped
- **AND** the peer is recreated only after all dependent mirrors are gone

### Requirement: Bootstrap waits for mirrors

The `peerdb up` command SHALL process mirrors serially by waiting for each mirror to settle before creating the next one.

#### Scenario: Bootstrap several mirrors

- **WHEN** `peerdb up` creates several mirrors
- **THEN** each mirror is created only after the previous mirror has settled

#### Scenario: Bootstrap with a timeout

- **WHEN** `peerdb up` is called with `--timeout`
- **THEN** each mirror's settle wait is bounded by that timeout
