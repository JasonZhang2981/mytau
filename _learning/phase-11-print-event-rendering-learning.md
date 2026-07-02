# Phase 11 学习笔记：Print and Event Rendering Modes

对应架构文档：`dev-notes/architecture/phase-11-print-event-rendering.md`

主要源码：

- `src/tau_coding/rendering/base.py`
- `src/tau_coding/rendering/plain.py`
- `src/tau_coding/rendering/json.py`
- `src/tau_coding/rendering/transcript.py`
- `src/tau_coding/rendering/__init__.py`
- `src/tau_coding/cli.py`
- `tests/test_rendering.py`
- `tests/test_cli.py`

前置阶段：

- Phase 1：定义 `AgentEvent`
- Phase 3：agent loop 会产生事件流
- Phase 6：print-mode CLI 可以跑一次 prompt
- Phase 8：`CodingSession.prompt()` 对外暴露异步事件流
- Phase 11：把事件流渲染成不同 CLI 输出模式

## 1. 这一阶段到底在做什么

Phase 11 增加了一个小但很关键的边界：

```text
AgentEvent stream
  -> EventRenderer
  -> stdout / stderr / JSONL
```

前面阶段里，agent 会不断产生事件：

- `AgentStartEvent`
- `MessageStartEvent`
- `MessageDeltaEvent`
- `MessageEndEvent`
- `ToolExecutionStartEvent`
- `ToolExecutionUpdateEvent`
- `ToolExecutionEndEvent`
- `ErrorEvent`

但“事件怎么显示给用户看”不应该由 agent loop 决定。

所以 Phase 11 在 `tau_coding.rendering` 里加入 renderer：

- `FinalTextRenderer`
- `JsonEventRenderer`
- `TranscriptRenderer`

它们都消费同一套 `AgentEvent`，但输出方式不同。

## 2. 为什么需要渲染边界

项目核心原则是：

```text
tau_agent = portable event-producing harness
tau_coding = CLI/session/UI application layer
```

`tau_agent` 只负责产出事件。

它不应该知道：

- stdout
- stderr
- Typer
- Rich
- JSON Lines
- 终端颜色
- print mode 的用户体验
- TUI 的渲染策略

这些都是前端或应用层选择。

所以 Phase 11 的方向是：

```text
AgentHarness / CodingSession 产生事件
Renderer 决定如何展示事件
```

这也为后面的 Textual TUI 打基础：

```text
print mode renderer 是事件消费者
TUI 以后也是事件消费者
```

## 3. 当前渲染模块结构

架构文档写的是：

```text
src/tau_coding/rendering/
```

当前源码确实是一个包，不是单个文件：

```text
src/tau_coding/rendering/
  __init__.py
  base.py
  plain.py
  json.py
  transcript.py
```

每个文件职责：

```text
base.py       定义 PrintOutputMode 和 EventRenderer 协议
plain.py      最终文本输出
json.py       JSON Lines 输出
transcript.py 人类可读的实时 transcript 输出
__init__.py   统一导出和 renderer factory
```

## 4. base.py：PrintOutputMode

源码：

```python
from enum import StrEnum

class PrintOutputMode(StrEnum):
    """Output modes supported by non-interactive print mode."""

    text = "text"
    json = "json"
    transcript = "transcript"
```

`PrintOutputMode` 表示 print mode 的输出模式。

CLI 里可以通过参数选择：

```bash
tau --output text "summarize this project"
tau --output json "summarize this project"
tau --output transcript "summarize this project"
```

默认是：

```python
PrintOutputMode.text
```

## 5. Python 知识：StrEnum

`StrEnum` 来自标准库：

```python
from enum import StrEnum
```

它是“值也是字符串的枚举”。

普通字符串容易写错：

```python
output = "jsno"  # 拼错了
```

枚举更安全：

```python
output = PrintOutputMode.json
```

而 `StrEnum` 的值仍然像字符串：

```python
PrintOutputMode.json.value == "json"
```

这对 CLI 参数特别方便。

Typer 可以把命令行里的：

```text
--output json
```

解析成：

```python
PrintOutputMode.json
```

## 6. base.py：EventRenderer 协议

源码：

```python
from typing import Protocol

class EventRenderer(Protocol):
    """Consumes agent events and renders them for a frontend or output mode."""

    def render(self, event: AgentEvent) -> None:
        """Render one event."""

    def finish(self) -> bool:
        """Finish rendering and return whether the run succeeded."""
```

这是一个协议。

它规定：

任何 renderer 只要实现两个方法，就可以当作 `EventRenderer` 使用：

```python
render(event)
finish()
```

具体类不需要显式继承：

```python
class FinalTextRenderer:
    def render(...): ...
    def finish(...): ...
```

只要结构符合就行。

## 7. Python 知识：Protocol

`Protocol` 是 Python 类型系统里的“结构化接口”。

你可以把它理解成：

```text
不看你是谁，只看你有没有这些方法。
```

例如：

```python
class Dog:
    def speak(self) -> str:
        return "woof"

class Speaker(Protocol):
    def speak(self) -> str: ...
```

`Dog` 没有继承 `Speaker`，但它有 `speak()` 方法，所以类型检查器可以认为它符合 `Speaker`。

Tau 这里的好处是：

- renderer 类很轻量
- 不需要抽象基类
- 后续 TUI adapter 也可以实现类似事件消费接口

## 8. render() 和 finish() 的分工

`EventRenderer` 有两个方法：

```python
render(event)
finish()
```

### render(event)

每来一个事件，就调用一次。

例如：

```python
renderer.render(MessageDeltaEvent(delta="Hel"))
renderer.render(MessageDeltaEvent(delta="lo"))
```

### finish()

事件流结束后调用。

它返回：

```python
bool
```

表示这次运行是否成功。

为什么需要 `finish()`？

因为有些 renderer 不是边收到事件边输出全部内容。

比如 `FinalTextRenderer` 会等到最后才输出最终答案。

它需要在 `finish()` 时统一决定：

- 打印最终文本
- 或打印错误
- 并返回 True/False

## 9. plain.py：FinalTextRenderer

`FinalTextRenderer` 是默认 print mode。

源码：

```python
class FinalTextRenderer:
    """Render only the final assistant text after the run finishes."""

    def __init__(self) -> None:
        self._last_assistant_text = ""
        self._failed = False
        self._error_messages: list[str] = []
```

它内部保存三类状态：

- 最后一条 assistant 完整文本
- 是否失败
- 错误消息列表

这个 renderer 的目标是 Pi-style print mode：

```text
只输出最终答案，不输出中间 tool 过程。
```

## 10. FinalTextRenderer.render()

源码：

```python
def render(self, event: AgentEvent) -> None:
    if isinstance(event, MessageEndEvent):
        self._last_assistant_text = event.message.content
        return

    if isinstance(event, ErrorEvent):
        if not event.recoverable:
            self._failed = True
        self._error_messages.append(event.message)
```

它只关心两类事件：

### MessageEndEvent

完整 assistant message 结束时：

```python
self._last_assistant_text = event.message.content
```

它不处理 `MessageDeltaEvent`。

所以 streaming 过程中不会一点一点打印。

### ErrorEvent

如果出现 error，就记录。

如果是 non-recoverable：

```python
self._failed = True
```

`recoverable` 可以理解成：

- True：可恢复错误，可能还能继续
- False：不可恢复错误，本次运行应该失败

## 11. FinalTextRenderer.finish()

源码：

```python
def finish(self) -> bool:
    if self._failed:
        for message in self._error_messages:
            typer.echo(f"Error: {message}", err=True)
        return False

    if self._last_assistant_text:
        typer.echo(self._last_assistant_text)
    return True
```

逻辑：

1. 如果失败，错误输出到 stderr，返回 False
2. 如果成功且有最终文本，输出最终文本到 stdout
3. 返回 True

这就是默认 `--output text` 的行为。

测试 `test_final_text_renderer_prints_only_final_message` 验证：

- thinking delta 不输出
- message delta 不输出
- 只有 `MessageEndEvent` 后 `finish()` 才输出最终答案

## 12. Python 包：typer

源码里用了：

```python
import typer
```

Typer 是一个 Python CLI 框架。

Tau 用它来实现命令行。

这里用的是：

```python
typer.echo(...)
```

它类似：

```python
print(...)
```

但更适合 CLI：

- 支持 stdout/stderr
- 和 Typer app 集成更好
- 对终端输出更稳定

例如：

```python
typer.echo("hello")
```

输出到 stdout。

```python
typer.echo("error", err=True)
```

输出到 stderr。

## 13. stdout 和 stderr

终端程序有两个常见输出通道：

### stdout

标准输出。

适合放“程序正常结果”。

例如：

```bash
tau --output text "answer"
```

最终答案应该在 stdout。

这样用户可以：

```bash
tau --output text "answer" > result.txt
```

### stderr

标准错误。

适合放：

- 错误
- 进度信息
- 调试信息
- 人类可读的工具过程

这样脚本读取 stdout 时，不会混入错误和进度。

Phase 11 里：

- text mode 的最终答案走 stdout
- text mode 的错误走 stderr
- transcript mode 的 assistant 文本走 stdout
- transcript mode 的工具过程走 stderr
- json mode 的事件 JSONL 走 stdout

## 14. json.py：JsonEventRenderer

源码：

```python
class JsonEventRenderer:
    """Render every agent event as one JSON object per line."""

    def __init__(self) -> None:
        self._failed = False

    def render(self, event: AgentEvent) -> None:
        if isinstance(event, ErrorEvent) and not event.recoverable:
            self._failed = True
        typer.echo(event.model_dump_json())

    def finish(self) -> bool:
        return not self._failed
```

它的行为非常直接：

每来一个事件，就输出一行 JSON。

这就是 JSON Lines，也叫 JSONL。

## 15. JSON Lines 是什么

JSONL 的格式是一行一个 JSON 对象：

```json
{"type":"message_start","message_role":"assistant"}
{"type":"message_delta","delta":"Hello"}
{"type":"error","message":"provider failed","recoverable":false}
```

它适合流式处理。

普通 JSON 数组必须等整个数组结束：

```json
[
  {...},
  {...}
]
```

但 agent events 是流式出现的。

JSONL 可以边产生边写：

```text
事件来一个，写一行。
```

这对脚本、日志、未来集成都很友好。

## 16. Pydantic 的 model_dump_json()

源码：

```python
event.model_dump_json()
```

这是 Pydantic model 的方法。

Tau 的 event 类型是 Pydantic model。

`model_dump_json()` 会把对象序列化成 JSON 字符串。

例如：

```python
MessageDeltaEvent(delta="Hello").model_dump_json()
```

可能得到：

```json
{"type":"message_delta","delta":"Hello"}
```

这样 renderer 不需要手写每种事件怎么转 JSON。

## 17. transcript.py：TranscriptRenderer

`TranscriptRenderer` 是人类可读的实时 transcript 输出。

它更接近 Phase 6 早期 print-mode 行为：

- assistant delta 实时输出到 stdout
- tool start/update/end 输出到 stderr
- retry 输出到 stderr
- error 输出到 stderr

源码初始化：

```python
class TranscriptRenderer:
    def __init__(self) -> None:
        self._assistant_started = False
        self._assistant_ended = False
        self._failed = False
        self._console = Console(stderr=True, highlight=False)
```

它记录：

- assistant 是否已经开始输出
- assistant 是否已经换行结束
- 是否失败
- Rich console

## 18. Python 包：rich

源码：

```python
from rich.console import Console
from rich.text import Text
```

Rich 是 Python 里常用的终端美化库。

它可以输出：

- 彩色文本
- 表格
- Markdown
- 面板
- 进度条

这里用得很轻：

```python
Console(stderr=True, highlight=False)
Text("...", style="cyan")
```

表示把带样式的文字输出到 stderr。

为什么不是 stdout？

因为 tool 过程属于人类可读过程信息，不应该污染最终答案 stdout。

## 19. TranscriptRenderer.render() 的事件处理

它用一串 `isinstance` 判断事件类型。

### MessageStartEvent

```python
if isinstance(event, MessageStartEvent):
    self._assistant_started = False
    self._assistant_ended = False
    return
```

新 assistant message 开始时，重置状态。

### MessageDeltaEvent

```python
if isinstance(event, MessageDeltaEvent):
    self._assistant_started = True
    typer.echo(event.delta, nl=False)
    return
```

实时输出 assistant 的 delta。

`nl=False` 表示不要自动换行。

例如两个 delta：

```python
"Hel"
"lo"
```

输出到 stdout 是：

```text
Hello
```

而不是：

```text
Hel
lo
```

### ToolExecutionStartEvent

```python
if isinstance(event, ToolExecutionStartEvent):
    self._ensure_assistant_newline()
    self._console.print(Text(format_tool_call_block(event.tool_call), style="cyan"))
    return
```

工具开始前，先确保 assistant 文本换行。

然后输出工具调用信息到 stderr。

### ToolExecutionUpdateEvent / RetryEvent

输出进度：

```text
… reading
… Retrying provider request 2/3 after HTTP 503.
```

### ToolExecutionEndEvent

工具结束时输出：

```text
✓ read
  done
```

失败时 marker 是：

```text
✗
```

### ErrorEvent

错误输出到 stderr。

non-recoverable error 会让 `finish()` 返回 False。

## 20. _ensure_assistant_newline()

源码：

```python
def _ensure_assistant_newline(self, *, final: bool = False) -> None:
    if self._assistant_started and not self._assistant_ended:
        typer.echo()
        self._assistant_ended = True
    elif final and not self._assistant_started:
        self._assistant_ended = True
```

这个函数解决一个终端输出细节：

assistant delta 是不带换行实时输出的。

如果后面马上输出 tool 信息，就会挤在同一行：

```text
Hello→ read a.py
```

所以在输出工具或错误前，要补一个换行。

它用状态位避免重复换行。

测试里验证 transcript 输出：

```python
assert captured.out == "Hello\n"
```

## 21. format_tool_call_block()

`TranscriptRenderer` 引用了：

```python
from tau_coding.tui.state import format_tool_call_block
```

这说明当前实现复用了 TUI state 里的工具调用格式化函数。

测试期望里有：

```python
assert "→ read a.py" in captured.err
```

也就是 read 工具调用会显示成：

```text
→ read a.py
```

这里出现了一个轻微的后续阶段痕迹：

Phase 11 原本是 print rendering，当前代码已经有 TUI 模块，所以 transcript renderer 复用了 TUI 的格式化函数。

学习时记住主线即可：

```text
TranscriptRenderer 把工具事件格式化成人类可读的 stderr 文本。
```

## 22. __init__.py：create_event_renderer()

源码：

```python
def create_event_renderer(mode: PrintOutputMode) -> EventRenderer:
    if mode is PrintOutputMode.text:
        return FinalTextRenderer()
    if mode is PrintOutputMode.json:
        return JsonEventRenderer()
    return TranscriptRenderer()
```

这是一个 factory function。

输入：

```python
PrintOutputMode.text
```

输出：

```python
FinalTextRenderer()
```

输入：

```python
PrintOutputMode.json
```

输出：

```python
JsonEventRenderer()
```

否则输出：

```python
TranscriptRenderer()
```

## 23. Python 知识：factory function

factory function 就是“负责创建对象的函数”。

比如：

```python
def create_animal(kind: str):
    if kind == "cat":
        return Cat()
    return Dog()
```

调用方不用知道具体类怎么选。

在 Tau 里，CLI 只需要：

```python
renderer = create_event_renderer(output)
```

不用自己写一堆 if/else。

## 24. CLI 如何接入 renderer

`src/tau_coding/cli.py` 里 CLI 参数有：

```python
output: Annotated[
    PrintOutputMode,
    typer.Option("--output", "-o", help="Output mode for print mode."),
] = PrintOutputMode.text
```

意思是用户可以用：

```bash
tau -o json "hello"
```

或者：

```bash
tau --output transcript "hello"
```

`run_print_mode()` 里：

```python
renderer = create_event_renderer(output)
...
async for event in session.prompt(prompt):
    renderer.render(event)
return renderer.finish()
```

这就是整个 Phase 11 的主线。

`CodingSession.prompt()` 产生事件。

renderer 消费事件。

CLI 返回 renderer 的成功/失败结果。

## 25. terminal command 为什么不走 renderer

`run_print_mode()` 里有一段：

```python
terminal_command = parse_terminal_command(prompt)
if terminal_command is not None:
    result = await session.run_terminal_command(...)
    typer.echo(_format_terminal_command_result(result))
    return result.ok
```

如果用户输入的是：

```text
! pwd
```

这是 Phase 8 的 terminal command 快捷方式。

它不是 agent event stream。

所以直接执行并格式化结果，不走 `EventRenderer`。

这也说明 renderer 的边界是：

```text
agent prompt 产生的 AgentEvent stream
```

不是 CLI 中所有输出都必须经过 renderer。

## 26. tests/test_rendering.py 怎么读

这个文件直接测试三个 renderer。

### TranscriptRenderer 测试

```python
renderer.render(MessageStartEvent())
renderer.render(ThinkingDeltaEvent(delta="hidden reasoning"))
renderer.render(MessageDeltaEvent(delta="Hel"))
renderer.render(MessageDeltaEvent(delta="lo"))
...
```

它验证：

- stdout 是 `Hello\n`
- thinking delta 不显示
- retry/tool 信息在 stderr
- `finish()` 返回 True

### FinalTextRenderer 测试

它验证：

- delta 不输出
- 只有 `MessageEndEvent` 后 finish 才输出最终文本
- non-recoverable error 在 finish 时输出 stderr

### JsonEventRenderer 测试

它验证：

- 每个事件输出一行 JSON
- JSON 可以被 `json.loads(...)` 解析
- non-recoverable error 后 `finish()` 返回 False

## 27. tests/test_cli.py 的集成测试

CLI 层测试两个 Phase 11 关键路径：

```python
test_run_print_mode_can_emit_json_events
```

验证：

```python
output=PrintOutputMode.json
```

会在 stdout 里出现：

```text
"type":"agent_start"
"type":"message_delta"
```

另一个：

```python
test_run_print_mode_can_emit_live_transcript
```

验证：

```python
output=PrintOutputMode.transcript
```

会把 delta 实时输出成：

```text
Hello\n
```

并且没有 stderr。

## 28. 三种输出模式对比

### text

默认模式。

适合脚本和普通用户：

```text
只要最终答案。
```

中间 thinking、tool、delta 都不显示。

### json

适合程序读取：

```text
每个事件一行 JSON。
```

可以被别的脚本消费。

### transcript

适合人类观察过程：

```text
assistant 实时输出
tool/retry/error 输出到 stderr
```

它保留了更接近早期 print-mode 的体验。

## 29. 初学者容易误解的点

### 误解 1：agent loop 应该直接 print

不应该。

agent loop 是核心逻辑，应该只产出事件。

print 是 UI 政策，属于外层 renderer。

### 误解 2：FinalTextRenderer 没处理 delta 是 bug

不是。

它的目标就是只输出最终 message。

delta 被忽略是设计。

### 误解 3：JSON mode 是给人看的

主要不是。

JSONL 更适合脚本、日志和集成。

人类可读模式是 transcript。

### 误解 4：stderr 表示一定失败

不一定。

stderr 也常用来放进度和诊断信息。

transcript mode 中工具过程走 stderr，即使运行成功也会有 stderr。

## 30. Phase 11 用一句话总结

Phase 11 的价值是：把 `CodingSession.prompt()` 产生的 agent event stream 和 CLI 输出策略分开，用 `EventRenderer` 协议支持 text、json、transcript 三种 print-mode 输出；这样 `tau_agent` 继续保持无 UI 依赖，`tau_coding` 负责终端显示策略，并为后续 Textual TUI 复用同一事件边界打基础。

## 31. 我的问题与推荐回答

问题：为什么 Tau 不让 `AgentLoop` 或 `AgentHarness` 直接把 assistant delta、tool result、error 打印到终端，而是要多一层 `EventRenderer`？

我的推荐回答：

因为 `AgentLoop` 和 `AgentHarness` 属于可复用 agent brain，它们应该只产出结构化 `AgentEvent`，不应该知道 stdout、stderr、Typer、Rich、JSONL 或 TUI。`EventRenderer` 位于 `tau_coding`，专门负责把同一条事件流转换成不同前端需要的输出：`FinalTextRenderer` 只打印最终答案，`JsonEventRenderer` 输出机器可读 JSONL，`TranscriptRenderer` 输出人类可读的实时过程。这样 print mode、脚本集成和未来 Textual TUI 都能复用同一套事件流，而不会污染核心 agent 层。
