# System Architecture

## Entry Points

Document the main runtime entry points.

(Examples will be added once the first source structure and entry points are defined.)

## Module Structure

Document each major module as the codebase is created.

### Core / Infrastructure

Infrastructure utilities, shared helpers, configuration.

### Data / Persistence

Persistence and state management.

### Services

Application services and business workflows.

### API / Delivery

HTTP, gRPC, CLI, or other external surfaces.

### UI / Presentation (if applicable)

Frontend, templates, or presentation layer.

### Integrations

External systems, credentials, APIs, brokers, queues, cloud services.

## Data Flow

Describe the main runtime flow once defined:

1. Startup / initialization
2. Request / event intake
3. State read / write
4. Business logic
5. External side effects
6. Response / event emission
7. Logging and audit

## Background Jobs

Document schedulers, workers, queues, or cron tasks as they are introduced.

## External Integrations

For every external dependency (once added):
- API used
- Auth method
- Env vars
- Failure behavior
- Test mocking strategy

## Invariants

List architecture invariants that must not be violated.

(Examples will be populated as the design solidifies.)
