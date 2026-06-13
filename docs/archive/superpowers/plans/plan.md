Implementation Plan for Codex

Provide this exact plan to your AI assistant to execute the migration task-by-task.
Task 1: Database Updates & Async Driver

Files: pyproject.toml, harness_poc/core/database.py

    [ ] Add aiosqlite to the project using uv add aiosqlite.

    [ ] In harness_poc/core/database.py, modify create_tables() to include connection.execute("PRAGMA journal_mode = WAL;") immediately after foreign keys are enabled.

    [ ] Add a new table creation statement for session_snapshots with columns: session_id TEXT PRIMARY KEY, last_offset INTEGER, state_payload TEXT, and updated_at TIMESTAMP.

Task 2: Core Event Types

Files: harness_poc/core/events.py

    [ ] Define the StreamPaused event subclassing BaseEvent, with payload fields reason: str and threshold_breached: str.

    [ ] Define AgentInputAdded for user prompts, and LLMActionEmitted for tracking token usage.

Task 3: The Polars State Reducer

Files: harness_poc/core/reducers.py (New)

    [ ] Create an async function derive_session_state(db: BlackboardDatabase, session_id: str) -> dict.

    [ ] Fetch the last_offset from session_snapshots. Fetch all state_events for the session where id > last_offset.

    [ ] Load the fetched events into a polars.DataFrame.

    [ ] Calculate the current token sum and identify the sequence of SkillCompleted statuses.

    [ ] Return the newly reduced state and persist it back to session_snapshots.

Task 4: Async Event Bus

Files: harness_poc/core/event_bus.py

    [ ] Refactor EventBus to instantiate an asyncio.Queue.

    [ ] Modify publish() to insert the event into the database via EventStore, then push it to the asyncio.Queue.

    [ ] Implement an async subscribe(self, session_id: str) generator that yields events from the queue.

Task 5: The Circuit Breaker Processor

Files: harness_poc/core/processors/circuit_breaker.py (New)

    [ ] Create an async long-running task run_circuit_breaker(bus: EventBus, config: HarnessConfig).

    [ ] Consume events from the bus. Maintain local counters for consecutive skill failures and total tokens.

    [ ] If consecutive skill failures exceed config.runtime.max_retries or tokens exceed the budget, publish a StreamPaused event.

Task 6: The LLM and Skill Processors

Files: harness_poc/core/processors/llm_worker.py, harness_poc/core/processors/skill_worker.py (New)

    [ ] Wrap the pydantic_runtime.py logic inside run_llm_worker(...). It must listen for AgentInputAdded or SkillCompleted events, derive state, and execute a single PydanticAI agent.run(), emitting the result back to the bus.

    [ ] Wrap SkillRunner.execute_skill inside run_skill_worker(...). It listens for SkillCalled events, executes the Python logic, and emits SkillCompleted.

    [ ] Both workers must immediately break their loops if they observe a StreamPaused event.

Task 7: Wire up the Main Loop

Files: harness_poc/cli.py, harness_poc/main.py

    [ ] Replace the synchronous GoalRunner instantiations with an asyncio.gather() block that concurrently starts the EventBus, CircuitBreaker, LLMWorker, and SkillWorker.

    [ ] Ensure ruff check passes cleanly on all new async code.
