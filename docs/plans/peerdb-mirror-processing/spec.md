# PeerDB Mirror Processing Specification

> **Status:** Approved. Last updated 2026-10-21.

## Purpose

Creating multiple PeerDB mirrors back to back starts their initial snapshots concurrently, which can exhaust source database resources. This feature makes serial processing the default so that each mirror's snapshot finishes before the next mirror starts. A `--parallel` option restores concurrent processing. Mirror drops already wait for each flow to disappear and are unchanged.

## Requirements

### Requirement: Default serial create

By default, the CLI SHALL wait for each newly created mirror to become ready before creating the next mirror.

#### Scenario: Two mirrors created in series

- **WHEN** the user runs `peerdb up` with two configured mirrors
- **THEN** the first mirror's initial load finishes before the second mirror is created

#### Scenario: Single mirror created

- **WHEN** the user runs `peerdb mirror create cdc_one`
- **THEN** the command waits until `cdc_one` is ready before returning

#### Scenario: Replaced mirror waits

- **WHEN** the user runs `peerdb mirror create --all` with replacement enabled
- **THEN** each replacement mirror becomes ready before the next replacement starts

### Requirement: Default serial resync

By default, the CLI SHALL wait for each mirror's resync to finish before starting the next resync.

#### Scenario: Two mirrors resynced in series

- **WHEN** the user runs `peerdb mirror resync --all`
- **THEN** the first mirror finishes resyncing before the second resync starts

#### Scenario: Single mirror resynced

- **WHEN** the user runs `peerdb mirror resync cdc_one`
- **THEN** the command waits until `cdc_one` finishes resyncing before returning

#### Scenario: Completed mirror resynced

- **WHEN** `cdc_one` is `STATUS_COMPLETED` and the user runs `peerdb mirror resync cdc_one`
- **THEN** PeerDB recreates the mirror
- **AND** the command waits until the recreated mirror becomes ready before returning

#### Scenario: Failed mirror resynced

- **WHEN** `cdc_one` is `STATUS_FAILED` and the user runs `peerdb mirror resync cdc_one`
- **THEN** PeerDB recreates the mirror
- **AND** the command waits until the recreated mirror becomes ready before returning

### Requirement: Terminated mirrors are not resynced

The CLI SHALL reject a resync request for a mirror in `STATUS_TERMINATED` or `STATUS_TERMINATING`.

#### Scenario: Terminated mirror

- **WHEN** `cdc_one` is terminated or terminating and the user runs `peerdb mirror resync cdc_one`
- **THEN** the command reports an error without sending a resync request

### Requirement: Parallel option

The CLI SHALL accept a `--parallel` option on the commands that create or resync mirrors.

#### Scenario: Parallel create option

- **WHEN** the user runs `peerdb up --parallel`
- **THEN** the command accepts the option without an unknown-option error

#### Scenario: Parallel resync option

- **WHEN** the user runs `peerdb mirror resync --all --parallel`
- **THEN** the command accepts the option without an unknown-option error

### Requirement: Parallel create

With `--parallel`, the CLI SHALL create mirrors without waiting for each mirror to become ready.

#### Scenario: Two mirrors created in parallel

- **WHEN** the user runs `peerdb up --parallel` with two configured mirrors
- **THEN** the second mirror is created before the first mirror is ready

#### Scenario: Single mirror created in parallel

- **WHEN** the user runs `peerdb mirror create cdc_one --parallel`
- **THEN** the command returns without waiting for `cdc_one` to become ready

### Requirement: Parallel resync

With `--parallel`, the CLI SHALL resync mirrors without waiting for each resync to finish.

#### Scenario: Two mirrors resynced in parallel

- **WHEN** the user runs `peerdb mirror resync --all --parallel`
- **THEN** the second resync starts before the first resync finishes

#### Scenario: Single mirror resynced in parallel

- **WHEN** the user runs `peerdb mirror resync cdc_one --parallel`
- **THEN** the command returns without waiting for `cdc_one` to finish resyncing

#### Scenario: Completed mirror resynced in parallel

- **WHEN** `cdc_one` is `STATUS_COMPLETED` and the user runs `peerdb mirror resync cdc_one --parallel`
- **THEN** the command returns after PeerDB accepts the request without waiting for the recreated mirror's snapshot

### Requirement: Ready state

A mirror SHALL be considered ready when its flow state is `STATUS_RUNNING` or `STATUS_COMPLETED`.

#### Scenario: CDC mirror reaches running

- **WHEN** a mirror's flow state becomes `STATUS_RUNNING`
- **THEN** the serial wait ends and the next mirror may start

#### Scenario: Snapshot-only mirror completes

- **WHEN** a mirror configured to run only an initial snapshot reaches `STATUS_COMPLETED`
- **THEN** the serial wait ends and the next mirror may start

### Requirement: Failure stops the series

While waiting in serial processing, the CLI SHALL abort the run with an error when a mirror reaches `STATUS_FAILED`, `STATUS_TERMINATED`, or `STATUS_TERMINATING`.

#### Scenario: Snapshot fails

- **WHEN** the first mirror reaches `STATUS_FAILED` during its initial load
- **THEN** the command reports an error
- **AND** the command does not create the next mirror

#### Scenario: Mirror disappears while waiting

- **WHEN** a mirror is removed while the command is waiting for it
- **THEN** the command reports an error
- **AND** the command does not process the next mirror

### Requirement: No wait timeout

The CLI SHALL wait indefinitely for a mirror to become ready or reach a failure state, without imposing a timeout.

A mirror that is paused, pausing, unknown, or modifying is not a failure state. The CLI SHALL keep waiting while it is in one of these states. A status-query error aborts the run.

#### Scenario: Long-running snapshot

- **WHEN** a mirror remains in a snapshot state for longer than the configured operation timeout
- **THEN** the CLI continues waiting

#### Scenario: Paused while waiting

- **WHEN** a mirror is paused while the CLI is waiting for it
- **THEN** the CLI keeps waiting until the mirror is resumed, reaches a failure state, or the command is interrupted

### Requirement: Kept mirrors are not waited on

When an existing mirror is kept because the create command is configured to keep existing mirrors, the CLI SHALL not wait for that mirror in serial processing.

#### Scenario: Existing mirror kept

- **WHEN** the first mirror already exists and the create command is configured to keep existing mirrors
- **THEN** the command does not wait for the existing mirror
- **AND** the command proceeds to the next mirror

#### Scenario: New mirror still waits

- **WHEN** a mirror does not exist and the create command is configured to keep existing mirrors
- **THEN** the command waits for the new mirror to become ready before proceeding

### Requirement: Drop behaviour unchanged

The CLI SHALL process mirror drops one at a time, waiting up to the configured operation timeout for each flow to disappear, without a `--parallel` option.

#### Scenario: Drop all

- **WHEN** the user runs `peerdb mirror drop --all`
- **THEN** each mirror is dropped, or the command fails with a timeout, before the next drop starts
