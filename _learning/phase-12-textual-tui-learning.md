# Phase 12 学习笔记：Textual TUI

对应架构文档：`dev-notes/architecture/phase-12-textual-tui.md`

主要源码：

- `src/tau_coding/tui/state.py`
- `src/tau_coding/tui/adapter.py`
- `src/tau_coding/tui/widgets.py`
- `src/tau_coding/tui/app.py`
- `src/tau_coding/tui/__init__.py`
- `src/tau_coding/cli.py`
- `tests/test_tui_adapter.py`
- `tests/test_tui_app.py`
- `tests/test_cli.py`

前置阶段：

- Phase 8：`CodingSession` 把 agent brain、tools、session storage 包起来
- Phase 11：print mode 通过 renderer 消费 `AgentEvent`
- Phase 12：Textual TUI 也开始消费同一套 `AgentEvent`

## 1. 这一阶段到底在做什么

Phase 12 给 Tau 加入第一版交互式终端 UI。

这个 UI 用的是 Python 的 Textual 框架。

你可以先用一句话理解：

Phase 12 把 `CodingSession.prompt()` 产生的事件流接到一个可交互的终端界面上，让用户可以在 TUI 输入 prompt、看到 assistant 回复、工具调用、错误和 session 信息。

核心链路是：

```text
CodingSession.prompt()
  emits AgentEvent
      ↓
TuiEventAdapter
  updates TuiState
      ↓
TauTuiApp
  renders Textual widgets
```

注意这里仍然没有让 `tau_agent` 依赖 Textual。

Textual 只存在于：

```text
src/tau_coding/tui/
```

## 2. 为什么 TUI 也要走事件边界

Phase 11 已经给 print mode 建了渲染边界：

```text
AgentEvent -> EventRenderer -> stdout/stderr
```

Phase 12 延续同一思想：

```text
AgentEvent -> TuiEventAdapter -> TuiState -> Textual widgets
```

这样做的好处是：

- agent core 不知道 UI
- CLI 和 TUI 可以消费同一套事件
- TUI 状态转换可以单独测试
- 以后换前端时不用重写 agent loop

Pi 的架构也是类似分层：

```text
agent/session emits events
terminal frontend consumes events
UI components render display state
```

Tau 到 Phase 12 时开始对齐这个方向。

## 3. 当前 tui/ 目录结构

当前源码：

```text
src/tau_coding/tui/
  __init__.py
  adapter.py
  app.py
  autocomplete.py
  config.py
  state.py
  widgets.py
```

Phase 12 主线重点是：

```text
state.py    TUI 显示状态
adapter.py  AgentEvent -> TuiState
widgets.py  Textual widgets
app.py      Textual App 外壳
```

当前代码里 `autocomplete.py`、`config.py`、很多 picker/modal/theme 逻辑，是后续 phase 和 polish 叠加出来的。

学习 Phase 12 时先抓住最小骨架：

```text
输入 prompt
运行 CodingSession
接收事件
更新 TuiState
刷新 transcript/sidebar
```

## 4. Python 包：Textual 是什么

Textual 是一个 Python 终端 UI 框架。

它让你可以在终端里写类似“应用程序”的界面：

- Header
- Footer
- 输入框
- 滚动区域
- 侧边栏
- modal screen
- keyboard bindings
- worker
- CSS 样式

它不是浏览器网页。

它是在终端里运行的 TUI：

```text
TUI = Terminal User Interface
```

Phase 12 的目标不是做完整产品级 UI，而是先把 Tau 的事件流接进 Textual。

## 5. state.py：TUI 的显示状态

`src/tau_coding/tui/state.py` 不依赖 Textual。

它只是普通 Python 状态对象。

这点很重要：

```text
TuiState 可以不启动终端界面就测试。
```

核心数据结构有：

```python
ChatItem
TuiState
```

## 6. ChatItemRole

源码：

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

它定义 transcript 里一条显示项可能是什么角色。

常见角色：

- `user`：用户消息
- `assistant`：assistant 回复
- `tool`：工具调用或工具结果
- `error`：错误
- `status`：状态信息
- `thinking`：模型思考 token
- `skill`：skill 调用或 skill 文件读取

后面的 `branch_summary`、`compaction_summary` 是后续 session tree / compaction 功能叠加进来的。

## 7. Python 知识：Literal

`Literal` 表示字段只能是固定值之一。

例如：

```python
role: Literal["user", "assistant"]
```

表示 `role` 只能是：

```text
"user"
"assistant"
```

如果你写：

```python
role = "abc"
```

类型检查器就能提醒你。

在 TUI 里这很有用，因为 UI 会根据 role 决定样式。

## 8. ChatItem

源码：

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

它表示 transcript 里一块可显示内容。

例如用户消息：

```python
ChatItem(role="user", text="Hello")
```

assistant 消息：

```python
ChatItem(role="assistant", text="Hi")
```

工具调用：

```python
ChatItem(
    role="tool",
    text="→ read README.md",
    tool_call_id="call-1",
)
```

工具结果会挂在同一个 item 上：

```python
tool_result_text="✓ read\nfile content..."
```

## 9. TuiState

源码：

```python
@dataclass(slots=True)
class TuiState:
    """Mutable display state for the interactive TUI."""

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

它是 TUI 的内存显示状态。

字段解释：

- `items`：已经完成的 transcript 块
- `assistant_buffer`：正在 streaming 的 assistant 文本
- `running`：当前 agent 是否正在运行
- `error`：最新错误
- `show_tool_results`：是否展开工具结果
- `show_thinking`：是否显示 thinking token
- `queued_steering` / `queued_follow_up`：运行中排队的消息
- `skills`：已加载 skill，用于把读 skill 文件的 tool call 显示成 skill 样式

## 10. 为什么需要 assistant_buffer

模型输出是流式的。

事件可能是：

```text
MessageDeltaEvent("Hel")
MessageDeltaEvent("lo")
MessageEndEvent("Hello")
```

如果每个 delta 都添加一个 `ChatItem`，UI 会出现很多碎片：

```text
Hel
lo
```

所以 TUI 先把 delta 放进：

```python
assistant_buffer
```

等消息结束，或者遇到工具事件需要刷新时，再 flush 成一条 assistant item。

测试：

```python
test_tui_adapter_builds_assistant_items_from_streamed_messages
```

验证：

```python
adapter.apply(MessageDeltaEvent(delta="Hel"))
adapter.apply(MessageDeltaEvent(delta="lo"))
assert state.assistant_buffer == "Hello"
assert state.items == []
```

直到 `MessageEndEvent` 才变成 item。

## 11. TuiState.add_item()

源码：

```python
def add_item(
    self,
    role: ChatItemRole,
    text: str,
    *,
    tool_call_id: str | None = None,
    tool_result_text: str | None = None,
    always_show_tool_result: bool = False,
) -> None:
    self.items.append(ChatItem(...))
```

它是往 transcript 里追加显示项的统一入口。

参数里的 `*` 表示后面的参数必须用关键字传。

例如：

```python
state.add_item("tool", "→ read README.md", tool_call_id="call-1")
```

不能写成：

```python
state.add_item("tool", "→ read README.md", "call-1")
```

这样可以避免参数顺序混乱。

## 12. TuiState.add_tool_call()

源码主线：

```python
def add_tool_call(self, tool_call: ToolCall) -> None:
    skill_name = self._read_skill_name(tool_call)
    if skill_name is not None:
        self.add_item("skill", f"Loading skill: {skill_name}", tool_call_id=tool_call.id)
        return
    self.add_item("tool", format_tool_call_block(tool_call), tool_call_id=tool_call.id)
```

它把 tool call 转成 UI item。

普通 read：

```text
→ read README.md
```

bash：

```text
$ git status
```

如果这个 read 正好读取一个 skill 文件，就显示成：

```text
Loading skill: review
```

这是为了让 TUI 更友好。

## 13. TuiState.add_user_message()

这个函数处理用户消息。

普通用户输入：

```python
self.add_item("user", content)
```

如果用户消息其实是展开后的 skill invocation：

```xml
<skill name="review" location="...">
...
</skill>

check the auth flow
```

TUI 不直接显示完整 skill 内容，而是压缩成：

```text
Using skill: review
check the auth flow
```

测试：

```python
test_tui_adapter_compacts_streamed_skill_invocations
```

验证结果：

```python
[("skill", "Using skill: review"), ("user", "check the auth flow")]
```

## 14. TuiState.record_tool_result()

工具结束时，事件里带 `AgentToolResult`。

TUI 要把结果挂回对应 tool call。

源码：

```python
for item in reversed(self.items):
    if item.role in {"tool", "skill"} and item.tool_call_id == result.tool_call_id:
        item.tool_result_text = result_text
        return
```

这里用 `reversed(self.items)` 从后往前找。

原因是最近的 tool call 最可能匹配。

如果找不到对应 tool call，就追加一个孤立工具结果 item。

## 15. Python 知识：reversed()

`reversed(list)` 会从后往前遍历。

例如：

```python
items = [1, 2, 3]
for item in reversed(items):
    print(item)
```

输出：

```text
3
2
1
```

在工具结果匹配里，从后往前找更接近事件发生顺序。

## 16. TuiState.load_messages()

当 TUI 打开一个已有 session，需要把历史消息显示出来。

源码：

```python
def load_messages(self, messages: Iterable[AgentMessage]) -> None:
    for message in messages:
        if message.role == "user":
            self.add_user_message(message.content)
        elif message.role == "assistant":
            if message.content:
                self.add_item("assistant", message.content)
            for tool_call in message.tool_calls:
                self.add_tool_call(tool_call)
        elif message.role == "tool":
            self.record_tool_result(...)
```

这就是 Phase 12 架构文档里说的：

```text
restores previous session messages into the visible transcript
```

`CodingSession` 负责恢复 durable messages。

`TuiState.load_messages()` 负责把这些 messages 转成显示项。

## 17. adapter.py：TuiEventAdapter

`TuiEventAdapter` 是 Phase 12 最核心的纯逻辑层。

源码：

```python
class TuiEventAdapter:
    """Apply portable agent events to mutable TUI display state."""

    def __init__(self, state: TuiState) -> None:
        self.state = state

    def apply(self, event: AgentEvent) -> None:
        ...
```

它的输入是：

```python
AgentEvent
```

输出不是返回值，而是修改：

```python
TuiState
```

这使得事件到 UI 状态的转换可以直接单元测试，不需要启动 Textual。

## 18. Adapter 如何处理运行状态

```python
if isinstance(event, AgentStartEvent):
    self.state.running = True
    self.state.error = None
    return

if isinstance(event, AgentEndEvent):
    self._flush_assistant_buffer()
    self.state.running = False
    return
```

当 agent 开始：

```python
running = True
```

当 agent 结束：

```python
running = False
```

并且 flush assistant buffer。

测试：

```python
test_tui_adapter_tracks_running_state
```

验证这个行为。

## 19. Adapter 如何处理 assistant streaming

```python
if isinstance(event, MessageStartEvent):
    if event.message_role == "assistant":
        self.state.assistant_buffer = ""
    return

if isinstance(event, MessageDeltaEvent):
    self.state.assistant_buffer += event.delta
    return
```

开始 assistant message 时清空 buffer。

收到 delta 时追加。

完整消息结束：

```python
if isinstance(event, MessageEndEvent):
    ...
    text = event.message.content or self.state.assistant_buffer
    if text:
        self.state.add_item("assistant", text)
    self.state.assistant_buffer = ""
```

这里 `event.message.content or self.state.assistant_buffer` 是兜底：

如果最终 message content 为空，就用 buffer。

## 20. Adapter 如何处理 tool events

工具开始：

```python
if isinstance(event, ToolExecutionStartEvent):
    self._flush_assistant_buffer()
    self.state.add_tool_call(event.tool_call)
    return
```

先 flush assistant buffer。

为什么？

因为 assistant 可能先输出：

```text
我先读取文件
```

然后发起 tool call。

UI 应该先显示 assistant 的这句话，再显示工具。

工具更新：

```python
self.state.add_item("tool", f"… {event.message}")
```

工具结束：

```python
self.state.record_tool_result(event.result)
```

## 21. Adapter 如何处理错误

源码：

```python
if isinstance(event, ErrorEvent):
    self._flush_assistant_buffer()
    if event.recoverable and event.message == "Agent run cancelled":
        self.state.add_item("status", "Agent run cancelled.")
        return
    self.state.error = event.message
    self.state.add_item("error", f"Error: {event.message}")
    if not event.recoverable:
        self.state.running = False
```

取消运行是一个特殊情况。

如果错误是可恢复的，并且消息是：

```text
Agent run cancelled
```

TUI 把它显示成 status，而不是红色 error。

测试：

```python
test_tui_adapter_renders_cancellation_as_status
```

验证取消会显示：

```text
Agent run cancelled.
```

## 22. widgets.py：SessionSidebar

`SessionSidebar` 是 Textual 的 `Static` widget。

源码：

```python
class SessionSidebar(Static):
    """Compact sidebar with current session metadata."""

    def update_from_session(self, session: SessionSummarySource, *, theme: TuiTheme = TAU_DARK_THEME) -> None:
        self.update(render_session_sidebar(session, theme=theme))
```

它显示 session 元数据，比如：

- model
- cwd
- tools
- skills
- prompt templates
- context usage

当前代码的 sidebar 已经比 Phase 12 初版丰富很多。

但 Phase 12 主线是：

```text
TUI 有一个侧边栏，显示当前 session 环境。
```

## 23. widgets.py：TranscriptView

`TranscriptView` 是滚动 transcript 区域。

源码：

```python
class TranscriptView(VerticalScroll):
    """Scrollable transcript view backed by individual selectable message widgets."""
```

它用：

```python
update_from_state(state)
```

根据 `TuiState` 重画 transcript。

核心流程：

```python
for item in state.items:
    self.mount(TranscriptMessageWidget(item, ...))

if state.assistant_buffer:
    self.mount(TranscriptMessageWidget(ChatItem(role="assistant", text=state.assistant_buffer), ...))
```

这表示：

- 已完成消息来自 `state.items`
- 正在 streaming 的 assistant 内容来自 `state.assistant_buffer`

## 24. Textual 知识：Widget、mount、update

Textual 里 UI 是 widget 树。

常见概念：

### Widget

一个 UI 组件。

比如：

- Header
- Footer
- Static
- Input
- VerticalScroll
- TranscriptView

### mount()

把一个子组件挂到当前组件里。

例如：

```python
self.mount(TranscriptMessageWidget(item))
```

### update()

更新组件内容。

例如：

```python
self.update(render_session_sidebar(session))
```

### refresh()

请求 Textual 重新绘制。

例如：

```python
self.refresh(layout=True)
```

## 25. app.py：TauTuiApp

`TauTuiApp` 是 Textual 应用主体：

```python
class TauTuiApp(App[None]):
    """Interactive Textual frontend for a ``CodingSession``."""
```

它继承自 Textual 的：

```python
App
```

核心职责：

- 保存 `CodingSession`
- 创建 `TuiState`
- 创建 `TuiEventAdapter`
- 组合 UI 布局
- 处理 prompt 输入
- 启动 worker 跑 agent
- 刷新 transcript/sidebar/status

## 26. TauTuiApp.__init__()

源码主线：

```python
self.session = session
self.state = TuiState(skills=session.skills)
self.state.load_messages(session.messages)
self.adapter = TuiEventAdapter(self.state)
self._prompt_worker: Worker[None] | None = None
```

这几行非常关键。

它说明 TUI 启动时：

1. 接收一个已经创建好的 `CodingSession`
2. 用 session.skills 初始化状态
3. 把已有 session.messages 加载到可见 transcript
4. 创建 adapter
5. 准备 worker

这正对应架构文档里：

```text
uses CodingSession rather than raw AgentHarness
restores previous session messages into visible transcript
```

## 27. TauTuiApp.compose()

Textual app 通过 `compose()` 声明 UI 结构。

源码主线：

```python
def compose(self) -> ComposeResult:
    yield Header()
    with Horizontal(id="workspace"):
        yield SessionSidebar(id="sidebar")
        with Vertical(id="main-pane"):
            yield TranscriptView(id="transcript", ...)
            yield Static("", id="queued-messages")
            with Horizontal(id="prompt-row"):
                yield Static("τ", id="prompt-prefix")
                yield PromptInput(...)
            yield CompactSessionInfo(id="compact-session-info")
            yield Static("", id="autocomplete")
    yield Footer()
```

这就是 TUI 页面布局：

```text
Header
workspace
  sidebar
  main-pane
    transcript
    queued messages
    prompt row
      τ prefix
      input
    compact session info
    autocomplete
Footer
```

当前代码已经有 autocomplete 和 compact info，这些是后续能力叠加。

Phase 12 重点看：

```text
sidebar + transcript + input + footer
```

## 28. Python 知识：yield 在 compose() 里是什么意思

普通函数里 `yield` 表示生成器。

Textual 的 `compose()` 用 `yield` 来“产出 widget”。

例如：

```python
yield Header()
yield Footer()
```

Textual 会收集这些 widget，组成界面。

`with Horizontal(...)` 表示在这个容器里面放 widget。

所以：

```python
with Horizontal(id="workspace"):
    yield SessionSidebar(id="sidebar")
```

意思是：

把 sidebar 放进 horizontal workspace 容器里。

## 29. TauTuiApp.on_mount()

源码主线：

```python
async def on_mount(self) -> None:
    prompt = self.query_one(PromptInput)
    prompt.focus()
    self._refresh()
    if self.startup_message:
        self._notify(self.startup_message, severity="warning")
    if self.initial_prompt and self.initial_prompt.strip():
        self._submit_prompt(self.initial_prompt.strip())
```

`on_mount()` 是 Textual 生命周期方法。

当 app 的 widget 树挂载完成后调用。

它做几件事：

- 找到 prompt 输入框
- 让输入框获得焦点
- 刷新页面
- 显示启动提示
- 如果 CLI 传了初始 prompt，直接提交

测试里有：

```python
test_tui_app_runs_initial_prompt
```

验证 initial prompt 能在 TUI 启动后运行。

## 30. 用户提交 prompt 的流程

当前 `app.py` 功能很多，Phase 12 主线可以简化成：

```text
用户在 PromptInput 输入
  -> TUI 判断是不是 command
  -> 如果不是 command
  -> _submit_prompt(text)
  -> run_worker(_run_prompt(...))
```

`_submit_prompt()`：

```python
def _submit_prompt(self, text: str) -> None:
    self._prompt_run_id += 1
    run_id = self._prompt_run_id
    self._follow_transcript_output()
    self._refresh()
    self._prompt_worker = self.run_worker(self._run_prompt(text, run_id), exclusive=True)
```

它不会直接 `await self._run_prompt(...)`。

而是用 Textual worker。

## 31. Textual Worker 是什么

如果 TUI 直接在事件处理函数里长时间 await 模型响应，界面可能卡住。

Worker 允许后台运行异步任务，让 UI 还能刷新。

这里：

```python
self.run_worker(self._run_prompt(text, run_id), exclusive=True)
```

表示：

启动一个 worker 跑 agent prompt。

`exclusive=True` 表示同类 worker 不应该并发乱跑。

这对 TUI 很重要：

```text
agent 在后台 streaming
UI 继续显示 delta、工具、状态
用户还能取消或排队消息
```

## 32. _run_prompt()

源码主线：

```python
async def _run_prompt(self, text: str, run_id: int | None = None) -> None:
    try:
        async for event in self.session.prompt(text):
            if active_run_id != self._prompt_run_id:
                return
            self.adapter.apply(event)
            await self._apply_streaming_transcript_event(event)
    except Exception as exc:
        ...
```

这就是 TUI 消费 agent event 的核心。

对每个事件：

1. 检查 run id 是否仍然有效
2. `adapter.apply(event)` 更新 `TuiState`
3. `_apply_streaming_transcript_event(event)` 更新可见 transcript widget

如果异常：

- 写入 state.error
- 添加 error item
- `running=False`
- 刷新界面

## 33. 为什么需要 _prompt_run_id

当前 TUI 支持取消、新 session、resume 等后续能力。

如果旧 worker 很晚才返回事件，不能让它污染新 session 的界面。

所以代码用：

```python
self._prompt_run_id += 1
run_id = self._prompt_run_id
```

每次提交 prompt 都有一个编号。

worker 中检查：

```python
if active_run_id != self._prompt_run_id:
    return
```

如果不是当前 run，就忽略旧事件。

Phase 12 初版未必已经这么复杂，但当前代码已经加了这个保护。

## 34. CLI 默认进入 TUI

Phase 12 架构文档说：

```bash
tau
```

默认打开 TUI。

`tests/test_cli.py` 里：

```python
test_cli_without_prompt_invokes_tui_runner
```

验证没有 prompt 时会调用：

```python
run_openai_tui(...)
```

并传入：

```python
(None, tmp_path, None, False, None, None, None)
```

另一个测试：

```python
test_cli_positional_prompt_invokes_tui_runner
```

验证：

```bash
tau "explain this repo"
```

也会进入 TUI，并把 `"explain this repo"` 作为 initial prompt。

这说明当前 CLI 设计是：

```text
默认交互式 TUI
print mode 是通过显式模式/路径运行
```

## 35. run_tui_app()

`run_tui_app()` 是创建并运行 TUI 的入口。

源码主线：

```python
provider_settings = load_provider_settings()
shell_settings = load_shell_settings()
manager = session_manager or SessionManager()
...
provider = create_model_provider(...)
...
session = await CodingSession.load(CodingSessionConfig(...))
app = TauTuiApp(session, tui_settings=load_tui_settings(), ...)
await app.run_async()
```

它做的事：

1. 加载 provider settings
2. 加载 shell settings
3. 准备 session manager
4. 创建 model provider
5. 创建 `CodingSession`
6. 创建 `TauTuiApp`
7. 运行 Textual app
8. finally 中关闭 session/provider

这里你要抓住：

```text
TauTuiApp 不自己创建 session
run_tui_app 负责 wiring
```

这让 TUI app 本体更像一个前端组件。

## 36. Phase 12 的临时 session path

架构文档里提到：

```python
def default_session_path(cwd: Path) -> Path:
    return cwd / ".tau" / "sessions" / "default.jsonl"
```

当前代码已经被后续 SessionManager 替代得更完整。

现在 `run_tui_app()` 使用：

```python
SessionManager()
```

并创建 session record，再用：

```python
jsonl_session_storage(record.path)
```

所以这里是一个后续演化点：

```text
Phase 12 初始：简单 default session path
当前实现：SessionManager 管理 indexed sessions
```

学习 Phase 12 时只要明白：

TUI 使用 JSONL session storage，能恢复并继续保存会话。

## 37. tests/test_tui_adapter.py 的价值

这个测试文件特别适合初学者读。

因为它不启动 Textual app。

它只测试：

```text
AgentEvent -> TuiState
```

重点测试：

- `test_tui_adapter_tracks_running_state`
- `test_tui_adapter_builds_assistant_items_from_streamed_messages`
- `test_tui_adapter_builds_user_items_from_streamed_messages`
- `test_tui_adapter_flushes_assistant_buffer_before_tool_events`
- `test_tui_adapter_records_tool_updates_and_results`
- `test_tui_adapter_records_errors_and_stops_on_non_recoverable_error`

这说明 Tau 的 TUI 不是把事件处理逻辑全写在 widget 里。

它先做可测试的 adapter 层。

## 38. tests/test_tui_app.py 怎么看

当前 `tests/test_tui_app.py` 非常大。

里面包含大量后续功能：

- markdown rendering
- responsive layout
- command modal
- session picker
- tree picker
- model picker
- theme picker
- login/logout
- autocomplete
- terminal command
- queue steering/follow-up
- thinking controls

Phase 12 阶段先重点看这些：

```text
test_tui_app_mounts_sidebar_and_transcript
test_tui_app_loads_restored_messages_into_display_state
test_tui_message_start_does_not_mount_empty_assistant_message
test_tui_streaming_deltas_update_active_message_without_full_refresh
test_tui_app_escape_cancels_running_session_from_prompt
test_tui_app_runs_initial_prompt
```

它们更接近第一版 TUI 骨架。

## 39. 初学者容易误解的点

### 误解 1：Textual TUI 直接调用 AgentHarness

不是。

TUI 使用的是：

```python
CodingSession
```

这样它天然拥有：

- tools
- session storage
- skill/prompt resources
- system prompt
- commands

### 误解 2：TuiState 是数据库状态

不是。

`TuiState` 是显示状态。

真正 durable session 在 JSONL storage 里。

TUI state 可以清空、重画、根据 messages 恢复。

### 误解 3：adapter 是 UI widget

不是。

`TuiEventAdapter` 不依赖 Textual。

它只是把 agent events 转成 display state。

### 误解 4：当前 app.py 所有东西都属于 Phase 12

不是。

当前 `app.py` 已经包含很多后续 phase 的功能。

Phase 12 的核心是：

```text
Textual app + prompt input + event adapter + transcript/sidebar + CodingSession
```

## 40. Phase 12 用一句话总结

Phase 12 的价值是：在 `tau_coding.tui` 中建立第一版 Textual 交互式前端，让 CLI 默认进入 TUI，并通过 `TuiEventAdapter` 把 `CodingSession.prompt()` 的 `AgentEvent` 流转换成 `TuiState`，再由 Textual widgets 渲染 sidebar、transcript 和 prompt input；这样 Tau 有了真正的交互界面，同时 `tau_agent` 仍然保持无 Textual/UI 依赖。

## 41. 我的问题与推荐回答

问题：为什么 Phase 12 不让 Textual widget 直接处理所有 `AgentEvent`，而是先经过 `TuiEventAdapter` 和 `TuiState`？

我的推荐回答：

因为 `AgentEvent -> 显示状态` 是一层纯逻辑，应该可以不启动终端 UI 就测试。`TuiEventAdapter` 把 `AgentStartEvent`、`MessageDeltaEvent`、`ToolExecutionStartEvent`、`ErrorEvent` 等事件转换成 `TuiState` 里的 `running`、`assistant_buffer`、`ChatItem`、`error` 等字段；Textual widget 只负责把这些状态画出来。这样事件处理逻辑不会散落在 UI 组件里，测试也更简单，后续 transcript 渲染、主题、响应式布局或 TUI 重构都不需要改 agent core。
