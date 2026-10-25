# PeerDB Mirror Wait Specification

> **Status:** Approved. Last updated 2026-10-24.

## Purpose

Creating or resyncing many PeerDB mirrors against large source tables can start several initial snapshots at once and overload the source database. The CLI currently offers no way to wait for each mirror's snapshot to finish before starting the next. This feature adds explicit wait and no-wait modes to mirror creation and resync, with no-wait preserved as the default.

## Requirements

### Requirement: Wait mode waits for snapshot completion

`--wait` SHALL make a mirror command return only after the selected mirror reaches snapshot completion.

#### Scenario: Normal create

- **WHEN** a user runs `mirror create NAME --wait`
- **THEN** the command returns only after the mirror reaches `STATUS_RUNNING`
- **AND** the command does not return while the mirror is setting up or snapshotting

#### Scenario: Snapshot-only create

- **WHEN** a user runs `mirror create NAME --wait` for a mirror configured for an initial snapshot only
- **THEN** the command returns only after the mirror reaches `STATUS_COMPLETED`

#### Scenario: Normal resync

- **WHEN** a user runs `mirror resync NAME --wait`
- **THEN** the command returns only after the resync completes and the mirror reaches `STATUS_RUNNING`

#### Scenario: Snapshot-only resync

- **WHEN** a user runs `mirror resync NAME --wait` for a mirror configured for an initial snapshot only
- **THEN** the command returns only after the resync completes and the mirror reaches `STATUS_COMPLETED`

### Requirement: Wait mode is sequential for all mirrors

When `--all --wait` is used, the CLI SHALL start the next mirror only after the previous mirror reaches snapshot completion.

#### Scenario: Create all mirrors sequentially

- **WHEN** a user runs `mirror create --all --wait` with two mirrors
- **THEN** the second create request is sent only after the first mirror reaches `STATUS_RUNNING` or `STATUS_COMPLETED`

#### Scenario: Resync all mirrors sequentially

- **WHEN** a user runs `mirror resync --all --wait` with two mirrors
- **THEN** the second resync request is sent only after the first mirror reaches `STATUS_RUNNING` or `STATUS_COMPLETED`

### Requirement: Create no-wait preserves existing behaviour

`mirror create --no-wait` SHALL return after PeerDB accepts the create request, without waiting for snapshot completion.

#### Scenario: Snapshot still running

- **WHEN** a user runs `mirror create NAME --no-wait` and the mirror's initial snapshot is still running
- **THEN** the command has already returned

### Requirement: Resync no-wait preserves existing behaviour

`mirror resync --no-wait` SHALL return after the mirror reaches `STATUS_RESYNC`, without waiting for snapshot completion.

#### Scenario: Resync initiated during cleanup

- **WHEN** a user runs `mirror resync NAME --no-wait`
- **THEN** the command returns after the mirror reaches `STATUS_RESYNC`
- **AND** the command does not wait for the resync snapshot to finish

### Requirement: No-wait is the default

`mirror create`, `mirror resync`, and `up` SHALL use no-wait mode when neither `--wait` nor `--no-wait` is given.

#### Scenario: Default create

- **WHEN** a user runs `mirror create NAME` without a wait option
- **THEN** the command returns after PeerDB accepts the create request

#### Scenario: Default resync

- **WHEN** a user runs `mirror resync NAME` without a wait option
- **THEN** the command returns after the mirror reaches `STATUS_RESYNC`

#### Scenario: Default up

- **WHEN** a user runs `up` without a wait option
- **THEN** the command creates mirrors without waiting for their snapshots

### Requirement: Up supports wait

`up --wait` SHALL wait for each configured mirror to reach snapshot completion before creating the next mirror.

#### Scenario: Up with multiple mirrors

- **WHEN** a user runs `up --wait` with two configured mirrors
- **THEN** the second mirror is created only after the first mirror reaches `STATUS_RUNNING` or `STATUS_COMPLETED`

### Requirement: Wait failure stops the command

If a selected mirror reaches `STATUS_FAILED` or `STATUS_TERMINATED` while a wait is in progress, the CLI SHALL stop with an error.

#### Scenario: Create wait failure

- **WHEN** a mirror reaches `STATUS_FAILED` during `mirror create --wait`
- **THEN** the command stops with an error

#### Scenario: Resync wait failure

- **WHEN** a mirror reaches `STATUS_TERMINATED` during `mirror resync --wait`
- **THEN** the command stops with an error

#### Scenario: All wait failure

- **WHEN** one of several mirrors fails during `--all --wait`
- **THEN** the command stops with an error
- **AND** later mirrors are not processed

### Requirement: Paused mirrors do not satisfy the wait

A mirror in `STATUS_PAUSED` or `STATUS_PAUSING` SHALL NOT satisfy snapshot completion.

#### Scenario: Mirror paused during wait

- **WHEN** a selected mirror is `STATUS_PAUSED` or `STATUS_PAUSING` while a wait is in progress
- **THEN** the command continues waiting
- **AND** the command does not report successful completion

#### Scenario: Mirror resumes

- **WHEN** the paused mirror later reaches `STATUS_RUNNING`
- **THEN** the wait completes successfully

### Requirement: Wait has no timeout

The snapshot-completion wait SHALL NOT fail solely because a configured mirror resync start wait timeout elapses.

#### Scenario: Long snapshot

- **WHEN** a mirror remains in `STATUS_SNAPSHOT` longer than the configured mirror resync start wait timeout
- **THEN** the command continues waiting
- **AND** the command does not report a timeout

### Requirement: Fast resync completion is accepted

When a resync completes before the CLI observes an intermediate status, the CLI SHALL treat the mirror's final `STATUS_RUNNING` or `STATUS_COMPLETED` as successful completion.

#### Scenario: Resync completes before an intermediate status is observed

- **WHEN** a resync finishes before any intermediate status is observed
- **THEN** the command returns successfully on `STATUS_RUNNING` or `STATUS_COMPLETED`

### Requirement: Wait applies to single and all mirrors

`--wait` SHALL wait for snapshot completion for a single named mirror and for every mirror when `--all` is used.

#### Scenario: Single mirror scope

- **WHEN** a user runs `mirror create NAME --wait`
- **THEN** the wait applies to that mirror only

#### Scenario: All mirrors scope

- **WHEN** a user runs `mirror create --all --wait`
- **THEN** the wait applies to every selected mirror

### Requirement: Resync wait reports completion

`mirror resync --wait` SHALL report that the resync completed rather than merely started.

#### Scenario: Wait mode success

- **WHEN** `mirror resync NAME --wait` succeeds
- **THEN** the output reports that the mirror was resynced

#### Scenario: No-wait mode success

- **WHEN** `mirror resync NAME --no-wait` succeeds
- **THEN** the output reports that the resync was initiated
