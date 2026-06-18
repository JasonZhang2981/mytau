# Installation

Tau is packaged as a Python console application named `tau`.

## Install With uv

From a checked-out copy of the repository:

```bash
uv tool install --editable .
```

From GitHub:

```bash
uv tool install git+https://github.com/alejandro-ao/tau.git
```

Verify the installed command:

```bash
tau --version
```

## Install With pipx

```bash
pipx install git+https://github.com/alejandro-ao/tau.git
```

## First Run

Tau starts the interactive Textual TUI when no prompt is provided:

```bash
tau
```

Passing a positional prompt also starts the TUI and submits that prompt as the
first turn:

```bash
tau "explain this repository"
```

For a one-shot print-mode prompt:

```bash
tau -p "explain this repository"
```

Print-mode prompts create indexed session entries under `~/.tau/sessions/` while
keeping stdout/stderr script-friendly.

Tau includes built-in provider entries for OpenAI, Anthropic, OpenRouter, and
Hugging Face Inference Providers. In the TUI, run `/login` to see them and
`/login openai` to save an API key.

Saved API keys live in `~/.tau/credentials.json` with private file permissions.
Environment variables such as `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`OPENROUTER_API_KEY`, and `HF_TOKEN` still work and take precedence.

Optionally configure a custom provider:

```bash
tau --provider local \
  --base-url http://localhost:11434/v1 \
  --api-key-env LOCAL_API_KEY \
  --model qwen \
  setup
```

Custom providers still read the API key from the configured environment
variable, such as `LOCAL_API_KEY` in the example above.

Then run:

```bash
tau --provider local
```

## Shell Completion

Shell completion is not enabled yet. The Typer application is currently created
with completion disabled so the command surface can stay stable while Tau is
still moving through the roadmap.
