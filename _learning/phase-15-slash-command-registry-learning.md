# Phase 15 学习笔记：Slash Command Registry

对应架构文档：`dev-notes/architecture/phase-15-slash-command-registry.md`

主要源码：

- `src/tau_coding/commands.py`
- `src/tau_coding/session.py`
- `src/tau_coding/tui/app.py`
- `tests/test_commands.py`
- `tests/test_coding_session.py`
- `tests/test_tui_app.py`

前置阶段：

- Phase 6：print-mode CLI 开始能接收用户输入
- Phase 8：`CodingSession` 成为 coding-agent 的应用包装层
- Phase 12：TUI 开始消费 session 事件和用户输入
- Phase 14：session 可以被创建、索引、列出、恢复
- Phase 15：把 slash command 从零散硬编码整理成统一注册表

## 1. 这一阶段到底在做什么

Phase 15 给 Tau 增加了一个 slash command registry。

所谓 slash command，就是用户输入以 `/` 开头的命令，例如：

```text
/quit
/new
/session
/resume
/model
/theme
```

在 Phase 15 之前，应用很容易写成这样：

```python
if text == "/quit":
    ...
elif text == "/new":
    ...
elif text.startswith("/resume"):
    ...
```

这种写法短期简单，但命令一多就会变得很散：

- 每个命令的名字写在不同地方
- 帮助信息不统一
- TUI 自动补全不知道有哪些命令
- 命令返回结果不标准
- 后续扩展命令会越来越难

Phase 15 的解决办法是：

```python
CommandRegistry
```

也就是一个“命令注册表”。

你可以把它想象成一个小字典：

```text
"quit"   -> /quit 这个命令的说明和处理函数
"new"    -> /new 这个命令的说明和处理函数
"resume" -> /resume 这个命令的说明和处理函数
```

用户输入 `/new` 时，registry 负责：

1. 判断这是不是 slash command。
2. 解析命令名和参数。
3. 找到对应的命令定义。
4. 调用这个命令的 handler。
5. 返回统一的 `CommandResult`。

## 2. 为什么这属于 tau_coding，而不是 tau_agent

Tau 的架构分层仍然很重要：

```text
tau_ai      provider/model streaming layer
tau_agent   portable agent harness, loop, tools, events, sessions
tau_coding  CLI app, resources, skills, extensions, commands, TUI integration
```

slash command 是应用层能力。

例如：

- `/session` 要知道当前 cwd、model、skills、context files。
- `/resume` 要用 `SessionManager`。
- `/model` 要和 provider/model 设置交互。
- `/theme` 只对 TUI 有意义。
- `/login` 和本地凭据、provider catalog 有关。

这些都不是一个通用 agent harness 应该关心的东西。

所以 Phase 15 把命令系统放在：

```text
src/tau_coding/commands.py
```

这样 `tau_agent` 仍然保持纯粹：

- 不依赖 Textual
- 不依赖 Typer CLI
- 不依赖本地 `~/.tau`
- 不关心 Tau 产品自己的命令名

## 3. 先看 commands.py 的 import

文件开头：

```python
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
```

这里对 Python 小白来说有几个重点。

### 3.1 Callable 是什么

`Callable` 表示“可以被调用的东西”。

最常见的 callable 是函数：

```python
def hello() -> str:
    return "hello"
```

`hello` 就是 callable，因为你可以这样调用：

```python
hello()
```

在命令系统里，每个命令都有一个 handler。

handler 本质上就是函数：

```python
def _new_command(context: CommandContext) -> CommandResult:
    return CommandResult(handled=True, new_session_requested=True)
```

所以代码定义了：

```python
CommandHandler = Callable[[CommandContext], CommandResult]
```

意思是：

```text
CommandHandler 是一种函数类型：
输入一个 CommandContext
返回一个 CommandResult
```

### 3.2 Sequence 是什么

`Sequence` 表示“有顺序的一组东西”。

例如：

```python
["a", "b", "c"]
("a", "b", "c")
```

list 和 tuple 都可以看成 sequence。

在 `CommandSession` 里你会看到：

```python
def skills(self) -> Sequence[Skill]: ...
```

意思是：

```text
session.skills 返回一组 Skill
至于是 list 还是 tuple，不强制
只要能按顺序遍历就可以
```

这比写死 `list[Skill]` 更灵活。

### 3.3 dataclass 是什么

`dataclass` 是 Python 标准库提供的工具。

它适合用来定义“主要保存数据”的类。

普通写法可能是：

```python
class CommandResult:
    def __init__(self, handled: bool, message: str | None = None) -> None:
        self.handled = handled
        self.message = message
```

用 dataclass 可以简化成：

```python
@dataclass
class CommandResult:
    handled: bool
    message: str | None = None
```

Python 会自动帮你生成 `__init__` 等基础方法。

Phase 15 里用了：

```python
@dataclass(frozen=True, slots=True)
```

这里有两个参数：

```text
frozen=True  创建后不希望再修改字段
slots=True   限制实例属性，减少内存，也避免随手加不存在的字段
```

你可以简单理解：

```text
这是一个更稳定、更像“值对象”的 dataclass
```

### 3.4 Protocol 是什么

`Protocol` 是类型检查用的“接口约定”。

`commands.py` 里没有直接依赖 `CodingSession` 这个具体类，而是定义了：

```python
class CommandSession(Protocol):
    ...
```

意思是：

```text
只要一个对象长得像 CommandSession，
有这些属性和方法，
命令 handler 就可以使用它。
```

这叫结构化类型。

例如 `_status_command()` 需要：

```python
session.model
session.cwd
session.tools
session.skills
```

它不关心这个 session 到底是不是 `CodingSession` 类，只关心它有没有这些字段。

这带来两个好处：

1. `commands.py` 和 `session.py` 不需要强绑定。
2. 测试里可以很容易写 `FakeSession`。

你在 `tests/test_commands.py` 里会看到：

```python
class FakeSession:
    ...
```

这个 fake session 只要提供 command handler 需要的属性，就能测试 registry。

## 4. CommandSession：命令系统需要的 session 能力清单

源码里：

```python
class CommandSession(Protocol):
    """Session attributes available to slash-command handlers."""
```

它不是普通业务类，而是一个“命令处理器需要哪些能力”的清单。

里面包括：

```python
@property
def cwd(self) -> Path: ...

@property
def model(self) -> str: ...

@property
def provider_name(self) -> str: ...
```

这些是当前环境信息。

还包括：

```python
@property
def skills(self) -> Sequence[Skill]: ...

@property
def prompt_templates(self) -> Sequence[PromptTemplate]: ...

@property
def context_files(self) -> Sequence[ProjectContextFile]: ...
```

这些是 Phase 9、Phase 10、Phase 13 逐步引入的资源信息。

还包括：

```python
@property
def session_id(self) -> str | None: ...

@property
def session_manager(self) -> SessionManager | None: ...
```

这些是 Phase 14 的 session resume 基础。

最后还有方法：

```python
def set_model(self, model: str) -> None: ...

def reload(self) -> CodingReloadSummary: ...

def reload_provider_settings(self) -> None: ...
```

这些代表 slash command 可以让 session 做一些动作。

注意这里的边界：

```text
commands.py 负责解释 /model 是什么
session.py 负责真的切换 model
```

## 5. CommandResult：命令处理结果

`CommandResult` 是 Phase 15 的关键。

源码：

```python
@dataclass(frozen=True, slots=True)
class CommandResult:
    """Result of handling a coding-session slash command."""

    handled: bool
    exit_requested: bool = False
    clear_requested: bool = False
    new_session_requested: bool = False
    compact_summary: str | None = None
    export_requested: bool = False
    export_destination: Path | None = None
    export_format: str | None = None
    resume_session_id: str | None = None
    resume_picker_requested: bool = False
    tree_picker_requested: bool = False
    login_picker_requested: bool = False
    login_provider: str | None = None
    logout_picker_requested: bool = False
    logout_provider: str | None = None
    model_picker_requested: bool = False
    scoped_models_picker_requested: bool = False
    theme_picker_requested: bool = False
    thinking_level: str | None = None
    theme: str | None = None
    message: str | None = None
```

你可以把它理解成：

```text
命令 handler 不直接操作 UI
命令 handler 只返回“我希望应用做什么”
```

例如 `/quit`：

```python
CommandResult(
    handled=True,
    exit_requested=True,
    message="Exiting session.",
)
```

意思是：

```text
这个命令已经处理了
请 UI 退出
顺便可以显示一条消息
```

再比如 `/new`：

```python
CommandResult(handled=True, new_session_requested=True)
```

意思是：

```text
这个命令已经处理了
请 UI 创建新 session
```

再比如 `/resume`：

```python
CommandResult(handled=True, resume_picker_requested=True)
```

或者：

```python
CommandResult(handled=True, resume_session_id=session_id)
```

分别表示：

```text
打开 session picker
直接恢复某个 session id
```

## 6. 为什么 CommandResult 不直接执行动作

这是一个非常重要的设计点。

假设 `/theme tau-light` 直接在 command handler 里改 TUI：

```python
def _theme_command(...):
    app.set_theme("tau-light")
```

那 `commands.py` 就必须知道 TUI app 是什么。

这会让 `commands.py` 依赖 Textual。

但 Phase 15 的做法是：

```python
return CommandResult(handled=True, theme="tau-light")
```

然后 TUI 看到结果再执行：

```python
if command.theme is not None:
    self._set_tui_theme(...)
```

这样命令系统保持纯粹：

```text
commands.py 解释用户意图
tui/app.py 执行 TUI 相关动作
session.py 执行 session 相关动作
```

这就是“结构化返回值”的价值。

## 7. CommandContext：handler 拿到的上下文

源码：

```python
@dataclass(frozen=True, slots=True)
class CommandContext:
    """Runtime context passed to slash-command handlers."""

    session: CommandSession
    registry: CommandRegistry
    text: str
    name: str
    args: str
```

它是每个命令 handler 的入参。

字段含义：

```text
session   当前 coding session
registry  当前命令注册表
text      用户输入的完整命令文本
name      解析出来的命令名
args      命令后面的参数
```

例如用户输入：

```text
/resume abc123
```

解析后：

```text
text = "/resume abc123"
name = "resume"
args = "abc123"
```

于是 `_resume_command()` 可以根据 `args` 判断：

- 没有 args：打开 picker
- 有 args：按 session id 恢复

## 8. SlashCommand：一个命令的注册信息

源码：

```python
@dataclass(frozen=True, slots=True)
class SlashCommand:
    """A registered slash command and its user-facing metadata."""

    name: str
    description: str
    usage: str
    handler: CommandHandler
    aliases: tuple[str, ...] = ()
    search_terms: tuple[str, ...] = ()
```

这代表一个命令的完整定义。

例如 `/new` 的注册：

```python
SlashCommand(
    name="new",
    usage="/new",
    description="Start a new session.",
    handler=_new_command,
    search_terms=("clear", "reset"),
)
```

字段解释：

```text
name         真正的命令名，例如 new
usage        给用户看的用法，例如 /new
description  给用户看的说明
handler      用户执行这个命令时调用哪个函数
aliases      别名
search_terms 搜索补全用的词，但不是命令
```

`search_terms` 很容易误解。

例如 `/new` 有：

```python
search_terms=("clear", "reset")
```

这表示：

```text
用户在补全面板里搜 clear/reset，可以建议 /new
```

但这不表示 `/clear` 是合法命令。

测试明确验证：

```python
assert registry.execute(session, "/clear").message == "Unknown command: /clear"
```

这就是“搜索词”和“真实命令名”的区别。

## 9. CommandRegistry 的内部数据结构

源码：

```python
class CommandRegistry:
    """Parse, register, list, and execute slash commands."""

    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}
        self._aliases: dict[str, str] = {}
```

这里有两个字典。

### 9.1 _commands

```python
self._commands: dict[str, SlashCommand] = {}
```

这个字典保存真实命令：

```text
"new" -> SlashCommand(...)
"quit" -> SlashCommand(...)
"session" -> SlashCommand(...)
```

### 9.2 _aliases

```python
self._aliases: dict[str, str] = {}
```

这个字典保存别名到真实命令的映射：

```text
"q" -> "quit"
```

不过当前 Pi-aligned registry 特意没有保留 `/q` 和 `/exit`。

测试里确认：

```python
assert registry.execute(session, "/exit").message == "Unknown command: /exit"
assert registry.execute(session, "/q").message == "Unknown command: /q"
```

## 10. register()：注册命令

源码核心：

```python
def register(self, command: SlashCommand) -> None:
    name = _normalize_name(command.name)
    if name in self._commands:
        raise ValueError(f"Duplicate slash command: /{name}")
    self._commands[name] = command
    for alias in command.aliases:
        normalized_alias = _normalize_name(alias)
        if normalized_alias in self._commands or normalized_alias in self._aliases:
            raise ValueError(f"Duplicate slash command alias: /{normalized_alias}")
        self._aliases[normalized_alias] = name
```

逐行看。

第一步：

```python
name = _normalize_name(command.name)
```

把命令名标准化。

比如：

```text
"/New" -> "new"
" new " -> "new"
```

第二步：

```python
if name in self._commands:
    raise ValueError(...)
```

防止重复注册同一个命令。

第三步：

```python
self._commands[name] = command
```

把命令放进字典。

第四步，处理 aliases：

```python
for alias in command.aliases:
    ...
```

如果 alias 和已有命令或已有 alias 冲突，也会报错。

这很重要，因为命令系统不能模棱两可。

例如如果 `/q` 同时是 `/quit` 和 `/query` 的别名，registry 就不知道该执行哪个。

## 11. get()：按名字或别名取命令

源码：

```python
def get(self, name: str) -> SlashCommand | None:
    normalized = _normalize_name(name)
    command_name = self._aliases.get(normalized, normalized)
    return self._commands.get(command_name)
```

逻辑是：

1. 标准化名字。
2. 如果它是 alias，找到真实命令名。
3. 从 `_commands` 里取命令。
4. 找不到就返回 `None`。

这里有一个 Python 小知识：

```python
dict.get(key, default)
```

如果 key 存在，就返回对应 value。

如果 key 不存在，就返回 default。

所以：

```python
self._aliases.get(normalized, normalized)
```

意思是：

```text
如果 normalized 是别名，就返回别名对应的真实命令名
否则就把 normalized 本身当成命令名
```

## 12. list_commands()：列出命令

源码：

```python
def list_commands(self) -> tuple[SlashCommand, ...]:
    """Return registered commands sorted by name."""
    return tuple(self._commands[name] for name in sorted(self._commands))
```

这里有两个 Python 点。

### 12.1 sorted(dict)

对字典调用 `sorted()` 时，默认排序的是 key。

例如：

```python
data = {"new": 1, "quit": 2, "compact": 3}
sorted(data)
```

结果是：

```python
["compact", "new", "quit"]
```

所以 registry 的命令列表是按名字排序的。

### 12.2 generator expression

这一段：

```python
self._commands[name] for name in sorted(self._commands)
```

是生成器表达式。

它会按排序后的命令名逐个取出 `SlashCommand`。

外面包一层：

```python
tuple(...)
```

最终变成不可变的 tuple。

## 13. execute()：命令系统的核心入口

源码：

```python
def execute(self, session: CommandSession, text: str) -> CommandResult:
    """Execute a slash command, or return unhandled for ordinary prompts."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return CommandResult(handled=False)

    if stripped.startswith("/skill:"):
        return CommandResult(handled=False)

    name, args = _parse_command(stripped)
    if not name:
        return CommandResult(handled=False)

    command = self.get(name)
    if command is None and name == "scoped" and args.lower() == "models":
        command = self.get("scoped-models")
        name = "scoped-models"
        args = ""
    if command is None:
        return CommandResult(handled=True, message=f"Unknown command: /{name}")

    return command.handler(
        CommandContext(session=session, registry=self, text=stripped, name=name, args=args)
    )
```

这是 Phase 15 最值得反复看的函数。

### 13.1 普通 prompt 不处理

```python
if not stripped.startswith("/"):
    return CommandResult(handled=False)
```

如果用户输入：

```text
请帮我解释这个函数
```

它不是 slash command。

registry 返回：

```python
CommandResult(handled=False)
```

意思是：

```text
这不是命令，继续当作普通 prompt 发给模型
```

### 13.2 /skill:<name> 不在这里处理

```python
if stripped.startswith("/skill:"):
    return CommandResult(handled=False)
```

这个非常关键。

`/skill:testing add tests` 看起来像 slash command，但在 Tau 里它是 prompt expansion。

也就是说，它不是让 UI 执行动作，而是要把 skill 文件内容展开到 prompt 里。

展开逻辑在 `CodingSession.prompt()` 的路径上。

所以 registry 这里故意返回 `handled=False`。

测试也验证了：

```python
assert registry.execute(session, "/skill:review fix this").handled is False
```

### 13.3 解析命令名和参数

```python
name, args = _parse_command(stripped)
```

例如：

```text
/model gpt-4.1
```

解析成：

```text
name = "model"
args = "gpt-4.1"
```

### 13.4 支持 Pi 风格的 /scoped models

源码里有一个特殊兼容：

```python
if command is None and name == "scoped" and args.lower() == "models":
    command = self.get("scoped-models")
    name = "scoped-models"
    args = ""
```

也就是说：

```text
/scoped-models
```

和：

```text
/scoped models
```

都能打开 scoped models picker。

测试里也验证：

```python
dashed_result = registry.execute(session, "/scoped-models")
pi_style_result = registry.execute(session, "/scoped models")
```

### 13.5 未知命令也算 handled

```python
if command is None:
    return CommandResult(handled=True, message=f"Unknown command: /{name}")
```

这里为什么 `handled=True`？

因为用户输入了 `/missing`。

这不是普通 prompt。

如果返回 `handled=False`，系统可能会把 `/missing` 发给模型。

但用户显然是在执行命令。

所以 registry 返回：

```text
handled=True
message="Unknown command: /missing"
```

意思是：

```text
我已经识别出这是命令输入，只是命令不存在。
请 UI 显示错误，不要发给模型。
```

## 14. _parse_command()：如何拆分命令

源码：

```python
def _parse_command(text: str) -> tuple[str, str]:
    command, separator, args = text[1:].partition(" ")
    return _normalize_name(command), args.strip() if separator else ""
```

这里用了字符串方法：

```python
partition(" ")
```

例如：

```python
"/resume abc123"[1:].partition(" ")
```

先看 `[1:]`：

```text
"/resume abc123" -> "resume abc123"
```

然后 partition：

```python
"resume abc123".partition(" ")
```

结果是：

```python
("resume", " ", "abc123")
```

所以：

```python
command = "resume"
separator = " "
args = "abc123"
```

如果没有空格：

```python
"new".partition(" ")
```

结果是：

```python
("new", "", "")
```

所以 `separator` 可以用来判断是否真的有参数。

## 15. _normalize_name()：命令名标准化

源码：

```python
def _normalize_name(name: str) -> str:
    return name.strip().removeprefix("/").lower()
```

逐段看：

```python
name.strip()
```

去掉首尾空白。

```python
.removeprefix("/")
```

如果开头有 `/`，就去掉。

```python
.lower()
```

转成小写。

所以这些都变成：

```text
"/NEW" -> "new"
" new " -> "new"
"New"  -> "new"
```

## 16. create_default_command_registry()

这个函数创建 Tau 内置命令表。

源码：

```python
def create_default_command_registry() -> CommandRegistry:
    """Create Tau's built-in slash command registry."""
    registry = CommandRegistry()
    registry.register(...)
    registry.register(...)
    ...
    return registry
```

它的模式很固定：

1. 创建 registry。
2. 注册每个 `SlashCommand`。
3. 返回 registry。

当前测试要求注册命令按名字排序后是：

```text
compact
export
hotkeys
login
logout
model
name
new
quit
reload
resume
scoped-models
session
skill
theme
tree
```

注意：

架构文档里描述的是 Phase 15 当时的核心集合。

当前源码已经继续被后续阶段扩展，包含：

- `/tree`
- `/scoped-models`
- `/logout`

但它们仍然复用 Phase 15 建立的 registry 机制。

## 17. /quit 命令

注册：

```python
SlashCommand(
    name="quit",
    usage="/quit",
    description="Exit the current session.",
    handler=_exit_command,
)
```

handler：

```python
def _exit_command(context: CommandContext) -> CommandResult:
    return CommandResult(handled=True, exit_requested=True, message="Exiting session.")
```

这个命令不需要参数。

它只返回：

```text
请退出当前 session
```

真正退出在哪里做？

在 TUI：

```python
if command.exit_requested:
    self.exit()
```

这就是“命令解释”和“UI 执行”分离。

## 18. /new 命令

注册：

```python
SlashCommand(
    name="new",
    usage="/new",
    description="Start a new session.",
    handler=_new_command,
    search_terms=("clear", "reset"),
)
```

handler：

```python
def _new_command(context: CommandContext) -> CommandResult:
    return CommandResult(handled=True, new_session_requested=True)
```

它不直接创建 session。

它只说：

```text
请创建新 session
```

TUI 收到后：

```python
if command.new_session_requested:
    await self._new_session()
```

Phase 14 里我们讲过 `_new_session()` 会创建新的 pending session，并在第一次持久化消息后进入 index。

## 19. /compact 命令

handler：

```python
def _compact_command(context: CommandContext) -> CommandResult:
    return CommandResult(
        handled=True,
        compact_summary=context.args.strip(),
    )
```

如果用户输入：

```text
/compact
```

结果：

```python
compact_summary = ""
```

如果用户输入：

```text
/compact Keep API decisions and test failures.
```

结果：

```python
compact_summary = "Keep API decisions and test failures."
```

TUI 收到 `compact_summary` 后，会启动 compaction worker。

这里为什么不用布尔值 `compact_requested=True`？

因为 `/compact` 还可以携带用户给摘要的 instructions。

所以用：

```python
compact_summary: str | None
```

可以同时表达：

```text
None 表示没有请求 compact
""   表示请求 compact，但没有额外 instructions
"..." 表示请求 compact，并带了 instructions
```

## 20. /export 命令

handler：

```python
def _export_command(context: CommandContext) -> CommandResult:
    try:
        export_format, destination = _parse_export_args(context.args)
    except ValueError as exc:
        return CommandResult(handled=True, message=str(exc))
    return CommandResult(
        handled=True,
        export_requested=True,
        export_destination=destination,
        export_format=export_format,
    )
```

它支持：

```text
/export
/export exports/session.html
/export --format jsonl exports/session.jsonl
/export --format=jsonl exports/session.jsonl
```

注意，handler 不直接写文件。

它只是返回：

```text
export_requested=True
export_destination=...
export_format=...
```

TUI 再调用：

```python
exported_path = await self.session.export(...)
```

## 21. _parse_export_args()

源码核心：

```python
parts = args.split()
export_format: str | None = None
destination: Path | None = None
index = 0
while index < len(parts):
    part = parts[index]
    ...
    index += 1
return export_format, destination
```

这里用的是手写的小解析器。

`args.split()` 会按空白切开参数。

例如：

```python
"--format jsonl exports/session.jsonl".split()
```

得到：

```python
["--format", "jsonl", "exports/session.jsonl"]
```

然后 while 循环逐个处理。

### 21.1 处理 --format jsonl

```python
if part == "--format":
    index += 1
    if index >= len(parts):
        raise ValueError("Usage: /export [--format html|jsonl] [destination]")
    export_format = parts[index]
```

如果看到 `--format`，下一个参数必须是格式。

如果用户只输入：

```text
/export --format
```

就会报 usage。

### 21.2 处理 --format=jsonl

```python
elif part.startswith("--format="):
    export_format = part.partition("=")[2]
```

`partition("=")` 会把字符串分成三段。

例如：

```python
"--format=jsonl".partition("=")
```

得到：

```python
("--format", "=", "jsonl")
```

所以 `[2]` 就是 `jsonl`。

### 21.3 处理未知 option

```python
elif part.startswith("-"):
    raise ValueError(f"Unknown export option: {part}")
```

如果用户输入：

```text
/export --bad
```

就返回错误消息。

### 21.4 处理 destination

```python
elif destination is None:
    destination = Path(part).expanduser()
else:
    raise ValueError("Usage: /export [--format html|jsonl] [destination]")
```

只允许一个 destination。

如果用户写两个路径，就报 usage。

`Path(part).expanduser()` 会把：

```text
~/Desktop/session.html
```

展开成用户 home 下的绝对语义路径。

## 22. /session 命令

`/session` 对应 handler 是 `_status_command()`。

它会收集当前 session 的摘要信息：

```python
lines = [
    f"Model: {session.model}",
    f"CWD: {session.cwd}",
    f"Tools: {len(session.tools)}",
    f"Skills: {len(session.skills)}",
    f"Prompt templates: {len(session.prompt_templates)}",
    f"Context files: {len(session.context_files)}",
    f"Estimated context tokens: {session.context_token_estimate}",
    f"Context window: {session.context_window_tokens}",
]
```

这里用了一个常见模式：

```python
lines = [...]
lines.append(...)
return "\n".join(lines)
```

这比不断做字符串加法更清晰。

`"\n".join(lines)` 会用换行符把列表里的每一行拼起来。

测试里验证 `/session` 会包含：

```text
Model: fake-model
CWD: ...
Tools: 4
Skills: 1
Context files: 1
Estimated context tokens: 123
Context window: 584
Thinking mode: medium
Resource diagnostics: 0
Session: session-1
```

注意旧的 `/status` 已经不是注册命令。

测试明确要求：

```python
assert registry.execute(session, "/status").message == "Unknown command: /status"
```

这是为了向 Pi 的命令列表靠齐。

## 23. /hotkeys 命令

handler：

```python
def _hotkeys_command(context: CommandContext) -> CommandResult:
    lines = [
        "Common keyboard shortcuts:",
        "- Enter: submit prompt",
        "- Shift+Enter: insert newline",
        ...
    ]
    return CommandResult(handled=True, message="\n".join(lines))
```

这个命令只是返回说明文本。

但它仍然放在 registry 里，这样：

- TUI 可以补全 `/hotkeys`
- 命令列表可以统一展示
- 测试可以独立验证

## 24. /reload 命令

handler：

```python
def _reload_command(context: CommandContext) -> CommandResult:
    try:
        summary = context.session.reload()
    except ValueError as exc:
        return CommandResult(handled=True, message=f"Could not reload: {exc}")

    return CommandResult(
        handled=True,
        message=_format_reload_summary(summary),
    )
```

这里第一次看到 handler 调用 session 方法：

```python
context.session.reload()
```

`reload()` 是 `CommandSession` protocol 规定 session 必须提供的能力。

它会重新读取：

- skills
- prompt templates
- context files
- resource diagnostics
- system prompt

然后 `_format_reload_summary()` 把结果变成用户可读文本。

测试验证 `/reload` 不刷新 provider config：

```text
Not refreshed by /reload; use /login or /model for provider/model settings.
```

这是一个产品边界：

```text
/reload 刷新本地 coding resources
/login 或 /model 处理 provider/model 配置
```

## 25. /resume 命令

handler：

```python
def _resume_command(context: CommandContext) -> CommandResult:
    if not context.args:
        return CommandResult(handled=True, resume_picker_requested=True)
    manager = context.session.session_manager
    if manager is None:
        return CommandResult(handled=True, message="Session manager is not available.")
    session_id = context.args.strip()
    if manager.get_session(session_id) is None:
        return CommandResult(handled=True, message=f"Unknown session: {session_id}")
    return CommandResult(
        handled=True,
        resume_session_id=session_id,
    )
```

分三种情况。

### 25.1 没有参数

用户输入：

```text
/resume
```

返回：

```python
resume_picker_requested=True
```

TUI 打开 session picker。

### 25.2 没有 SessionManager

如果 session manager 不存在：

```python
message="Session manager is not available."
```

这是一种防御式处理。

### 25.3 有 session id

用户输入：

```text
/resume abc123
```

代码会先检查：

```python
manager.get_session(session_id)
```

如果不存在：

```python
message="Unknown session: abc123"
```

如果存在：

```python
resume_session_id="abc123"
```

然后 TUI 调用：

```python
await self._resume_session(command.resume_session_id)
```

## 26. /name 命令

`/name` 用来查看或修改当前 session 名称。

没有参数时：

```text
/name
```

返回当前名称和 usage：

```text
Current session name: Test session
Usage: /name <new name>
```

有参数时：

```text
/name Customer bugfix
```

会调用：

```python
manager.touch_session(
    session_id,
    model=context.session.model,
    provider_name=context.session.provider_name,
    title=name,
)
```

这里复用了 Phase 14 的 `SessionManager.touch_session()`。

它会更新 metadata index 里的 title、model、provider、updated_at。

## 27. _validated_session_name()

源码：

```python
def _validated_session_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("Usage: /name <new name>")
    if any(char in name for char in "\r\n\t"):
        raise ValueError("Session name must be a single line.")
    return name
```

这里有一个 Python 小知识：

```python
any(...)
```

`any()` 会判断一组条件里有没有至少一个为 True。

这里：

```python
any(char in name for char in "\r\n\t")
```

意思是：

```text
只要 name 里包含回车、换行、tab 任意一个字符，就返回 True
```

所以 session name 必须是单行。

测试验证：

```python
result = registry.execute(session, "/name Bad\nName")
assert result.message == "Session name must be a single line."
```

## 28. /model 命令

handler：

```python
def _model_command(context: CommandContext) -> CommandResult:
    refresh_error = _refresh_provider_settings(context.session)
    if refresh_error is not None:
        return refresh_error

    if context.args:
        model = context.args.strip()
        available_models = set(context.session.available_models)
        if available_models and model not in available_models:
            models = ", ".join(sorted(available_models))
            return CommandResult(...)
        context.session.set_model(model)
        return CommandResult(handled=True, message=f"Current model: {model}")

    return CommandResult(handled=True, model_picker_requested=True)
```

这个命令也有两种模式。

### 28.1 没有参数

```text
/model
```

返回：

```python
model_picker_requested=True
```

TUI 打开 model picker。

### 28.2 有参数

```text
/model other-model
```

先确认模型是否在 `available_models` 中。

如果合法：

```python
context.session.set_model(model)
```

然后返回：

```python
message="Current model: other-model"
```

测试里确认 session 的 model 真的变了：

```python
assert session.model == "other-model"
```

## 29. 为什么 /model 先 reload_provider_settings()

`_model_command()` 一开始调用：

```python
refresh_error = _refresh_provider_settings(context.session)
```

内部：

```python
try:
    session.reload_provider_settings()
except ValueError as exc:
    return CommandResult(
        handled=True,
        message=f"Could not refresh provider settings: {exc}",
    )
```

意思是：

```text
在打开模型选择或切换模型前，先刷新 provider 配置
```

因为用户可能刚改过 provider settings。

如果配置文件坏了，就返回错误消息，而不是继续执行。

## 30. /theme 命令

内置主题名：

```python
BUILTIN_TUI_THEME_NAMES = ("tau-dark", "tau-light", "high-contrast")
```

handler：

```python
def _theme_command(context: CommandContext) -> CommandResult:
    if not context.args:
        return CommandResult(handled=True, theme_picker_requested=True)

    theme_name = context.args.strip()
    if theme_name not in BUILTIN_TUI_THEME_NAMES:
        themes = ", ".join(BUILTIN_TUI_THEME_NAMES)
        return CommandResult(
            handled=True,
            message=f"Unknown theme: {theme_name}\nAvailable themes: {themes}",
        )
    return CommandResult(handled=True, theme=theme_name)
```

没有参数：

```text
/theme
```

打开 theme picker。

有参数：

```text
/theme tau-light
```

返回：

```python
theme="tau-light"
```

TUI 再执行：

```python
self._set_tui_theme(...)
```

## 31. /login 和 /logout 命令

`/login` 支持：

```text
/login
/login openai
```

没有参数时：

```python
login_picker_requested=True
```

有参数时，如果 provider 合法：

```python
login_provider="openai"
```

`/logout` 类似：

```python
logout_picker_requested=True
```

或者：

```python
logout_provider="openai"
```

这里依赖：

```python
BUILTIN_PROVIDER_CATALOG
builtin_provider_entry()
```

这说明命令系统已经和 Tau 的 provider catalog 产生应用层协作。

但仍然没有污染 `tau_agent`。

## 32. /skill 和 /skill:<name> 的区别

这一点很容易混。

当前 registry 里注册了：

```python
SlashCommand(
    name="skill",
    usage="/skill:<name> [request]",
    description="Expand a loaded skill into your prompt.",
    handler=_skill_command,
    search_terms=("skills",),
)
```

但 `execute()` 一开始有：

```python
if stripped.startswith("/skill:"):
    return CommandResult(handled=False)
```

所以：

```text
/skill:testing add tests
```

不会被 registry 当普通命令执行，而会进入 prompt expansion。

而：

```text
/skill
```

会命中 `_skill_command()`，返回提示：

```text
Use /skill:<name> [request] to expand a loaded skill into your prompt.
```

这是一种很细的 UX 设计：

```text
/skill            是帮助提示
/skill:<name>     是 prompt expansion 指令
```

## 33. prompt template slash command 为什么也不是普通命令

在 `CodingSession.handle_command()` 里：

```python
def handle_command(self, text: str) -> CommandResult:
    """Handle coding-session slash commands.

    Prompt-template slash commands are expansion directives, so they remain
    unhandled here and flow through `prompt()` for on-the-fly replacement.
    """
    if expand_prompt_template_command(text, self._prompt_templates) is not None:
        return CommandResult(handled=False)
    return self._command_registry.execute(self, text)
```

如果项目里有：

```text
.agents/prompts/example.md
```

那么用户可以输入：

```text
/example src/app.py
```

这看起来像 slash command，但它其实是 prompt template expansion。

所以 `handle_command()` 也故意返回：

```python
CommandResult(handled=False)
```

让后续 `prompt()` 去展开模板。

测试验证：

```python
assert session.handle_command("/example src/app.py").handled is False
```

然后真正调用 `session.prompt()` 时，provider 收到的是展开后的内容：

```text
Custom prompt for src/app.py.
```

## 34. TUI 如何消费 CommandResult

TUI 里核心逻辑在：

```text
src/tau_coding/tui/app.py
```

用户提交文本后：

```python
command = self.session.handle_command(text)
if command.handled:
    ...
    return
```

如果 `handled=True`，就说明这是命令输入，不要发给模型。

然后 TUI 按字段执行动作：

```python
if command.new_session_requested:
    await self._new_session()
```

```python
if command.resume_session_id is not None:
    await self._resume_session(command.resume_session_id)
```

```python
if command.resume_picker_requested:
    self.action_open_session_picker()
```

```python
if command.model_picker_requested:
    self._open_model_picker()
```

```python
if command.theme is not None:
    self._set_tui_theme(...)
```

最后如果有 message：

```python
if command.message:
    ...
```

TUI 会决定把消息显示成通知、transcript message，还是临时提示。

这说明 `CommandResult` 是 command layer 和 UI layer 的桥。

## 35. autocomplete 为什么也依赖 registry

Phase 15 的 registry 还为后续自动补全打基础。

TUI 构建 completion state 时：

```python
registry = _session_command_registry(self.session)
return build_completion_state(
    text,
    command_registry=registry,
    skills=self.session.skills,
    prompt_templates=self.session.prompt_templates,
    ...
)
```

也就是说：

```text
命令补全不需要自己维护一份命令列表
它可以直接读 CommandRegistry
```

这避免了一个常见 bug：

```text
命令能执行，但补全里没有
或者补全里有，但执行不了
```

Phase 15 建 registry，就是后面 Phase 17 TUI autocomplete 的前置条件。

## 36. tests/test_commands.py 怎么测

Phase 15 的核心测试在：

```text
tests/test_commands.py
```

它定义了一个：

```python
class FakeSession:
    ...
```

这个 fake session 提供命令 handler 需要的属性。

例如：

```python
self.provider_name = "openai"
self.model = "fake-model"
self.available_models = ("fake-model", "other-model")
self.tools = tuple(create_coding_tools(cwd=tmp_path))
self.skills = (...)
self.context_files = (...)
self.session_manager = manager
```

这就是 Protocol 的好处。

测试不用启动完整 `CodingSession`，也不用真的跑 agent loop。

它只测：

```text
给 registry 一个像 session 的对象
输入命令
检查 CommandResult
```

## 37. 测试覆盖了什么

测试包括：

```text
test_registry_ignores_ordinary_prompts_and_skill_expansion
test_registered_commands_are_pi_aligned
test_quit_and_new_return_control_flags
test_compact_command_accepts_optional_instructions
test_export_command_requests_default_export
test_export_command_parses_format_and_destination
test_session_command_includes_session_details
test_hotkeys_command_lists_common_tui_shortcuts
test_model_command_requests_picker_and_switches_models
test_theme_command_requests_picker_and_sets_theme
test_non_pi_commands_are_not_registered
test_login_command_requests_provider_picker
test_reload_command_refreshes_session_resources
test_resume_without_argument_requests_picker
test_resume_command_requests_indexed_session
test_name_command_renames_current_session
test_unknown_command_returns_message
test_registry_rejects_duplicate_commands_and_aliases
```

这些测试从几个角度保护 Phase 15：

- 普通 prompt 不被误判为命令
- `/skill:<name>` 继续走 prompt expansion
- 内置命令列表符合预期
- `/exit`、`/q`、`/clear` 等旧命令不再注册
- control flags 正确返回
- session manager 相关命令能按 id 检查
- duplicate command 会报错

## 38. 为什么未知命令不能发给模型

再强调一次这个点，因为它很像真实产品里的细节。

如果用户输入：

```text
/clearr
```

这很可能是想输入命令，但打错了。

如果系统把它当 prompt 发给模型，模型可能会开始解释 `/clearr`。

这不是用户想要的。

所以 registry 返回：

```python
CommandResult(handled=True, message="Unknown command: /clearr")
```

这样 UI 会显示错误，而不是调用模型。

## 39. 为什么 /help 没有注册

当前测试要求：

```python
for command in ("/provider", "/skills", "/resources", "/context", "/help"):
    result = registry.execute(session, command)
    assert result.message == f"Unknown command: {command}"
```

这看起来有点反直觉，因为源码里确实有 `_help_command()`、`_skills_command()`、`_resources_command()`、`_context_command()` 等函数。

但它们没有被 `create_default_command_registry()` 注册。

所以对用户来说它们不是当前默认命令。

这体现了一个架构现实：

```text
源码里存在 helper 函数，不等于它已经是公开功能
是否注册，才决定它是不是当前产品命令
```

Phase 15 的目标是 Pi-aligned command registry，所以旧的 Tau-specific 诊断命令没有进入默认注册表。

## 40. 当前代码比 Phase 15 文档多出来的命令

架构文档是阶段记录，当前源码已经继续往后走。

所以现在 `commands.py` 里还可以看到一些后续能力：

- `/tree`
- `/scoped-models`
- `/logout`
- thinking 相关 result 字段

学习时不要被这个吓到。

你可以这样分层理解：

```text
Phase 15 学的是 registry 机制
后续 phase 继续往 registry 里添加更多命令和更多 CommandResult 字段
```

也就是说，Phase 15 建了“插座板”。

后面每个命令只是往这个插座板上插更多功能。

## 41. 和前面阶段的连接

### 41.1 连接 Phase 8：CodingSession

`CodingSession` 现在有：

```python
self._command_registry = command_registry or create_default_command_registry()
```

这说明 session 默认自带内置 registry。

同时测试也可以传入自定义 registry。

### 41.2 连接 Phase 9：skills 和 prompt templates

`/skill:<name>` 和 `/example` 这类 prompt expansion 不被 registry 吞掉。

这保证资源系统和命令系统不会互相抢输入。

### 41.3 连接 Phase 14：SessionManager

`/resume` 和 `/name` 都依赖：

```python
context.session.session_manager
```

也就是上一阶段的 metadata index。

### 41.4 连接 Phase 12：TUI

TUI 不需要知道每个命令怎么解析。

它只需要消费结构化结果。

## 42. Python 小白应该掌握的语法点

### 42.1 类型别名

```python
CommandHandler = Callable[[CommandContext], CommandResult]
```

这不是赋普通值，而是在定义一个更易读的类型名字。

以后写：

```python
handler: CommandHandler
```

就比每次写：

```python
handler: Callable[[CommandContext], CommandResult]
```

清楚。

### 42.2 `str | None`

```python
message: str | None = None
```

意思是：

```text
message 可以是字符串，也可以是 None
```

在 Python 3.10+ 里，`|` 可以用来表示 union type。

### 42.3 tuple[str, ...]

```python
aliases: tuple[str, ...] = ()
```

意思是：

```text
aliases 是一个 tuple
里面每个元素都是 str
元素数量不限
默认是空 tuple
```

`...` 在类型标注里表示“任意数量”。

### 42.4 f-string

```python
f"Unknown command: /{name}"
```

这是格式化字符串。

如果：

```python
name = "missing"
```

结果就是：

```text
Unknown command: /missing
```

### 42.5 try/except

```python
try:
    export_format, destination = _parse_export_args(context.args)
except ValueError as exc:
    return CommandResult(handled=True, message=str(exc))
```

意思是：

```text
尝试解析参数
如果解析函数抛出 ValueError
就把错误变成用户能看到的 command message
```

这种模式很适合命令解析。

内部可以用 exception 表示错误，外部统一转成 `CommandResult`。

## 43. 这一阶段的设计核心

Phase 15 的核心不是“多了几个命令”。

真正核心是：

```text
slash command 被建模成数据 + handler + 结构化结果
```

也就是：

```python
SlashCommand      # 命令定义
CommandRegistry   # 命令注册、查找、执行
CommandContext    # 执行上下文
CommandResult     # 执行结果
```

这四个类型让命令系统变成一个可以扩展的模块，而不是一堆散落的 if/elif。

## 44. 你读源码时的推荐顺序

建议这样读：

1. 先读 `CommandResult`，明白命令可以返回哪些动作。
2. 再读 `SlashCommand`，明白一个命令由哪些信息组成。
3. 再读 `CommandRegistry.register()`，明白命令怎么进入注册表。
4. 再读 `CommandRegistry.execute()`，明白用户输入怎么被解析执行。
5. 再读 `create_default_command_registry()`，看 Tau 注册了哪些内置命令。
6. 最后读各个 `_xxx_command()` handler。
7. 回到 `CodingSession.handle_command()` 看 session 如何委托 registry。
8. 再到 `tui/app.py` 看 UI 如何消费 `CommandResult`。

这样读会比从文件第一行一路读到底更容易。

## 45. Phase 15 用一句话总结

Phase 15 的价值是：在 `tau_coding` 中引入 `CommandRegistry`、`SlashCommand`、`CommandContext` 和 `CommandResult`，把 slash command 从散落的硬编码判断升级成可注册、可解析、可测试、可补全、可被 TUI 结构化消费的应用层命令系统，同时继续保持 `tau_agent` 不依赖 Tau 的 CLI/TUI 产品行为。

## 46. 我的问题与推荐回答

问题：为什么 `/skill:testing add tests` 和 `/example src/app.py` 看起来像 slash command，却要让 `CommandRegistry` 返回 `handled=False`？

我的推荐回答：

因为它们不是“让 UI 或 session 执行动作”的普通命令，而是 prompt expansion 指令。`/skill:testing add tests` 需要把 skill 文档展开进 prompt，`/example src/app.py` 需要把 prompt template 渲染成真正发给模型的文本。如果 registry 把它们当普通命令处理掉，后面的 `CodingSession.prompt()` 就没有机会做展开。因此 registry 对这类输入返回 `handled=False`，让它们继续沿普通 prompt 路径流动，但在发给模型前被资源系统替换成展开后的内容。
