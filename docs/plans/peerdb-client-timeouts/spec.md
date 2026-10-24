# PeerDB Client Timeouts Specification

> **Status:** Draft. Last updated 2026-10-24.

## Purpose

The PeerDB client currently exposes a single ambiguous `operation_timeout`, uses hardcoded request timeouts that are too short for some API calls, and implements lifecycle waits as iteration counts rather than wall-clock deadlines. This lets operations exceed their configured timeout, mishandles mirrors that are already paused or failed, and can leave state-change requests waiting indefinitely. The change groups the PeerDB UI URL and all timeout and interval settings under a top-level `client` group, gives every operation an explicit default and config override, and makes lifecycle waits bounded and reliable.

## Requirements

### Requirement: Client settings group

The configuration SHALL accept the PeerDB UI URL and all timeout and interval settings under a top-level `client` group.

#### Scenario: Client group accepted

- **WHEN** a configuration places the PeerDB UI URL and timeout settings under `client`
- **THEN** parsing succeeds
- **AND** every configured value is available to the client

#### Scenario: Missing client group rejected

- **WHEN** a configuration omits the `client` group
- **THEN** parsing fails with an error naming the missing group

### Requirement: Defaults for every setting

Every timeout and interval setting SHALL have a default value when omitted from the configuration.

#### Scenario: Omitted settings use defaults

- **WHEN** the `client` group contains only the PeerDB UI URL
- **THEN** parsing succeeds
- **AND** every timeout and interval setting has its documented default value

### Requirement: Configuration overrides

Every timeout and interval setting SHALL be overridable through the `client` group.

#### Scenario: Override is used

- **WHEN** a timeout or interval setting is overridden under `client`
- **THEN** the client uses the configured value instead of the default

### Requirement: Positive integer values

Timeout and interval settings SHALL reject values less than one second.

#### Scenario: Zero rejected

- **WHEN** a timeout or interval setting is set to zero
- **THEN** parsing fails with a validation error

#### Scenario: Negative value rejected

- **WHEN** a timeout or interval setting is set to a negative number
- **THEN** parsing fails with a validation error

### Requirement: Legacy top-level keys rejected

Configuration SHALL reject the legacy top-level `operation_timeout` and `peerdb_ui_url` keys with an error that names their replacements under `client`.

#### Scenario: Legacy timeout rejected

- **WHEN** a configuration contains `operation_timeout`
- **THEN** parsing fails with an error that names the replacement timeout settings under `client`

#### Scenario: Legacy URL rejected

- **WHEN** a configuration contains a top-level `peerdb_ui_url`
- **THEN** parsing fails with an error that names `client.peerdb_ui_url`

### Requirement: Fast request timeouts

Fast PeerDB API requests SHALL use the configured connect and read timeouts, and a request timeout SHALL raise the library exception for that operation rather than a raw HTTP client exception.

#### Scenario: Read timeout is wrapped

- **WHEN** a fast API request exceeds its read timeout
- **THEN** the client raises the library exception for that operation
- **AND** the original timeout is available as the cause

#### Scenario: Connectivity check reports failure

- **WHEN** the connectivity check exceeds its connect or read timeout
- **THEN** the check returns `False`
- **AND** no raw HTTP client exception escapes

### Requirement: Operation-specific request timeouts

Peer creation, mirror creation, and mirror state-change requests SHALL each use their own configured request timeout.

#### Scenario: Peer creation uses its own budget

- **WHEN** a peer is created and server-side validation takes longer than the fast request timeout
- **THEN** the request is allowed to continue up to the peer creation request timeout

#### Scenario: State change uses its own budget

- **WHEN** a mirror state change is requested and the server performs a synchronous shutdown or drop
- **THEN** the request is allowed to continue up to the state-change request timeout

### Requirement: Wall-clock lifecycle waits

Lifecycle waits SHALL be bounded by elapsed wall-clock time and SHALL use the configured status poll interval.

#### Scenario: Slow status calls do not extend the deadline

- **WHEN** a lifecycle wait is configured for a given number of seconds and individual status calls are slow
- **THEN** the wait stops once the configured wall-clock time has elapsed
- **AND** it does not run for a number of iterations derived from the timeout value

#### Scenario: Timeout reports last status

- **WHEN** a lifecycle wait reaches its deadline without reaching the target state
- **THEN** the timeout error includes the last observed mirror status

### Requirement: Terminal state fail-fast

Lifecycle waits SHALL stop immediately when a configured failure status such as `STATUS_FAILED` or `STATUS_TERMINATED` is observed.

#### Scenario: Failed mirror does not wait for the deadline

- **WHEN** a wait is polling a mirror that becomes `STATUS_FAILED`
- **THEN** the wait raises a terminal-state error immediately
- **AND** the error reports the observed status

### Requirement: Pause and resume from transitional states

Pause and resume SHALL handle a mirror that is already `STATUS_PAUSING`.

#### Scenario: Pause from pausing

- **WHEN** a pause is requested for a mirror in `STATUS_PAUSING`
- **THEN** the client waits for `STATUS_PAUSED`
- **AND** the wait is bounded by the pause wait timeout

#### Scenario: Resume from pausing

- **WHEN** a resume is requested for a mirror in `STATUS_PAUSING`
- **THEN** the client waits for `STATUS_PAUSED`
- **AND** then requests the resume
- **AND** waits for `STATUS_RUNNING` within the resume wait timeout

### Requirement: Resync semantics

Resync SHALL confirm progress for signal-based resyncs and SHALL NOT wait for the transient `STATUS_RESYNC` state when the server recreates a failed or completed mirror synchronously.

#### Scenario: Failed mirror resync

- **WHEN** a resync is requested for a mirror in `STATUS_FAILED` or `STATUS_COMPLETED`
- **THEN** the client returns after the synchronous recreate request succeeds
- **AND** it does not wait for `STATUS_RESYNC`

#### Scenario: Running mirror resync

- **WHEN** a resync is requested for a mirror in `STATUS_RUNNING`, `STATUS_PAUSED`, `STATUS_SETUP`, or `STATUS_SNAPSHOT`
- **THEN** the client waits for a resync progress state such as `STATUS_RESYNC`, `STATUS_SETUP`, or `STATUS_SNAPSHOT`
- **AND** the wait is bounded by the resync wait timeout

### Requirement: Drop semantics

Mirror drops SHALL wait until the mirror is no longer reported, and peer drops SHALL apply a total wait budget across all dependent mirror drops.

#### Scenario: Mirror disappears

- **WHEN** a mirror drop is requested
- **THEN** the client waits until the mirror is no longer reported
- **AND** the wait is bounded by the mirror drop wait timeout

#### Scenario: Peer drop total budget

- **WHEN** a peer with multiple mirrors is dropped
- **THEN** the dependent mirror drops share the configured peer drop wait budget
- **AND** the total wait does not grow by one full timeout per mirror

### Requirement: Mirror existence

A successful mirror status response SHALL mean the mirror exists, regardless of the reported status value.

#### Scenario: Unknown status is existing

- **WHEN** the status endpoint returns a successful response with `STATUS_UNKNOWN`
- **THEN** the client treats the mirror as existing

#### Scenario: Not found is missing

- **WHEN** the status endpoint reports that the mirror does not exist
- **THEN** the client treats the mirror as missing

### Requirement: Transient polling errors

Transient status errors during a lifecycle wait SHALL be retried until the wait deadline.

#### Scenario: Transient error recovers

- **WHEN** a status call fails transiently and a later call succeeds within the deadline
- **THEN** the wait continues normally

#### Scenario: Persistent error surfaces at the deadline

- **WHEN** status calls keep failing until the deadline
- **THEN** the timeout error includes the last observed error
