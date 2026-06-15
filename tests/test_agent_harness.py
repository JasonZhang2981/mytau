from collections.abc import Mapping

import pytest

from tau_agent import AgentTool, AgentToolResult, AssistantMessage, UserMessage
from tau_agent.harness import AgentHarness, AgentHarnessConfig
from tau_agent.types import JSONValue
from tau_ai import (
    FakeProvider,
    ProviderResponseEndEvent,
    ProviderResponseStartEvent,
    ProviderTextDeltaEvent,
)


@pytest.mark.anyio
async def test_prompt_appends_user_message_and_assistant_response() -> None:
    assistant = AssistantMessage(content="Hello")
    provider = FakeProvider(
        [[ProviderResponseStartEvent(model="fake"), ProviderResponseEndEvent(message=assistant)]]
    )
    harness = AgentHarness(
        AgentHarnessConfig(provider=provider, model="fake", system="You are Tau.")
    )

    events = [event async for event in harness.prompt("Hi")]

    assert [event.type for event in events] == [
        "agent_start",
        "turn_start",
        "message_start",
        "message_end",
        "turn_end",
        "agent_end",
    ]
    assert harness.messages == (UserMessage(content="Hi"), assistant)


@pytest.mark.anyio
async def test_continue_runs_without_adding_user_message() -> None:
    existing = UserMessage(content="Previous prompt")
    assistant = AssistantMessage(content="Continuing")
    provider = FakeProvider(
        [[ProviderResponseStartEvent(model="fake"), ProviderResponseEndEvent(message=assistant)]]
    )
    harness = AgentHarness(
        AgentHarnessConfig(provider=provider, model="fake", system="You are Tau."),
        messages=[existing],
    )

    _events = [event async for event in harness.continue_()]

    assert harness.messages == (existing, assistant)
    assert provider.calls[0][2] == [existing]


def test_messages_property_returns_immutable_snapshot() -> None:
    harness = AgentHarness(
        AgentHarnessConfig(provider=FakeProvider([]), model="fake", system="You are Tau."),
        messages=[UserMessage(content="Hello")],
    )

    snapshot = harness.messages
    harness.append_message(AssistantMessage(content="Hi"))

    assert snapshot == (UserMessage(content="Hello"),)
    assert harness.messages == (UserMessage(content="Hello"), AssistantMessage(content="Hi"))


@pytest.mark.anyio
async def test_subscribed_listeners_receive_events_and_can_unsubscribe() -> None:
    assistant = AssistantMessage(content="Hello")
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderTextDeltaEvent(delta="Hello"),
                ProviderResponseEndEvent(message=assistant),
            ],
            [ProviderResponseStartEvent(model="fake"), ProviderResponseEndEvent(message=assistant)],
        ]
    )
    harness = AgentHarness(
        AgentHarnessConfig(provider=provider, model="fake", system="You are Tau.")
    )
    seen: list[str] = []

    async def listener(event: object) -> None:
        seen.append(event.type)  # type: ignore[attr-defined]

    unsubscribe = harness.subscribe(listener)

    _events = [event async for event in harness.prompt("Hi")]
    unsubscribe()
    _more_events = [event async for event in harness.continue_()]

    assert seen == [
        "agent_start",
        "turn_start",
        "message_start",
        "message_delta",
        "message_end",
        "turn_end",
        "agent_end",
    ]


@pytest.mark.anyio
async def test_cancel_requests_cancellation_for_current_run() -> None:
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderTextDeltaEvent(delta="first"),
                ProviderTextDeltaEvent(delta="second"),
                ProviderResponseEndEvent(message=AssistantMessage(content="firstsecond")),
            ]
        ]
    )
    harness = AgentHarness(
        AgentHarnessConfig(provider=provider, model="fake", system="You are Tau.")
    )

    events = []
    async for event in harness.prompt("Hi"):
        events.append(event)
        if event.type == "message_delta":
            harness.cancel()

    assert [event.type for event in events] == [
        "agent_start",
        "turn_start",
        "message_start",
        "message_delta",
        "error",
        "turn_end",
        "agent_end",
    ]
    assert harness.messages == (UserMessage(content="Hi"),)


@pytest.mark.anyio
async def test_harness_passes_tools_to_loop() -> None:
    async def executor(arguments: Mapping[str, JSONValue]) -> AgentToolResult:
        return AgentToolResult(
            tool_call_id="call-1",
            name="echo",
            ok=True,
            content=str(arguments["text"]),
        )

    tool = AgentTool(
        name="echo",
        description="Echo text.",
        input_schema={"type": "object"},
        executor=executor,
    )
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderResponseEndEvent(message=AssistantMessage()),
            ]
        ]
    )
    harness = AgentHarness(
        AgentHarnessConfig(provider=provider, model="fake", system="You are Tau.", tools=[tool])
    )

    _events = [event async for event in harness.prompt("Hi")]

    assert provider.calls[0][3] == [tool]
