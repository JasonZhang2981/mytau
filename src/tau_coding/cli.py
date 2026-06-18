"""Command-line entry point for Tau."""

from os import environ
from pathlib import Path
from typing import Annotated

import anyio
import typer

from tau_agent.session import SessionEntry, SessionStorage
from tau_ai import (
    DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES,
    DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS,
    DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS,
    ModelProvider,
)
from tau_ai.env import DEFAULT_OPENAI_COMPATIBLE_BASE_URL
from tau_coding import __version__
from tau_coding.provider_config import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER_NAME,
    OpenAICompatibleProviderConfig,
    ProviderSettings,
    load_provider_settings,
    provider_kind,
    resolve_provider_selection,
    save_provider_settings,
    upsert_openai_compatible_provider,
)
from tau_coding.provider_runtime import create_model_provider
from tau_coding.rendering import PrintOutputMode, create_event_renderer
from tau_coding.resources import TauResourcePaths
from tau_coding.session import CodingSession, CodingSessionConfig, jsonl_session_storage
from tau_coding.session_manager import CodingSessionRecord, SessionManager
from tau_coding.tui import run_tui_app

app = typer.Typer(
    name="tau",
    help="Tau coding-agent harness.",
    add_completion=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)


def providers_command() -> None:
    """List configured model providers."""
    render_provider_settings(load_provider_settings())


def setup_command(
    *,
    provider_name: str = DEFAULT_PROVIDER_NAME,
    base_url: str = DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
    api_key_env: str = "OPENAI_API_KEY",
    model: str = DEFAULT_MODEL,
    timeout_seconds: float = DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES,
    max_retry_delay_seconds: float = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS,
    set_default: bool = True,
) -> None:
    """Create or update an OpenAI-compatible provider entry."""
    settings = load_provider_settings()
    provider = OpenAICompatibleProviderConfig(
        name=provider_name,
        base_url=base_url.rstrip("/"),
        api_key_env=api_key_env,
        models=(model,),
        default_model=model,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        max_retry_delay_seconds=max_retry_delay_seconds,
    )
    updated = upsert_openai_compatible_provider(settings, provider, set_default=set_default)
    path = save_provider_settings(updated)
    typer.echo(f"Saved provider '{provider.name}' to {path}")
    if provider.api_key_env not in environ:
        typer.echo(f"Set {provider.api_key_env} before running Tau with this provider.", err=True)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    prompt_arg: Annotated[
        str | None,
        typer.Argument(help="Initial prompt to run in interactive TUI mode."),
    ] = None,
    prompt_option: Annotated[
        str | None,
        typer.Option("--prompt", "-p", help="Prompt to run in non-interactive print mode."),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="Configured provider name to use."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model name to request from the provider."),
    ] = None,
    setup_base_url: Annotated[
        str,
        typer.Option("--base-url", help="OpenAI-compatible base URL for `tau setup`."),
    ] = DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
    setup_api_key_env: Annotated[
        str,
        typer.Option("--api-key-env", help="API key environment variable for `tau setup`."),
    ] = "OPENAI_API_KEY",
    setup_timeout_seconds: Annotated[
        float,
        typer.Option(
            "--timeout-seconds",
            help="HTTP timeout in seconds for `tau setup` provider requests.",
        ),
    ] = DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS,
    setup_max_retries: Annotated[
        int,
        typer.Option("--max-retries", help="Provider retry count for `tau setup`."),
    ] = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES,
    setup_max_retry_delay_seconds: Annotated[
        float,
        typer.Option(
            "--max-retry-delay-seconds",
            help="Provider retry delay in seconds for `tau setup`.",
        ),
    ] = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS,
    setup_default: Annotated[
        bool,
        typer.Option("--set-default/--no-set-default", help="Make setup provider the default."),
    ] = True,
    cwd: Annotated[
        Path | None,
        typer.Option("--cwd", help="Working directory for built-in coding tools."),
    ] = None,
    output: Annotated[
        PrintOutputMode,
        typer.Option("--output", "-o", help="Output mode for print mode."),
    ] = PrintOutputMode.text,
    resume: Annotated[
        str | None,
        typer.Option("--resume", help="Resume a session id in TUI mode."),
    ] = None,
    new_session: Annotated[
        bool,
        typer.Option("--new-session", help="Create a new session in TUI mode (default)."),
    ] = False,
    auto_compact_threshold: Annotated[
        int | None,
        typer.Option(
            "--auto-compact-threshold",
            help="Automatically compact TUI context above this rough token estimate.",
        ),
    ] = None,
    version: Annotated[
        bool,
        typer.Option("--version", help="Show Tau's version and exit."),
    ] = False,
) -> None:
    """Run the Tau CLI."""
    if version:
        typer.echo(f"tau {__version__}")
        raise typer.Exit()

    if ctx.invoked_subcommand is not None:
        return

    if prompt_option is None and prompt_arg == "sessions":
        render_session_list(SessionManager().list_sessions())
        raise typer.Exit()

    if prompt_option is None and prompt_arg == "providers":
        providers_command()
        raise typer.Exit()

    if prompt_option is None and prompt_arg == "setup":
        setup_command(
            provider_name=provider or DEFAULT_PROVIDER_NAME,
            base_url=setup_base_url,
            api_key_env=setup_api_key_env,
            model=model or DEFAULT_MODEL,
            timeout_seconds=setup_timeout_seconds,
            max_retries=setup_max_retries,
            max_retry_delay_seconds=setup_max_retry_delay_seconds,
            set_default=setup_default,
        )
        raise typer.Exit()

    if prompt_option is None:
        try:
            anyio.run(
                run_openai_tui,
                model,
                cwd or Path.cwd(),
                resume,
                new_session,
                provider,
                auto_compact_threshold,
                prompt_arg,
            )
        except RuntimeError as exc:
            raise typer.BadParameter(str(exc)) from exc
        raise typer.Exit()

    prompt = prompt_option
    if prompt is None:
        raise AssertionError("prompt option should be set outside TUI mode")

    try:
        ok = anyio.run(run_openai_print_mode, prompt, model, cwd or Path.cwd(), output, provider)
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if not ok:
        raise typer.Exit(1)


async def run_openai_tui(
    model: str | None,
    cwd: Path,
    session_id: str | None = None,
    new_session: bool = False,
    provider_name: str | None = None,
    auto_compact_token_threshold: int | None = None,
    initial_prompt: str | None = None,
) -> None:
    """Run the Textual TUI with the default OpenAI-compatible provider."""
    await run_tui_app(
        model=model,
        cwd=cwd,
        session_id=session_id,
        new_session=new_session,
        provider_name=provider_name,
        auto_compact_token_threshold=auto_compact_token_threshold,
        initial_prompt=initial_prompt,
    )


def render_session_list(records: list[CodingSessionRecord]) -> None:
    """Render indexed sessions for the CLI."""
    if not records:
        typer.echo("No sessions found.")
        return

    for record in records:
        title = record.title or "Untitled"
        typer.echo(f"{record.id}\t{title}\t{record.model}\t{record.cwd}")


def render_provider_settings(settings: ProviderSettings) -> None:
    """Render configured providers for the CLI."""
    for provider in settings.providers:
        marker = "*" if provider.name == settings.default_provider else " "
        models = ",".join(provider.models)
        typer.echo(
            f"{marker}\t{provider.name}\t{provider_kind(provider)}\t"
            f"{provider.default_model}\t{models}\t{provider.api_key_env}\t"
            f"{provider.base_url}\t{provider.timeout_seconds:g}s\t"
            f"retries={provider.max_retries}\t"
            f"retry_delay={provider.max_retry_delay_seconds:g}s"
        )


async def run_openai_print_mode(
    prompt: str,
    model: str | None,
    cwd: Path,
    output: PrintOutputMode = PrintOutputMode.text,
    provider_name: str | None = None,
    session_manager: SessionManager | None = None,
) -> bool:
    """Run print mode with the OpenAI-compatible provider configured from the environment."""
    settings = load_provider_settings()
    selection = resolve_provider_selection(settings, provider_name=provider_name, model=model)
    provider = create_model_provider(selection.provider)
    manager = session_manager or SessionManager()
    record = manager.create_session(cwd=cwd, model=selection.model)
    try:
        return await run_print_mode(
            prompt=prompt,
            model=selection.model,
            cwd=record.cwd,
            provider=provider,
            output=output,
            storage=jsonl_session_storage(record.path),
            session_id=record.id,
            session_manager=manager,
            provider_name=selection.provider.name,
            provider_settings=settings,
        )
    finally:
        await provider.aclose()


async def run_print_mode(
    *,
    prompt: str,
    model: str,
    cwd: Path,
    provider: ModelProvider,
    output: PrintOutputMode = PrintOutputMode.text,
    resource_paths: TauResourcePaths | None = None,
    storage: SessionStorage | None = None,
    session_id: str | None = None,
    session_manager: SessionManager | None = None,
    provider_name: str = DEFAULT_PROVIDER_NAME,
    provider_settings: ProviderSettings | None = None,
) -> bool:
    """Run one non-interactive prompt and print streamed events.

    Returns False when the agent emits a non-recoverable error so CLI callers
    can fail non-interactive runs while still rendering the error message.
    """
    session = await CodingSession.load(
        CodingSessionConfig(
            provider=provider,
            model=model,
            cwd=cwd,
            storage=storage or _MemorySessionStorage(),
            resource_paths=resource_paths,
            session_id=session_id,
            session_manager=session_manager,
            provider_name=provider_name,
            provider_settings=provider_settings,
        )
    )
    renderer = create_event_renderer(output)
    try:
        async for event in session.prompt(prompt):
            renderer.render(event)
        return renderer.finish()
    finally:
        await session.aclose()


class _MemorySessionStorage:
    """Append-only in-memory storage for direct print-mode tests."""

    def __init__(self) -> None:
        self.entries: list[SessionEntry] = []

    async def append(self, entry: SessionEntry) -> None:
        self.entries.append(entry)

    async def read_all(self) -> list[SessionEntry]:
        return list(self.entries)
