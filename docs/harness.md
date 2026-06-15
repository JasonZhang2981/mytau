# Agent Harness

`AgentHarness` is Tau's reusable stateful agent brain.

It lives in:

```text
src/tau_agent/harness.py
```

The harness owns a transcript and delegates execution to the pure agent loop.

## Basic shape

```python
harness = AgentHarness(
    AgentHarnessConfig(
        provider=provider,
        model="...",
        system="...",
        tools=[...],
    )
)

async for event in harness.prompt("Hello"):
    ...
```

## Responsibilities

The harness:

- stores transcript messages
- appends `UserMessage` objects for new prompts
- calls `run_agent_loop()`
- streams `AgentEvent` objects
- exposes `continue_()` for running without a new user prompt
- supports event listeners
- supports basic cancellation

The harness does not know about CLI arguments, Textual, Rich rendering, slash commands, or session files.

For a detailed architecture walkthrough, read [Phase 4: AgentHarness](architecture/phase-4-agent-harness.md).
