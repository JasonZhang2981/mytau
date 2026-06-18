# Getting Started

This page explains how to install Tau, run the TUI, and work on the project.

## Requirements

Tau targets the Python version declared in `pyproject.toml` and uses `uv` for
dependency management.

## Install As a Tool

From GitHub:

```bash
uv tool install git+https://github.com/alejandro-ao/tau.git
```

From a local checkout:

```bash
uv tool install --editable .
```

Verify the installed command:

```bash
tau --version
```

## Local Development Setup

```bash
uv sync --dev --group docs
```

## Verify the CLI

```bash
uv run tau --version
```

Expected output:

```text
tau 0.1.0
```

## Configure a Provider

Tau includes built-in provider entries for OpenAI, Anthropic, OpenRouter, and
Hugging Face Inference Providers. In the TUI, run `/login` to see the list and
`/login openai` to save an API key for a provider.

Provider metadata is written to `~/.tau/providers.json`. API keys saved with
`/login` are written to `~/.tau/credentials.json` with private file permissions.
Environment variables such as `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`OPENROUTER_API_KEY`, and `HF_TOKEN` still work and take precedence.

To add a custom OpenAI-compatible provider:

```bash
uv run tau --provider local \
  --base-url http://localhost:11434/v1 \
  --api-key-env LOCAL_API_KEY \
  --model qwen \
  setup
```

## Open the TUI

```bash
uv run tau
```

Installed as a tool:

```bash
tau
```

Tau stores indexed sessions under `~/.tau/sessions/`.

## Run an Initial Prompt in the TUI

```bash
uv run tau "explain this repository"
```

This opens the interactive TUI and submits the prompt as the first turn.

For a one-shot print-mode prompt, use `-p`:

```bash
uv run tau -p "explain this repository"
```

Print-mode prompts are non-interactive, but they still use the shared
coding-session environment. Tau stores their session entries under
`~/.tau/sessions/`.

## Run tests and checks

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

## Run the documentation site locally

```bash
uv run --group docs mkdocs serve
```

Then open:

```text
http://127.0.0.1:8000
```

## Build the documentation site

```bash
uv run --group docs mkdocs build
```

The generated static website is written to `site/`.

## Deployment

Documentation is deployed to GitHub Pages from the `main` branch using the workflow in:

```text
.github/workflows/docs.yml
```

The public site is configured for:

```text
https://alejandro-ao.github.io/tau/
```
