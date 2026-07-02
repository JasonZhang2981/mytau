# Phase 6 学习笔记：Non-interactive Print-mode CLI

对应架构文档：`dev-notes/architecture/phase-6-print-mode-cli.md`

对应源码：

- `src/tau_coding/cli.py`
- `src/tau_coding/rendering/base.py`
- `src/tau_coding/rendering/plain.py`
- `src/tau_coding/rendering/json.py`
- `src/tau_coding/rendering/transcript.py`
- `src/tau_coding/session.py`
- `tests/test_cli.py`
- `pyproject.toml`

前置阶段：

- Phase 2：`tau_ai` 能创建 provider 并流式返回 ProviderEvent
- Phase 4：`AgentHarness` 能运行 prompt
- Phase 5：`tau_coding` 有 read/write/edit/bash 工具

## 1. 这一阶段到底在做什么

Phase 6 的目标是让 Tau 第一次能作为命令行工具真正使用。

也就是说，用户可以运行：

```bash
tau -p "explain this repo"
tau --prompt "write tests for main.py"
tau --model gpt-5.5 -p "summarize README.md"
```

这叫 non-interactive print mode。

non-interactive 的意思是：只跑一个 prompt，输出结果，然后退出。

print mode 的意思是：直接把结果打印到终端，而不是打开完整 TUI。

## 2. Phase 6 的历史实现和当前实现

架构文档说，Phase 6 最初的 CLI 大概是这样：

```text
读取 provider 配置
创建 coding tools
构建最小 system prompt
创建 AgentHarness
调用 prompt()
把 assistant 文本打印到 stdout
把工具摘要打印到 stderr
```

当前源码已经演进了。

现在 print mode 不是直接创建 `AgentHarness`，而是创建更高层的 `CodingSession`。

当前主线是：

```text
tau -p "..."
        ↓
Typer CLI 解析参数
        ↓
run_openai_print_mode()
        ↓
解析 provider/model/settings
        ↓
创建 SessionManager 和 session record
        ↓
run_print_mode()
        ↓
CodingSession.load()
        ↓
session.prompt()
        ↓
renderer.render(event)
        ↓
renderer.finish()
```

这样 print mode 和 TUI 能共用更多能力：

- shared system prompt
- project instructions discovery
- skills / prompt templates
- built-in coding tools
- session persistence
- provider/model resolution
- provider timeout/retry settings
- shell command prefix
- renderer 输出模式

## 3. CLI 入口来自哪里

`pyproject.toml` 里有：

```toml
[project.scripts]
tau = "tau_coding.cli:app"
```

这表示安装这个包后，系统会生成一个命令：

```bash
tau
```

执行时会加载：

```python
tau_coding.cli:app
```

也就是 `src/tau_coding/cli.py` 里的 Typer app。

## 4. `cli.py` 顶部导入怎么看

源码开头：

```python
from os import environ
from pathlib import Path
from typing import Annotated

import anyio
import typer
```

### 4.1 `typer`

Typer 是 Python CLI 框架。

它可以把函数参数变成命令行参数。

比如：

```python
prompt_option: Annotated[
    str | None,
    typer.Option("--prompt", "-p", help="Prompt to run in non-interactive print mode."),
] = None
```

对应命令行：

```bash
tau -p "hello"
tau --prompt "hello"
```

### 4.2 `anyio`

Typer 的命令入口是普通同步函数。

但 Tau 的核心运行是 async。

所以 CLI 里用：

```python
anyio.run(run_openai_print_mode, ...)
```

把 async 函数跑起来。

可以简单理解为：`anyio.run()` 是同步 CLI 和异步 agent 代码之间的桥。

### 4.3 `Annotated`

`Annotated` 用来给类型附加 Typer 参数说明。

比如：

```python
model: Annotated[
    str | None,
    typer.Option("--model", "-m", help="Model name to request from the provider."),
] = None
```

它的普通类型是：

```python
str | None
```

但额外告诉 Typer：

```text
这是 --model / -m 参数
help 文案是 ...
```

### 4.4 `Path`

CLI 的 `--cwd` 参数使用 `Path`：

```python
cwd: Annotated[
    Path | None,
    typer.Option("--cwd", help="Working directory for built-in coding tools."),
] = None
```

这样 Typer 会把命令行里的路径字符串转换成 `Path` 对象。

## 5. Typer app

源码：

```python
app = typer.Typer(
    name="tau",
    help="Tau coding-agent harness.",
    add_completion=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
```

这创建了 CLI app。

参数解释：

- `name="tau"`：命令名
- `help=...`：帮助说明
- `add_completion=False`：不自动添加 shell completion 命令
- `allow_extra_args=True`：允许额外参数
- `ignore_unknown_options=True`：允许某些未知选项先不被 Typer 拦截

后面两个设置和当前 CLI 支持 `export` 等伪子命令有关。

## 6. `@app.callback(invoke_without_command=True)`

源码：

```python
@app.callback(invoke_without_command=True)
def main(...):
    ...
```

Typer 的 callback 是入口函数。

`invoke_without_command=True` 表示：即使没有明确子命令，也会执行这个函数。

所以这些都会进 `main()`：

```bash
tau
tau -p "hello"
tau "explain this repo"
tau --version
tau sessions
```

## 7. `main()` 的关键参数

### 7.1 positional prompt

```python
prompt_args: Annotated[
    list[str] | None,
    typer.Argument(help="Initial prompt to run in interactive TUI mode."),
] = None
```

这代表位置参数。

比如：

```bash
tau explain this repo
```

会进入 `prompt_args`。

当前逻辑里，位置参数不是 print mode，而是 TUI 的 initial prompt。

### 7.2 print-mode prompt

```python
prompt_option: Annotated[
    str | None,
    typer.Option("--prompt", "-p", help="Prompt to run in non-interactive print mode."),
] = None
```

只有使用 `-p` 或 `--prompt` 才是 print mode。

### 7.3 provider 和 model

```python
provider: str | None
model: str | None
```

用于选择 provider 和模型。

### 7.4 cwd

```python
cwd: Path | None
```

工具和 session 的工作目录。

如果不传，就用当前目录：

```python
cwd or Path.cwd()
```

### 7.5 output

```python
output: PrintOutputMode = PrintOutputMode.text
```

print mode 支持三种输出：

- `text`
- `json`
- `transcript`

## 8. `main()` 的分支逻辑

`main()` 里面最重要的是这些分支。

### 8.1 `--version`

```python
if version:
    typer.echo(f"tau {__version__}")
    raise typer.Exit()
```

测试里：

```python
result = CliRunner().invoke(app, ["--version"])
assert result.stdout.strip() == "tau 0.1.0"
```

### 8.2 没有 `-p` 时进入 TUI

```python
if prompt_option is None:
    anyio.run(run_openai_tui, ...)
    raise typer.Exit()
```

所以：

```bash
tau
```

会启动 TUI。

而：

```bash
tau "explain this repo"
```

会启动 TUI，并把 `"explain this repo"` 当作初始 prompt。

测试里验证了这两个行为。

### 8.3 有 `-p` 时进入 print mode

```python
prompt = prompt_option
ok = anyio.run(run_openai_print_mode, prompt, model, cwd or Path.cwd(), output, provider)
if not ok:
    raise typer.Exit(1)
```

如果 `run_openai_print_mode()` 返回 False，CLI 用 exit code 1 退出。

这对脚本很重要。

脚本可以根据 exit code 判断是否成功。

## 9. 当前 CLI 里还有哪些后续命令

当前 `main()` 里也处理：

- `tau sessions`
- `tau export ...`
- `tau providers`
- `tau setup`

这些不完全属于原始 Phase 6 主线，属于后续 CLI 能力。

这一讲先重点理解：

```bash
tau -p "..."
```

和：

```bash
tau
```

之间的分流。

## 10. `run_openai_print_mode()`

源码主线：

```python
async def run_openai_print_mode(
    prompt: str,
    model: str | None,
    cwd: Path,
    output: PrintOutputMode = PrintOutputMode.text,
    provider_name: str | None = None,
    session_manager: SessionManager | None = None,
) -> bool:
    settings = load_provider_settings()
    shell_settings = load_shell_settings()
    selection = resolve_provider_selection(settings, provider_name=provider_name, model=model)
    provider = create_model_provider(...)
    manager = session_manager or SessionManager()
    record = manager.create_session(cwd=cwd, model=selection.model)
    try:
        return await run_print_mode(...)
    finally:
        await provider.aclose()
```

它负责真实 provider 运行所需的外部配置：

1. 加载 provider settings
2. 加载 shell settings
3. 根据 provider/model 选择具体 provider config
4. 创建 provider runtime
5. 创建 session record
6. 调用 `run_print_mode()`
7. 最后关闭 provider

### 10.1 为什么有 `try ... finally`

provider 可能持有 HTTP client。

即使 run_print_mode 出错，也应该关闭 provider：

```python
finally:
    await provider.aclose()
```

这是一种资源清理模式。

## 11. `run_print_mode()`

这是 Phase 6 当前实现的核心函数。

源码：

```python
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
    runtime_provider_config: ProviderConfig | None = None,
    shell_command_prefix: str | None = None,
) -> bool:
```

注意它全部是 keyword-only 参数，因为开头有 `*`。

这样调用时必须写清楚：

```python
await run_print_mode(
    prompt="Say hello",
    model="fake",
    cwd=tmp_path,
    provider=provider,
)
```

## 12. `CodingSession.load()`

`run_print_mode()` 第一件大事：

```python
session = await CodingSession.load(
    CodingSessionConfig(
        provider=provider,
        model=model,
        cwd=cwd,
        storage=storage or _MemorySessionStorage(),
        ...
    )
)
```

为什么用 `CodingSession`？

因为当前 print mode 要和 TUI 共用 coding-agent 环境。

`CodingSession.load()` 会负责：

- 读取 session storage
- 创建默认 session entries
- 创建默认 coding tools
- 发现项目 instructions
- 加载 skills 和 prompt templates
- 构建 shared system prompt
- 创建 `AgentHarness`

这比原始 Phase 6 直接创建 `AgentHarness` 更完整。

## 13. `_MemorySessionStorage`

源码：

```python
class _MemorySessionStorage:
    def __init__(self) -> None:
        self.entries: list[SessionEntry] = []

    async def append(self, entry: SessionEntry) -> None:
        self.entries.append(entry)

    async def read_all(self) -> list[SessionEntry]:
        return list(self.entries)
```

这是测试和直接 print mode 用的内存 storage。

如果没有传入真实 storage，`run_print_mode()` 就用它。

它实现了最小 storage 接口：

- `append()`
- `read_all()`

### 13.1 为什么 append/read_all 是 async

真实 storage 可能读写文件。

为了接口一致，即使内存版很简单，也写成 async。

## 14. renderer：输出模式

`run_print_mode()` 创建 renderer：

```python
renderer = create_event_renderer(output)
```

源码：

```python
def create_event_renderer(mode: PrintOutputMode) -> EventRenderer:
    if mode is PrintOutputMode.text:
        return FinalTextRenderer()
    if mode is PrintOutputMode.json:
        return JsonEventRenderer()
    return TranscriptRenderer()
```

对应三种输出：

```text
text       FinalTextRenderer
json       JsonEventRenderer
transcript TranscriptRenderer
```

## 15. `PrintOutputMode`

源码：

```python
class PrintOutputMode(StrEnum):
    text = "text"
    json = "json"
    transcript = "transcript"
```

`StrEnum` 是字符串枚举。

也就是说：

```python
PrintOutputMode.text
```

本质上也可以当字符串 `"text"` 用。

Typer 可以把命令行参数：

```bash
--output json
```

解析成对应枚举值。

## 16. `FinalTextRenderer`

这是默认 print mode。

源码主线：

```python
class FinalTextRenderer:
    def __init__(self) -> None:
        self._last_assistant_text = ""
        self._failed = False
        self._error_messages: list[str] = []
```

它不是边流边打印，而是记录最后一条 assistant message：

```python
if isinstance(event, MessageEndEvent):
    self._last_assistant_text = event.message.content
```

结束时：

```python
if self._failed:
    typer.echo(f"Error: {message}", err=True)
    return False

if self._last_assistant_text:
    typer.echo(self._last_assistant_text)
return True
```

### 16.1 stdout 和 stderr

`typer.echo(text)` 默认输出到 stdout。

```python
typer.echo(f"Error: {message}", err=True)
```

输出到 stderr。

测试里：

```python
assert captured.out == "Hello\n"
assert captured.err == ""
```

错误时：

```python
assert "Error: provider failed" in captured.err
```

## 17. `JsonEventRenderer`

源码：

```python
class JsonEventRenderer:
    def render(self, event: AgentEvent) -> None:
        if isinstance(event, ErrorEvent) and not event.recoverable:
            self._failed = True
        typer.echo(event.model_dump_json())
```

它把每个 `AgentEvent` 都输出成一行 JSON。

这适合脚本或其他程序消费。

比如测试检查：

```python
assert '"type":"agent_start"' in captured.out
assert '"type":"message_delta"' in captured.out
```

## 18. `TranscriptRenderer`

`TranscriptRenderer` 是更像实时 transcript 的输出方式。

它会：

- 对 `MessageDeltaEvent` 立即打印 delta 到 stdout
- 对工具开始/结束打印摘要到 stderr
- 对 retry 打印状态到 stderr
- 对错误打印到 stderr

它用到了 `rich.console.Console(stderr=True)`。

这说明工具活动、错误、重试这些辅助信息走 stderr，assistant 文本走 stdout。

## 19. terminal command 特殊逻辑

`run_print_mode()` 里有：

```python
terminal_command = parse_terminal_command(prompt)
if terminal_command is not None:
    result = await session.run_terminal_command(...)
    typer.echo(_format_terminal_command_result(result))
    return result.ok
```

这表示 print mode 支持直接跑终端命令。

测试里：

```python
prompt="! printf hello"
```

会执行命令，并把结果加入上下文。

```python
prompt="!! printf hidden"
```

会执行命令，但不加入上下文。

这个能力是当前源码后续增强，不是原始 Phase 6 最小主线。

## 20. 普通 prompt 流程

如果不是 terminal command：

```python
async for event in session.prompt(prompt):
    renderer.render(event)
return renderer.finish()
```

这就是 print mode 的核心。

它消费 `CodingSession.prompt()` 产生的 agent events。

每个 event 交给 renderer。

最后 renderer 决定：

- 是否打印最终文本
- 是否失败
- 返回 True/False

## 21. session persistence

当前 print mode 会保存 session。

`run_openai_print_mode()` 里：

```python
record = manager.create_session(cwd=cwd, model=selection.model)
```

然后把 storage 传给 `run_print_mode()`。

测试里也直接传：

```python
storage = JsonlSessionStorage(tmp_path / "print-session.jsonl")
```

运行后读取：

```python
entries = await storage.read_all()
messages = [entry.message for entry in entries if isinstance(entry, MessageEntry)]
```

断言：

```python
assert [message.role for message in messages] == ["user", "assistant"]
```

这说明 print mode 不只是打印，也会留下 session entries。

## 22. project instructions

测试里：

```python
(tmp_path / "AGENTS.md").write_text("Use the local rules.", encoding="utf-8")
```

然后 run_print_mode。

断言 provider 收到的 system prompt 里有：

```text
Use the local rules.
```

以及：

```text
<project_instructions path=".../AGENTS.md">
```

这说明当前 print mode 通过 `CodingSession` 共用了项目 instructions 发现和 system prompt 构建能力。

## 23. skill command expansion

测试里创建：

```text
resources/skills/testing.md
```

然后 prompt：

```text
/skill:testing add tests
```

最终 provider 收到的 user message 不是原始文本，而是展开后的内容：

```text
<skill name="testing" location="...">
...
</skill>

add tests
```

这也是当前 print mode 通过 `CodingSession` 获得的能力。

## 24. `run_openai_tui()`

如果没有 `-p`，CLI 会调用：

```python
async def run_openai_tui(...):
    await run_tui_app(...)
```

Phase 6 的重点不是 TUI。

但当前 CLI 默认模式已经是 TUI：

```bash
tau
```

进入 TUI。

```bash
tau "explain this repo"
```

进入 TUI，并带 initial prompt。

这是后续阶段演进后的行为。

## 25. provider setup 和 providers 命令

当前 `cli.py` 还包含：

- `providers_command()`
- `setup_command()`
- `render_provider_settings()`

这些用于配置和查看 provider。

例如 `setup_command()` 会创建或更新 OpenAI-compatible provider entry。

这不属于原始 Phase 6 最小 print-mode 核心，但它解释了为什么当前 `cli.py` 顶部有很多 provider config 相关导入。

## 26. tests/test_cli.py 怎么读

这份测试很长，因为 CLI 已经包含很多后续能力。

Phase 6 主线建议先看这些。

### 26.1 version

```python
test_version_command
```

验证：

```bash
tau --version
```

输出：

```text
tau 0.1.0
```

### 26.2 没有 -p 进入 TUI

```python
test_cli_without_prompt_invokes_tui_runner
test_cli_positional_prompt_invokes_tui_runner
```

验证：

- `tau` 进入 TUI
- `tau "explain this repo"` 进入 TUI，并传 initial prompt

### 26.3 print mode 基础输出

```python
test_run_print_mode_prints_final_assistant_text
```

验证：

- FakeProvider 返回 Hello
- print mode 最终 stdout 是 `Hello\n`
- provider 收到 shared system prompt
- provider 收到 read/write/edit/bash 工具

### 26.4 print mode 错误

```python
test_run_print_mode_fails_on_non_recoverable_error
test_cli_exits_nonzero_when_print_mode_fails
```

验证：

- provider error 会输出到 stderr
- print mode 返回 False
- CLI exit code 为 1

### 26.5 project instructions 和 session

```python
test_run_print_mode_includes_discovered_context
test_run_print_mode_persists_session_entries
```

验证当前 print mode 共享 CodingSession 环境。

### 26.6 output modes

```python
test_run_print_mode_can_emit_json_events
test_run_print_mode_can_emit_live_transcript
```

验证：

- `--output json` 输出 JSONL events
- `--output transcript` 实时输出 assistant delta

## 27. Phase 6 里用到的 Python 包和语法

### 27.1 Typer

用途：创建命令行应用。

关键对象：

- `typer.Typer`
- `typer.Option`
- `typer.Argument`
- `typer.echo`
- `typer.Exit`
- `typer.BadParameter`

### 27.2 anyio

用途：从同步 CLI 入口运行 async 函数。

```python
anyio.run(run_openai_print_mode, ...)
```

### 27.3 Annotated

把类型和 CLI metadata 放一起。

```python
Annotated[str | None, typer.Option("--model", "-m")]
```

### 27.4 pytest 的 monkeypatch

测试 CLI 时不想真的打开 TUI。

所以测试里：

```python
monkeypatch.setattr(cli, "run_openai_tui", fake_run_openai_tui)
```

把真实函数替换成 fake 函数。

### 27.5 CliRunner

来自 Typer/Click 测试体系：

```python
result = CliRunner().invoke(app, ["--version"])
```

它可以像真实命令行一样调用 Typer app。

### 27.6 capsys

pytest fixture，用于捕获 stdout/stderr。

```python
captured = capsys.readouterr()
assert captured.out == "Hello\n"
```

## 28. 小白必须分清的几组概念

### 28.1 `tau "prompt"` 不是 print mode

当前 CLI 中：

```bash
tau "explain this repo"
```

是 TUI initial prompt。

真正 print mode 是：

```bash
tau -p "explain this repo"
```

### 28.2 `run_openai_print_mode()` 不是 `run_print_mode()`

`run_openai_print_mode()` 负责真实配置：

- provider settings
- model selection
- session record
- provider runtime

`run_print_mode()` 负责已经拿到 provider 后的一次 prompt 执行。

测试常直接测 `run_print_mode()`，因为可以传 FakeProvider。

### 28.3 renderer 不负责运行 agent

renderer 只消费 events 并输出。

真正运行 prompt 的是：

```python
session.prompt(prompt)
```

### 28.4 stdout 和 stderr 不一样

assistant 最终文本通常走 stdout。

错误、工具活动、retry 等辅助信息常走 stderr。

这样脚本可以更容易区分“结果文本”和“诊断信息”。

### 28.5 print mode 当前已经不是最小 harness demo

当前 print mode 是基于 `CodingSession` 的完整 coding-agent 环境。

这让它比原始 Phase 6 更复杂，但也更不容易和 TUI 行为漂移。

## 29. 运行测试

Phase 6 最相关测试：

```text
tests/test_cli.py
```

运行：

```bash
uv run pytest tests/test_cli.py
```

这组测试覆盖：

- `tau --version`
- 无 `-p` 时启动 TUI
- 位置 prompt 作为 TUI initial prompt
- print mode 最终文本输出
- provider error 失败路径
- project instructions 注入 system prompt
- session persistence
- terminal command
- skill command expansion
- JSON event output
- live transcript output
- print mode 失败时 CLI exit code
- sessions/export/providers/setup 等后续 CLI 能力

## 30. 用一句话总结 Phase 6

Phase 6 的价值是：把前面已经完成的 provider、agent harness、coding tools 和渲染逻辑接到 `tau` 命令上，让用户可以用 `tau -p "..."` 非交互式运行一次 coding-agent prompt，并把结果以文本、JSON events 或实时 transcript 的形式输出。

## 31. 我的问题与推荐回答

问题：为什么当前 print mode 要走 `CodingSession`，而不是像最早 Phase 6 那样直接创建 `AgentHarness`？

我的推荐回答：

因为 `AgentHarness` 只负责通用 agent 大脑，而 print mode 作为 coding-agent 产品入口，需要更多环境能力：项目 instructions、skills、prompt templates、默认 coding tools、session persistence、provider/model 配置、shell command prefix 等。让 print mode 走 `CodingSession`，可以和 TUI 共用同一套 coding-agent 环境，减少两种入口之间的行为漂移；同时 `tau_agent` 仍然保持干净，不依赖 CLI、文件路径、Rich/Textual 或 session 存储。
