# Add Export Support

## Objective
Add export support

## Background
A Python harness.


## Requirements
- Must be fast

## Non-Goals
- No explicit non-goals provided.

## Proposed Behavior
- Add or change the smallest coherent surface that satisfies the objective.
- Respect these constraints: - Follow existing project patterns and keep the change narrowly scoped.
- Preserve discoverability, testability, and existing command behavior.

## Acceptance Criteria
- The requested behavior is available through the expected user path.
- Errors and unclear input produce actionable feedback.
- Existing related tests continue to pass.

## Test Plan
- Add focused unit tests for success and unclear-input paths.
- Run the targeted pytest file for the changed behavior.
- Run lint/type checks if shared interfaces changed.

## Open Questions
- No open questions recorded.
