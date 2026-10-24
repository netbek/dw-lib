# PeerDB Serial Mirror Operations Specification

> **Status:** Draft. Last updated 2026-10-24.

## Purpose

PeerDB operations that act on several mirrors currently start each mirror without waiting for the previous one to settle. Initial snapshots and resyncs can therefore run concurrently even when the caller processes mirrors one at a time. This change makes every multi-mirror operation serial and adds no new timeout options: create and resync wait until settled, while drop, pause, and resume keep their configured timeouts. Parallel execution is out of scope.

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

### Requirement: No completion deadline for create and resync

Serial create and resync operations SHALL wait for a settled state without a completion deadline.

#### Scenario: Initial snapshot runs longer than a status wait

- **WHEN** a mirror remains in `STATUS_SNAPSHOT` for longer than the configured status wait timeout would allow
- **THEN** the batch keeps waiting
- **AND** the next mirror is not started

#### Scenario: Resync runs longer than a status wait

- **WHEN** a mirror remains in `STATUS_RESYNC` or `STATUS_SNAPSHOT` for longer than the configured status wait timeout would allow
- **THEN** the batch keeps waiting
- **AND** the next mirror is not started

### Requirement: Terminal states stop create and resync batches

A serial create or resync batch SHALL stop when the current mirror reaches `STATUS_FAILED` or `STATUS_TERMINATED`.

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

Serial drop, pause, and resume operations SHALL wait for each mirror's target state, using the configured wait timeout, before starting the next mirror.

#### Scenario: Drop waits for the mirror to disappear

- **WHEN** a serial drop processes a mirror
- **THEN** the next mirror is not dropped until the current mirror is no longer reported

#### Scenario: Pause waits for the paused state

- **WHEN** a serial pause processes a mirror
- **THEN** the next mirror is not paused until the current mirror reaches `STATUS_PAUSED`

#### Scenario: Resume waits for the running state

- **WHEN** a serial resume processes a mirror
- **THEN** the next mirror is not resumed until the current mirror reaches `STATUS_RUNNING`

#### Scenario: Configured timeout expires

- **WHEN** a drop, pause, or resume wait exceeds the configured timeout
- **THEN** the batch stops with a timeout error
- **AND** the mirror may continue changing state on the server

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

#### Scenario: Bootstrap waits through a long snapshot

- **WHEN** a mirror created by `peerdb up` remains in `STATUS_SNAPSHOT` for an extended period
- **THEN** `peerdb up` keeps waiting
- **AND** the next mirror is not created
