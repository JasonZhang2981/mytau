"""Stateful reusable agent harness built on the pure loop."""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from inspect import isawaitable

from tau_agent.events import AgentEvent
from tau_agent.loop import run_agent_loop
from tau_agent.messages import AgentMessage, UserMessage
from tau_agent.tools import AgentTool
from tau_ai.provider import ModelProvider

EventListener = Callable[[AgentEvent], Awaitable[None] | None]


@dataclass(slots=True)
class AgentHarnessConfig:
    """Configuration for an `AgentHarness`."""

    provider: ModelProvider
    model: str
    system: str
    tools: list[AgentTool] = field(default_factory=list)
    max_turns: int = 8


class SimpleCancellationToken:
    """Small cancellation token used by the harness and loop."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation."""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        """Return whether cancellation has been requested."""
        return self._cancelled


class AgentHarness:
    """Reusable stateful agent brain.

    The harness owns the transcript and delegates execution to `run_agent_loop`.
    It remains independent of CLI, Rich, Textual, session files, and coding-agent
    resource loading.
    """

    def __init__(
        self,
        config: AgentHarnessConfig,
        *,
        messages: Sequence[AgentMessage] = (),
    ) -> None:
        self._config = config
        self._messages = list(messages)
        self._listeners: list[EventListener] = []
        self._current_signal: SimpleCancellationToken | None = None

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        """Return an immutable snapshot of the current transcript."""
        return tuple(self._messages)

    @property
    def config(self) -> AgentHarnessConfig:
        """Return the harness configuration."""
        return self._config

    def append_message(self, message: AgentMessage) -> None:
        """Append an existing message, useful for restoring session state."""
        self._messages.append(message)

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        """Subscribe to streamed events and return an unsubscribe callback."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            with suppress(ValueError):
                self._listeners.remove(listener)

        return unsubscribe

    def cancel(self) -> None:
        """Request cancellation for the currently running prompt, if any."""
        if self._current_signal is not None:
            self._current_signal.cancel()

    def prompt(self, content: str) -> AsyncIterator[AgentEvent]:
        """Append a user message and run the agent loop."""
        self._messages.append(UserMessage(content=content))
        return self._run()

    def continue_(self) -> AsyncIterator[AgentEvent]:
        """Continue the agent loop without appending a new user message."""
        return self._run()

    async def _run(self) -> AsyncIterator[AgentEvent]:
        signal = SimpleCancellationToken()
        self._current_signal = signal
        try:
            async for event in run_agent_loop(
                provider=self._config.provider,
                model=self._config.model,
                system=self._config.system,
                messages=self._messages,
                tools=self._config.tools,
                max_turns=self._config.max_turns,
                signal=signal,
            ):
                await self._notify(event)
                yield event
        finally:
            if self._current_signal is signal:
                self._current_signal = None

    async def _notify(self, event: AgentEvent) -> None:
        for listener in list(self._listeners):
            result = listener(event)
            if isawaitable(result):
                await result
