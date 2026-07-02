# Phase 23: Advanced TUI and Product Polish 学习笔记

这一篇讲 Tau 的 Textual TUI 打磨。

你可以先用一句话理解：

```text
Phase 23 不是改 agent 大脑，而是把终端界面变得更像一个可长期使用的产品。
```

这包括：

- 工具结果预览
- Markdown 和代码块渲染
- 鼠标选择与复制
- slash-command 输出弹窗
- 命令补全
- session picker
- keybinding 配置
- 主题系统
- 响应式 sidebar
- activity indicator
- thinking tokens 展示控制
- scoped model picker
- Esc 两阶段取消
- `/name` 重命名 session

但是边界仍然是：

```text
CodingSession emits AgentEvent values
        ↓
TuiEventAdapter updates TuiState
        ↓
Textual widgets render the transcript and controls
```

这句话非常重要。

它说明：

```text
agent core 只发事件
TUI adapter 把事件转成 UI 状态
Textual widgets 负责显示
```

## 1. Phase 23 的核心边界

Phase 23 的所有 UI polish 都应该留在：

```text
src/tau_coding/tui/
```

不应该进入：

```text
src/tau_agent/
```

为什么？

因为 `tau_agent` 是可复用 agent harness。

它不应该知道：

- Textual 是什么
- Rich 是什么
- Ctrl+K 是什么
- sidebar 怎么显示
- 鼠标选择怎么复制
- 主题颜色是什么
- session picker 怎么打开

这些都是应用层 UI 细节。

Tau 的架构目标一直是：

```text
AgentHarness = reusable agent brain
CodingSession = coding-agent environment
TUI = one frontend
```

Phase 23 是在强化这个边界，而不是破坏它。

## 2. 主要源码文件

这一 phase 主要看这些文件：

```text
src/tau_coding/tui/config.py
src/tau_coding/tui/state.py
src/tau_coding/tui/widgets.py
src/tau_coding/tui/app.py
```

它们的大致职责是：

```text
config.py   TUI 配置、快捷键、主题
state.py    TUI 显示状态，不直接渲染
widgets.py  Textual/Rich widget 和渲染函数
app.py      TUI 应用主流程、命令调度、worker、取消、picker
```

对应测试：

```text
tests/test_tui_adapter.py
tests/test_tui_app.py
tests/test_tui_config.py
```

## 3. Textual 是什么

Textual 是一个 Python 终端 UI 框架。

它可以让你在 terminal 里做出类似 app 的界面：

- 输入框
- 列表
- 弹窗
- 滚动区域
- footer
- 快捷键绑定
- CSS 样式
- worker 后台任务

Tau 用 Textual 做交互式 TUI。

但注意：

```text
Textual 只属于 tau_coding.tui
```

不能让 `tau_agent` 依赖 Textual。

否则以后如果想换成 Web UI、VS Code 插件、别的 terminal UI，就会很困难。

## 4. Rich 是什么

Rich 是 Python 的终端富文本渲染库。

它可以渲染：

- 彩色文本
- Markdown
- 代码高亮
- 表格
- rule 分隔线
- padding
- group
- syntax diff

Phase 23 里，Rich 主要用于 transcript 和 sidebar 的漂亮显示。

例如：

```python
from rich.markdown import CodeBlock, Heading, Markdown
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
```

这些都是 Rich 的组件。

## 5. `config.py`: TUI 配置和主题系统

`src/tau_coding/tui/config.py` 负责：

- keybindings
- theme names
- theme colors
- loading/saving `~/.tau/tui.json`

开头：

```python
class TuiConfigError(ValueError):
    """Raised when Tau TUI configuration is invalid."""
```

这是自定义异常。

如果用户写的 `tui.json` 不合法，就抛这个错误。

继承 `ValueError` 表示：

```text
这个错误和“传入的值不对”有关。
```

## 6. `TuiKeybindings`

```python
@dataclass(frozen=True, slots=True)
class TuiKeybindings:
    cancel: str = "escape"
    command_palette: str = "ctrl+k"
    session_picker: str = "ctrl+r"
    queue_follow_up: str = "alt+enter"
    accept_completion: str = "tab"
    completion_next: str = "down"
    completion_previous: str = "up"
    thinking_cycle: str = "shift+tab"
    model_cycle: str = "ctrl+p"
    toggle_thinking: str = "ctrl+t"
    toggle_tool_results: str = "ctrl+o"
    copy_message: str = "ctrl+c"
    quit: str = "ctrl+d"
```

这是 TUI 快捷键配置。

`dataclass` 会帮它生成构造函数。

`frozen=True` 表示创建后不可轻易修改。

`slots=True` 表示更轻量，也防止随便加不存在的字段。

默认值就是 Tau 内置快捷键。

例如：

```text
Ctrl+K 打开命令面板
Ctrl+R 打开 session picker
Ctrl+T 显示/隐藏 thinking tokens
Ctrl+O 展开/折叠 tool results
```

## 7. `to_json()`

```python
def to_json(self) -> dict[str, str]:
    """Serialize these keybindings to JSON-compatible data."""
    return {
        "cancel": self.cancel,
        "command_palette": self.command_palette,
        ...
    }
```

这个方法把 Python 对象转成普通 dict。

为什么？

因为 JSON 只能保存：

- string
- number
- boolean
- null
- object
- array

不能直接保存 Python dataclass。

所以要先转成 JSON-compatible data。

## 8. `Literal` 限定主题名字

```python
type TuiThemeName = Literal["tau-dark", "tau-light", "high-contrast"]
```

意思是主题名字只能是：

```text
tau-dark
tau-light
high-contrast
```

这对类型检查很有帮助。

如果有人写：

```python
TuiSettings(theme="solarized")
```

类型检查器会认为不合法。

运行时也会有配置校验。

## 9. `TuiTheme`

```python
@dataclass(frozen=True, slots=True)
class TuiTheme:
    name: TuiThemeName
    screen_background: str
    screen_text: str
    chrome_background: str
    ...
    syntax_theme: str
    role_styles: dict[str, TuiRoleStyle]
```

这是一个完整主题。

它不只是一两个颜色，而是包含：

- 屏幕背景
- 普通文字
- sidebar 背景
- transcript 背景
- prompt 背景
- Markdown 标题颜色
- link 颜色
- code block 背景
- completion 选中样式
- syntax theme
- 不同消息角色的样式

消息角色包括：

- user
- assistant
- tool
- error
- status
- thinking
- skill
- branch_summary
- compaction_summary

这让不同角色的 transcript block 可以有不同左侧 accent 和 body 样式。

## 10. 三个内置主题

代码里定义了：

```python
TAU_DARK_THEME
HIGH_CONTRAST_THEME
TAU_LIGHT_THEME
```

然后：

```python
_THEMES: dict[TuiThemeName, TuiTheme] = {
    TAU_DARK_THEME.name: TAU_DARK_THEME,
    TAU_LIGHT_THEME.name: TAU_LIGHT_THEME,
    HIGH_CONTRAST_THEME.name: HIGH_CONTRAST_THEME,
}
```

这就是一个主题注册表。

`get_tui_theme()` 根据名字取主题：

```python
def get_tui_theme(name: TuiThemeName = "tau-dark") -> TuiTheme:
    return _THEMES[name]
```

## 11. `TuiSettings`

```python
@dataclass(frozen=True, slots=True)
class TuiSettings:
    keybindings: TuiKeybindings = field(default_factory=TuiKeybindings)
    theme: TuiThemeName = "tau-dark"
    auto_copy_selection: bool = False
```

这是用户 TUI 设置。

它包括：

- 快捷键
- 当前主题
- 是否自动复制选中的文本

这里又出现：

```python
field(default_factory=TuiKeybindings)
```

意思是每次创建 `TuiSettings` 时，都新建一个 `TuiKeybindings` 对象。

避免多个 settings 共享同一个可变默认对象。

## 12. `~/.tau/tui.json`

```python
def tui_settings_path(paths: TauPaths | None = None) -> Path:
    """Return the durable TUI settings path."""
    return (paths or TauPaths()).home / "tui.json"
```

这表示 TUI 配置默认存在：

```text
~/.tau/tui.json
```

例如用户可以写：

```json
{
  "theme": "tau-light"
}
```

重启后 TUI 使用 light theme。

## 13. `state.py`: TUI 显示状态

`src/tau_coding/tui/state.py` 不负责画界面。

它只负责保存 UI 当前应该展示什么。

核心类型：

```python
ChatItemRole = Literal[
    "user",
    "assistant",
    "tool",
    "error",
    "status",
    "thinking",
    "skill",
    "branch_summary",
    "compaction_summary",
]
```

这表示 transcript 里每个 item 的角色。

## 14. `ChatItem`

```python
@dataclass(slots=True)
class ChatItem:
    """One rendered item in the TUI transcript."""

    role: ChatItemRole
    text: str
    tool_call_id: str | None = None
    tool_result_text: str | None = None
    always_show_tool_result: bool = False
```

这是 transcript 中的一条显示项。

字段含义：

- `role`: 这条消息是什么角色
- `text`: 默认显示文本
- `tool_call_id`: 如果是工具调用，用来和工具结果匹配
- `tool_result_text`: 工具结果或 summary 详情
- `always_show_tool_result`: 是否总是展开详情

注意：

```text
ChatItem 仍然是朴素数据，不含 Textual widget。
```

这保持了 state 和 renderer 的分离。

## 15. `TuiState`

```python
@dataclass(slots=True)
class TuiState:
    items: list[ChatItem] = field(default_factory=list)
    assistant_buffer: str = ""
    running: bool = False
    error: str | None = None
    show_tool_results: bool = False
    show_thinking: bool = False
    queued_steering: tuple[str, ...] = ()
    queued_follow_up: tuple[str, ...] = ()
    skills: tuple[Skill, ...] = ()
```

这是整个 TUI 的显示状态。

它记录：

- transcript items
- assistant 正在流式输出的 buffer
- 当前 agent 是否运行
- 是否显示工具结果
- 是否显示 thinking tokens
- queued steering/follow-up
- 已加载 skills

它是 mutable 的。

所以没有 `frozen=True`。

因为 UI 状态会不断变化。

## 16. branch summary 和 compaction summary 的 UI 折叠

`add_user_message()` 里有：

```python
branch_summary = _parse_branch_summary_message(content)
if branch_summary is not None:
    self.add_item(
        "branch_summary",
        "Branch summary (Ctrl+O to expand)",
        tool_result_text=branch_summary,
    )
    return
```

以及：

```python
compaction_summary = _parse_compaction_summary_message(content)
if compaction_summary is not None:
    self.add_item(
        "compaction_summary",
        "Compaction summary (Ctrl+O to expand)",
        tool_result_text=compaction_summary,
    )
    return
```

这说明：

```text
session replay 后的 summary message 在 TUI 里不会直接铺满屏幕。
```

它会显示成：

```text
Compaction summary (Ctrl+O to expand)
```

用户需要时再按 `Ctrl+O` 展开。

这是 Phase 23 的一个典型产品打磨：

```text
完整信息还在，但默认界面不被大段 summary 淹没。
```

## 17. tool result 预览

`format_tool_result_block()`：

```python
def format_tool_result_block(
    *,
    name: str,
    ok: bool,
    content: str,
    data: dict[str, JSONValue] | None = None,
) -> str:
```

它会生成工具结果显示文本。

开头：

```python
status = "✓" if ok else "✗"
lines = [f"{status} {name}"]
```

如果成功就显示 `✓`，失败就显示 `✗`。

然后：

```python
if content:
    lines.append(_preview_text(content, max_lines=TOOL_RESULT_PREVIEW_LINES))
```

只显示前几行结果，避免大输出刷屏。

如果是 `edit` 工具，并且有 patch：

```python
patch = _result_patch(name=name, ok=ok, data=data)
if patch:
    lines.extend(["", "Patch:", _preview_text(patch, max_lines=TOOL_PATCH_PREVIEW_LINES)])
```

TUI 可以展示 diff patch。

## 18. `_preview_text()`

```python
def _preview_text(text: str, *, max_lines: int) -> str:
    lines = text.splitlines()
    ...
```

它会：

1. 按行切分。
2. 取前 `max_lines` 行。
3. 如果还有隐藏行，追加提示。
4. 如果字符太多，也截断。

提示类似：

```text
[Preview only: 10 more lines hidden from the TUI.]
```

注意这里说的是：

```text
hidden from the TUI
```

不是 hidden from session。

完整工具结果仍然保存在 durable session 里，也仍然可以给模型上下文和 replay 使用。

## 19. `widgets.py`: Textual/Rich 渲染层

`src/tau_coding/tui/widgets.py` 负责把 `TuiState` 变成真正的终端 UI。

开头可以看到很多 UI 包：

```python
from rich.console import Console, Group, RenderableType
from rich.markdown import CodeBlock, Heading, Markdown
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual.containers import Horizontal, VerticalScroll
from textual.selection import Selection
from textual.widgets import Static
```

你可以把它们分成两类：

```text
Rich     负责内容怎么画
Textual 负责界面组件和交互
```

## 20. `SessionSummarySource` Protocol

```python
class SessionSummarySource(Protocol):
    @property
    def cwd(self) -> Path: ...
    @property
    def model(self) -> str: ...
    ...
```

`Protocol` 是一种“结构化接口”。

意思是：

```text
只要某个对象有这些属性，就可以被当作 SessionSummarySource 使用。
```

它不像继承那样要求显式继承某个基类。

这里的好处是：

```text
sidebar 渲染函数不需要依赖完整 CodingSession 类型，只需要依赖它要展示的那些属性。
```

这是降低耦合的一种方法。

## 21. `TranscriptMessageWidget`

Phase 23 的重点之一是：

```text
transcript 不再是一个巨大的 RichLog，而是由一个个 selectable message widget 组成。
```

核心 widget 里有：

```python
def get_selection(self, selection: Selection) -> tuple[str, str] | None:
    """Return selected plain text from this message, not rendered Markdown markup."""
    selected_text = _extract_text_selection(self.selection_text, selection)
    if not selected_text:
        return None
    return selected_text, "\n"
```

这让每个消息块自己处理选中文本。

好处是：

```text
选择一条消息的一部分时，不会意外复制整个会话。
```

## 22. Markdown 和 plain text 的分工

```python
def _use_plain_transcript_body(item: ChatItem) -> bool:
    return item.role in {"user", "tool", "skill", "error"}
```

也就是说：

- user/tool/skill/error 默认按 plain text 显示
- assistant/thinking/status 可以走 Markdown 渲染

为什么这样设计？

因为用户输入和工具输出通常要保持原样。

比如用户粘贴了：

```text
*这个不一定是 Markdown*
```

如果强行渲染成 Markdown，可能会改变原始含义。

而 assistant 输出常常包含：

- 标题
- bullet
- code block
- link
- inline code

所以 assistant 更适合 Rich Markdown。

## 23. 代码块和 patch 渲染

`_render_patch_body()`：

```python
marker = "\nPatch:\n"
if marker not in text:
    return None
...
return Group(
    _plain_text(f"{before_patch}{marker.rstrip()}", body_style=body_style),
    Syntax(
        patch.rstrip("\n"),
        "diff",
        theme=syntax_theme,
        word_wrap=True,
        background_color=code_block_background,
    ),
)
```

如果文本里有：

```text
Patch:
```

就把后面当 diff patch，用 Rich `Syntax(..., "diff")` 高亮。

这让 `edit` 工具结果在 TUI 里有 inline diff view。

## 24. 防御性代码块渲染

Phase 23 还处理了未知 fenced language。

比如模型输出：

```text
```not-a-real-language
hello
```
```

如果直接让 Pygments 按不存在的语言高亮，可能报错或显示坏掉。

所以 widgets 里引入：

```python
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound
```

当语言不存在时，fallback 到 plain code rendering。

这就是“产品打磨”：

```text
不要因为模型输出了奇怪 fence label 就把整个 transcript 搞坏。
```

## 25. `TranscriptView`: 滚动 transcript

```python
class TranscriptView(VerticalScroll):
    """Scrollable transcript view backed by individual selectable message widgets."""
```

它继承 Textual 的 `VerticalScroll`。

说明 transcript 是一个可滚动区域。

里面有：

```python
def on_mount(self) -> None:
    """Follow new transcript content until the user scrolls away."""
    self.anchor()
```

默认跟随新输出滚到底部。

但如果用户滚动离开底部，它不会强行把用户拉回底部。

这对长输出很重要。

## 26. thinking tokens 的显示控制

`TranscriptView._redraw()` 里：

```python
if item.role == "thinking" and not state.show_thinking:
    if not hidden_thinking_placeholder:
        self.mount(
            TranscriptMessageWidget(
                ChatItem(
                    role="thinking",
                    text="Thinking… Press Ctrl+T to show thinking tokens.",
                ),
                ...
            )
        )
    continue
```

默认不显示 thinking tokens 的细节。

只显示一个占位提示：

```text
Thinking… Press Ctrl+T to show thinking tokens.
```

用户按 `Ctrl+T` 后，再展开实际 thinking 内容。

这保持界面干净，也保留调试能力。

## 27. `app.py`: 命令调度和 compaction worker

`src/tau_coding/tui/app.py` 是 TUI 主应用。

当用户提交输入时，它会：

1. 看是否正在 compaction。
2. 看是不是 terminal command。
3. 看是不是 slash command。
4. 如果不是命令，就作为 prompt 提交给 agent。

处理 `/compact` 的片段：

```python
if command.compact_summary is not None:
    if self._is_compaction_active():
        self._notify("A compaction is already running.", severity="warning")
    elif self._is_agent_or_queue_active():
        prompt.text = raw_text
        prompt.move_cursor(_text_end_location(raw_text))
        self._notify(
            "Wait for the current agent turn and queued messages to finish before compacting.",
            severity="warning",
        )
        return
    else:
        self._compaction_worker = self.run_worker(
            self._run_compaction(command.compact_summary),
            exclusive=False,
        )
```

这里有几个产品细节：

- 如果 compaction 已经在跑，不重复启动。
- 如果 agent 正在运行或队列里还有 prompt，不允许 compaction 插队。
- 如果不能执行，会保留用户输入，不让用户重新打。
- compaction 用 worker 异步运行。

## 28. Textual worker 是什么

Textual 的 worker 可以让长任务在后台运行。

比如：

```python
self.run_worker(self._run_compaction(...), exclusive=False)
```

如果不放到 worker，TUI 可能会卡住。

compaction 要调用模型生成 summary，可能要等一会儿。

所以它适合 worker。

## 29. `_run_compaction()`

```python
async def _run_compaction(self, summary: str) -> None:
    """Run manual compaction without disabling prompt editing."""
    self.state.clear()
    self.state.add_item("status", "Compacting session…")
    self._refresh()
    try:
        compact_message = await self.session.compact(summary)
    ...
    self.state.clear()
    self.state.set_skills(self.session.skills)
    self.state.load_messages(self.session.messages)
    self._notify(compact_message)
    self._refresh()
```

流程：

1. 清空当前可见 transcript。
2. 显示 `Compacting session…` 状态。
3. 调用 `session.compact()`。
4. compact 完成后，从 session messages 重新加载可见 transcript。
5. 用 notification 告知用户结果。

注意：

```text
TUI 只是调用 session.compact()
真正 compaction 行为仍然在 CodingSession
```

这就是边界清楚。

## 30. 取消 compaction

```python
def action_cancel(self) -> None:
    """Cancel the active compaction or agent turn."""
    if self._cancel_active_compaction(notify=True):
        return
    self._cancel_active_prompt(notify=True)
```

按 Esc 时，先尝试取消 compaction。

如果没有 compaction，再取消 agent prompt。

`_cancel_active_compaction()`：

```python
worker.cancel()
self._compaction_worker = None
self.state.clear()
self.state.set_skills(self.session.skills)
self.state.load_messages(self.session.messages)
self._refresh()
```

它取消 worker，然后恢复当前 session messages。

## 31. slash-command 输出不再污染 transcript

Phase 23 里有：

```python
def _command_message_uses_transcript(command_text: str) -> bool:
    command_name = command_text.split(maxsplit=1)[0].casefold()
    return command_name == "/reload"
```

多数 slash-command 输出不再进入 transcript。

短结果用 notification。

长结果打开 modal。

只有像 `/reload` 这种确实和会话状态变化有关的，才可能写到 transcript。

这样可以避免：

```text
/help
/skills
/status
```

这些参考信息污染 agent conversation。

## 32. footer 快捷键提示

`_prompt_bindings()` 会根据模式返回不同的 visible bindings。

模式有：

```python
Literal["normal", "completion", "running"]
```

普通模式显示：

- Submit
- Newline
- Commands
- Sessions
- Thinking
- Model
- Clear
- Quit

补全模式显示：

- Complete
- Choose
- Close

运行中显示：

- Steer
- Follow-up
- Cancel
- Thinking
- Tools

这让底部 footer 随状态变化，而不是一直显示同一组快捷键。

## 33. `_theme_css_variables()`

```python
def _theme_css_variables(theme: TuiTheme) -> dict[str, str]:
    return {
        "tau-screen-background": theme.screen_background,
        "tau-screen-text": theme.screen_text,
        ...
    }
```

它把 Python 里的 `TuiTheme` 转成 Textual CSS 变量。

这样 Textual app 的 CSS 可以统一使用这些变量。

好处是：

```text
同一个主题对象同时驱动 Rich 渲染和 Textual CSS。
```

UI 颜色就不会一半是 dark theme，一半是别的颜色。

## 34. sidebar 和 compact session info

`render_session_sidebar()` 展示：

- provider
- model
- thinking
- tools
- skills
- prompt templates
- context files

其中 context files 很重要。

因为用户可以直接看到 `AGENTS.md` 等项目上下文是否被加载。

窄屏时则使用：

```python
class CompactSessionInfo(Static):
```

它显示单行 session metadata。

这是响应式 TUI 的一部分。

## 35. `/name` session rename

架构文档还提到：

```text
Sessions can now be renamed from the TUI with /name <new name>.
```

这类命令更新的是 indexed session metadata。

也就是说它影响：

- `/resume`
- resume completions
- session picker

但不会改写 append-only transcript 的历史消息。

这依旧保持 durable conversation history 的边界。

## 36. 这一 phase 的 Python 包

### 36.1 `dataclasses`

用来定义轻量数据对象，比如：

- `TuiKeybindings`
- `TuiTheme`
- `TuiSettings`
- `ChatItem`
- `TuiState`

### 36.2 `json`

`config.py` 里：

```python
from json import dumps, loads
```

用于把 TUI settings 写成 JSON 或从 JSON 读取。

### 36.3 `pathlib.Path`

用于处理文件路径。

例如：

```python
Path("~/.tau/tui.json")
```

比直接拼字符串更可靠。

### 36.4 `typing`

使用：

- `Any`
- `Literal`
- `Protocol`
- `ClassVar`
- `cast`

这些帮助表达更精确的类型。

### 36.5 `Textual`

用于 TUI app、widgets、bindings、selection、scroll container。

核心概念：

- `Static`: 显示静态内容
- `VerticalScroll`: 可滚动区域
- `Binding`: 快捷键绑定
- `Selection`: 鼠标选择文本范围

### 36.6 `Rich`

用于终端富文本渲染。

核心组件：

- `Text`
- `Table`
- `Markdown`
- `Syntax`
- `Group`
- `Padding`
- `Rule`

### 36.7 `Pygments`

Rich 的代码高亮底层依赖 Pygments。

Phase 23 使用它检查 fenced language 是否存在，避免未知语言导致渲染坏掉。

## 37. 小白要抓住的主线

这一 phase 功能很多，但主线只有一条：

```text
TUI 显示可以越来越复杂，但 agent/session/core 状态仍然保持简单。
```

你可以用三层理解：

```text
TuiState
    保存 UI 要显示什么

widgets.py
    决定怎么显示、怎么选择、怎么高亮、怎么折叠

app.py
    决定用户按键、命令、worker、modal、取消流程
```

而 `tau_agent` 不参与这些。

## 38. 如何运行测试

Phase 23 对应测试：

```bash
uv run pytest tests/test_tui_adapter.py tests/test_tui_app.py tests/test_tui_config.py
```

这些测试覆盖：

- TUI adapter 是否把 agent events 转成正确 state
- transcript render 是否处理 tool result、patch、Markdown、selection
- TUI settings 是否加载主题和 keybindings
- compaction command 是否正确调度
- theme picker 是否保存配置
- thinking/tool display toggle 是否正常
- footer bindings 是否随模式变化

## 39. 用一句话总结

Phase 23 的核心价值是：在不污染 `tau_agent` 的前提下，把 Tau 的 Textual frontend 从基础交互推进到可长期使用的产品级 TUI，包括主题、快捷键、选择复制、Markdown/patch 渲染、命令弹窗、session picker、状态提示和取消流程。

## 40. 我的问题与推荐回答

问题：为什么 Phase 23 做了这么多 TUI 功能，却仍然强调不能让 `tau_agent` 依赖 Textual 或 Rich？

我的推荐回答：

因为 `tau_agent` 是可复用的 agent harness，它应该只关心消息、事件、工具调用、session replay 和 agent loop。Textual、Rich、快捷键、主题、弹窗、sidebar、鼠标选择都只是 Tau 当前 CLI/TUI 产品的一种表现形式。如果把这些 UI 细节放进 `tau_agent`，以后想换成 Web UI、VS Code 插件或别的终端界面时就会被绑死。Phase 23 的正确做法是让 `CodingSession` 继续发 `AgentEvent`，`TuiEventAdapter` 更新 `TuiState`，再由 `tau_coding.tui` 的 widgets 和 app 做复杂渲染。
