# Phase 8 学习笔记：Coding Session Wrapper

对应架构文档：`dev-notes/architecture/phase-8-coding-session.md`

主要源码：

- `src/tau_coding/session.py`
- `src/tau_coding/commands.py`
- `src/tau_coding/__init__.py`
- `tests/test_coding_session.py`
- `dev-notes/design/04-sessions.md`

前置阶段：

- Phase 1：定义 `AgentMessage` / `AgentEvent`
- Phase 2：定义 provider streaming 层
- Phase 3：实现纯 agent loop
- Phase 4：把 agent loop 包成 `AgentHarness`
- Phase 5：加入 read/write/edit/bash coding tools
- Phase 7：加入 append-only session entries、JSONL storage、session replay

## 1. 这一阶段到底在做什么

Phase 8 给 Tau 加了第一层“coding agent 环境包装器”：`CodingSession`。

你可以先用一句话理解：

`CodingSession` 是把 `AgentHarness`、磁盘 session 文件、cwd、coding tools、slash command 这些“实际编程环境需要的东西”组装到一起的一层。

前面 Phase 4 的 `AgentHarness` 已经能让 agent 跑起来了：

```text
用户消息 -> AgentHarness -> AgentLoop -> ModelProvider -> AgentEvent
```

但是一个真正的 coding agent 还需要更多环境能力：

- 当前工作目录是哪里？
- 默认有哪些工具？
- 之前的对话怎么恢复？
- 新消息怎么保存到 session 文件？
- slash command 怎么处理？
- 以后 TUI、resume、skills、prompt templates 应该插在哪里？

这些都不应该塞进 `tau_agent`。

所以 Phase 8 在 `tau_coding` 里加 `CodingSession`：

```text
tau_agent.AgentHarness
        ^
        |
tau_coding.CodingSession
```

这里的方向要看清楚：

- `CodingSession` 使用 `AgentHarness`
- `AgentHarness` 不知道 `CodingSession`

这就保住了项目最重要的边界：

```text
tau_agent  = 可复用 agent brain
tau_coding = 本地 coding-agent 应用环境
```

## 2. 为什么这一层叫 CodingSession

`Session` 在这里不是简单的“聊天记录”。

它更像一次 coding agent 工作现场：

- 一段 transcript
- 一个模型
- 一个工作目录
- 一组工具
- 一个 session JSONL 文件
- 当前 active leaf
- 当前 system prompt
- 一些命令入口

Pi 的架构里有一个核心概念叫 `AgentSession`。

Tau 的 Phase 8 不是一次性做完整 Pi `AgentSession`，而是先做一个最小版本：

```text
CodingSession =
  AgentHarness
  + SessionStorage
  + restored transcript
  + coding tools
  + command seam
```

这里的 `command seam` 可以理解成“以后放 slash command 的接缝”。

Phase 8 的初始目标不是把 `/model`、`/sessions`、`/compact` 全部做完，而是先给这些能力一个自然的归属位置。

## 3. 为什么它放在 tau_coding，而不是 tau_agent

这个问题非常重要。

`tau_agent` 应该保持 portable。

portable 的意思是：

同一个 agent brain 可以被不同前端使用：

- print-mode CLI
- Rich renderer
- Textual TUI
- 以后也可以是 Web UI
- 甚至也可以被别的 Python 程序调用

所以 `tau_agent` 里不应该知道这些东西：

- 本地 session 文件路径
- 当前项目 cwd 的含义
- `.agents` 目录
- CLI 参数
- slash commands
- Textual widget
- Rich 渲染
- Tau 自己的资源加载逻辑

这些是 coding app 的事情，所以放在 `tau_coding`。

架构分层可以画成：

```text
src/tau_ai/
  负责 provider / model streaming

src/tau_agent/
  负责 message / event / tool abstraction / loop / harness / session primitive

src/tau_coding/
  负责本地 coding-agent 应用：
  cwd、工具选择、session 文件、命令、资源、CLI、TUI
```

`CodingSession` 正好站在 `tau_coding` 的入口位置。

## 4. 先看 CodingSessionConfig

源码位置：`src/tau_coding/session.py`

`CodingSessionConfig` 是一个 dataclass：

```python
@dataclass(frozen=True, slots=True)
class CodingSessionConfig:
    provider: ModelProvider
    model: str
    storage: SessionStorage
    cwd: Path
    system: str | None = None
    ...
```

它的作用是：

把创建一个 `CodingSession` 需要的外部依赖和配置集中放在一个对象里。

最核心字段是：

```python
provider: ModelProvider
model: str
storage: SessionStorage
cwd: Path
system: str | None = None
tools: list[AgentTool] | None = None
```

逐个解释：

### provider

```python
provider: ModelProvider
```

这是 Phase 2 的模型提供者抽象。

`CodingSession` 自己不直接调用 OpenAI、Anthropic 或其他 API。

它只依赖 `ModelProvider`：

```text
CodingSession -> AgentHarness -> ModelProvider
```

这样测试时可以传 `FakeProvider`，不用真的访问网络。

### model

```python
model: str
```

表示当前 session 默认使用哪个模型。

例如：

```python
model="gpt-4.1-mini"
```

在测试里常用：

```python
model="fake"
```

### storage

```python
storage: SessionStorage
```

这是 Phase 7 的 session storage 抽象。

它负责：

- `read_all()`
- `append(entry)`

常见实现是：

```python
JsonlSessionStorage(path)
```

注意：`CodingSession` 只依赖 `SessionStorage` 协议，不强绑 JSONL。

这意味着以后可以替换成：

- 内存 storage
- 数据库 storage
- 远端 storage

只要满足同一个协议即可。

### cwd

```python
cwd: Path
```

`cwd` 是 current working directory，也就是当前 coding agent 在哪个项目目录工作。

它会影响：

- read/write/edit/bash 工具的根目录
- system prompt 里展示的项目路径
- 资源发现
- session manager 按项目过滤 session

初学者要注意：这里用的是 `pathlib.Path`，不是普通字符串。

例如：

```python
from pathlib import Path

cwd = Path.cwd()
```

`Path` 的好处是路径拼接更安全：

```python
cwd / "README.md"
```

比字符串拼接：

```python
cwd + "/README.md"
```

更清晰，也更跨平台。

### system

```python
system: str | None = None
```

`system` 是系统提示词。

如果传了：

```python
system="You are Tau."
```

就直接用这个。

如果没传，当前代码会通过 `build_system_prompt(...)` 动态组装。

这个动态组装主要属于后续 Phase 9 / Phase 10 / Phase 13 / Phase 19 的扩展。

读 Phase 8 时先记住：

```text
CodingSession 负责把最终 system prompt 交给 AgentHarness。
```

## 5. Python 知识：dataclass(frozen=True, slots=True)

`CodingSessionConfig` 使用：

```python
@dataclass(frozen=True, slots=True)
```

这是标准库 `dataclasses` 提供的功能。

### dataclass 是什么

普通 Python 类如果要保存数据，通常要手写：

```python
class User:
    def __init__(self, name: str, age: int):
        self.name = name
        self.age = age
```

`dataclass` 可以帮你自动生成 `__init__` 等方法：

```python
from dataclasses import dataclass

@dataclass
class User:
    name: str
    age: int

user = User(name="Alice", age=18)
```

### frozen=True

`frozen=True` 表示对象创建后字段不应该被改。

例如：

```python
config = CodingSessionConfig(...)
config.model = "other"
```

这种修改会报错。

好处是：

- 配置对象更稳定
- 减少“谁偷偷改了配置”的问题
- 更适合传来传去

不过源码里也会用 `dataclasses.replace(...)` 创建一个改过的新 config。

例如：

```python
replace(self._config, model="new-model")
```

这不是原地修改，而是生成一个新对象。

### slots=True

`slots=True` 会限制对象只能有 dataclass 声明过的字段。

比如：

```python
config.xxx = 123
```

如果 `xxx` 不是字段，就不能随便加。

好处：

- 更省内存
- 防止拼错字段名
- 数据结构更明确

## 6. CodingSession.load() 是核心入口

创建 session 不是直接：

```python
CodingSession(...)
```

而是：

```python
session = await CodingSession.load(config)
```

为什么用 `load`？

因为它要做异步 IO：

- 从 storage 读 JSONL entries
- 必要时加载资源
- 创建 harness

所以它是：

```python
@classmethod
async def load(cls, config: CodingSessionConfig) -> CodingSession:
```

这里有两个 Python 语法点：

### @classmethod

普通方法第一个参数是 `self`：

```python
def foo(self):
    ...
```

`@classmethod` 的第一个参数是 `cls`：

```python
@classmethod
def load(cls, config):
    ...
```

`cls` 表示“当前类本身”。

所以在方法内部可以：

```python
session = cls(...)
```

这样如果以后有子类继承 `CodingSession`，`load()` 也能返回子类实例。

### async def

`async def` 定义异步函数。

调用时不能直接：

```python
session = CodingSession.load(config)
```

而要：

```python
session = await CodingSession.load(config)
```

因为里面有：

```python
entries = await config.storage.read_all()
```

读文件是 IO 操作，所以用 `await`。

## 7. load() 第一步：读取 session entries

源码主线：

```python
entries = await config.storage.read_all()
pending_initial_entries: tuple[SessionEntry, ...] = ()
```

意思是：

先从 storage 里读出所有历史 entries。

如果是 JSONL storage，就是从 session JSONL 文件里逐行读。

这里读到的 entries 可能包括：

- `SessionInfoEntry`
- `ModelChangeEntry`
- `ThinkingLevelChangeEntry`
- `MessageEntry`
- `LeafEntry`
- `CompactionEntry`
- `BranchSummaryEntry`

Phase 8 最关心的是：

- metadata entries
- message entries
- leaf entries

## 8. 空 session：先准备元信息，但不立刻写文件

当前源码里有一个很重要的行为：

```python
if not entries:
    info = SessionInfoEntry(cwd=str(config.cwd))
    model = ModelChangeEntry(parent_id=info.id, model=config.model)
    thinking = ThinkingLevelChangeEntry(
        parent_id=model.id,
        thinking_level=config.thinking_level,
    )
    entries = [info, model, thinking]
    pending_initial_entries = (info, model, thinking)
```

如果 storage 里什么都没有，Tau 会先构造：

```text
SessionInfoEntry
  -> ModelChangeEntry
    -> ThinkingLevelChangeEntry
```

但注意：

这些 entry 先放在内存里，不马上写进文件。

变量名叫：

```python
pending_initial_entries
```

pending 的意思是“待处理的、还没落盘的”。

为什么不马上写？

因为一个用户打开 TUI 后可能什么都没说就退出。

如果一加载 session 就写文件，会制造很多空 session 文件。

所以设计是：

```text
load 空 session
  -> 内存里准备初始 metadata
  -> 等第一次真正持久化消息时
  -> 再把 metadata 一起写入 JSONL
```

这个行为在测试里叫：

```python
test_load_empty_session_defers_transcript_file
```

测试会确认：

```python
entries = await storage.read_all()
assert entries == []
assert not storage.path.exists()
```

也就是加载空 session 不会创建文件。

## 9. 非空 session：replay 恢复状态

如果 session 文件里已经有 entries，源码会做：

```python
entries = _detach_missing_parents(entries)
linear_state = SessionState.from_entries(entries)
latest_leaf = _latest_leaf_entry(entries)
state = (
    SessionState.from_entries(entries, leaf_id=latest_leaf.entry_id)
    if latest_leaf is not None
    else linear_state
)
```

这里的概念来自 Phase 7。

### linear_state

```python
linear_state = SessionState.from_entries(entries)
```

这表示按 entries 顺序整体 replay。

### latest_leaf

```python
latest_leaf = _latest_leaf_entry(entries)
```

`LeafEntry` 表示当前 active branch 指向哪一个 entry。

JSONL 是 append-only 的，所以可能有多个 leaf：

```text
message A
leaf -> A
message B
leaf -> B
branch to A
leaf -> A
```

最后一个 leaf 才表示当前 active leaf。

### leaf_id replay

```python
SessionState.from_entries(entries, leaf_id=latest_leaf.entry_id)
```

这表示：

不要把所有 sibling branch 都放进当前上下文，只恢复从 root 到 active leaf 的路径。

这是 session tree 的价值。

## 10. Python 知识：三元表达式

这段：

```python
state = (
    SessionState.from_entries(entries, leaf_id=latest_leaf.entry_id)
    if latest_leaf is not None
    else linear_state
)
```

是 Python 的条件表达式。

格式是：

```python
值1 if 条件 else 值2
```

可以理解成：

```python
if latest_leaf is not None:
    state = SessionState.from_entries(entries, leaf_id=latest_leaf.entry_id)
else:
    state = linear_state
```

这不是特殊框架语法，是 Python 自带语法。

## 11. 创建 coding tools

`CodingSession.load()` 接着处理工具：

```python
tools = (
    config.tools
    if config.tools is not None
    else create_coding_tools(
        cwd=config.cwd,
        shell_command_prefix=config.shell_command_prefix,
    )
)
```

意思是：

如果调用方显式传了 tools，就用调用方的。

如果没传，就创建默认 coding tools：

```text
read
write
edit
bash
```

这来自 Phase 5。

为什么工具创建放在 `tau_coding`？

因为这些工具有本地 coding 环境含义：

- 读当前项目文件
- 写当前项目文件
- 编辑当前项目文件
- 在 cwd 下执行 shell 命令

`tau_agent` 不应该知道这些本地环境细节。

测试里会验证：

```python
assert [tool.name for tool in session.tools] == ["read", "write", "edit", "bash"]
```

## 12. 创建 AgentHarness

`load()` 的关键一步是：

```python
harness = AgentHarness(
    AgentHarnessConfig(
        provider=config.provider,
        model=state.model or config.model,
        system=system,
        tools=tools,
    ),
    messages=state.messages,
)
```

这一段把前面所有阶段串起来了。

`AgentHarnessConfig` 需要：

- provider
- model
- system
- tools

`messages=state.messages` 表示：

如果这是一个恢复出来的 session，就把历史 transcript 放回 harness。

于是后续继续 prompt 时，模型能看到旧上下文。

数据流是：

```text
JSONL entries
  -> SessionState.from_entries()
  -> state.messages
  -> AgentHarness(messages=state.messages)
```

这就是 resume 能成立的基础。

## 13. CodingSession.__init__ 保存什么

`load()` 最后会调用：

```python
session = cls(
    config,
    state=state,
    harness=harness,
    last_parent_id=_last_parent_id_from_state(state),
    ...
)
```

`CodingSession` 内部最核心的几个字段是：

```python
self._config = config
self._state = state
self._harness = harness
self._last_parent_id = last_parent_id
self._pending_initial_entries = pending_initial_entries
```

逐个解释：

### _config

创建 session 的配置。

包括 provider、model、storage、cwd 等。

### _state

从 JSONL replay 出来的 durable state。

这是“磁盘上已经确认保存过的状态”的内存视图。

### _harness

真正负责跑 agent 的 brain。

`CodingSession.prompt()` 最终会调用：

```python
self._harness.prompt(...)
```

### _last_parent_id

下一条 session entry 应该挂在哪个 parent 后面。

如果当前最后一条消息 entry id 是：

```text
msg-123
```

那么下一条消息 entry 的 parent 就应该是：

```python
parent_id="msg-123"
```

这个字段让 append-only tree 能继续往下生长。

### _pending_initial_entries

空 session 初始 metadata 的暂存区。

第一次真正写入消息前，会先把这些 metadata 写进去。

## 14. CodingSession 暴露的基础属性

当前 `CodingSession` 有很多 property。

Phase 8 主线先看这些：

```python
@property
def cwd(self) -> Path:
    return self._config.cwd

@property
def model(self) -> str:
    return self._harness.config.model

@property
def tools(self) -> tuple[AgentTool, ...]:
    return tuple(self._harness.config.tools)

@property
def messages(self) -> tuple[AgentMessage, ...]:
    return self._harness.messages

@property
def state(self) -> SessionState:
    return self._state

@property
def storage(self) -> SessionStorage:
    return self._config.storage
```

`@property` 是 Python 的属性装饰器。

它让你可以这样访问：

```python
session.model
```

而不是：

```python
session.model()
```

但是背后其实执行了一个方法。

为什么很多地方返回 `tuple(...)`？

比如：

```python
return tuple(self._harness.config.tools)
```

因为 tuple 不容易被外部直接修改。

如果直接返回 list，调用方可能：

```python
session.tools.append(...)
```

这会绕过 `CodingSession` 的控制。

## 15. prompt() 是一次用户输入的主入口

用户正常输入一句话时，会走：

```python
async for event in session.prompt("Read README.md"):
    ...
```

`prompt()` 是一个 async generator。

函数签名：

```python
async def prompt(
    self,
    content: str,
    *,
    streaming_behavior: StreamingBehavior | None = None,
) -> AsyncIterator[AgentEvent]:
```

这里有几个 Python 知识点。

### AsyncIterator

`AsyncIterator[AgentEvent]` 表示：

这个函数会异步地产生一串 `AgentEvent`。

调用方式是：

```python
async for event in session.prompt("Hello"):
    print(event)
```

不是：

```python
events = await session.prompt("Hello")
```

因为 agent streaming 是一点一点返回事件的。

### 参数里的 *

```python
async def prompt(self, content: str, *, streaming_behavior: ... = None)
```

`*` 后面的参数必须用关键字传。

也就是说可以：

```python
session.prompt("hello", streaming_behavior="steer")
```

不可以：

```python
session.prompt("hello", "steer")
```

这样代码可读性更好。

## 16. prompt() 的第一步：扩展 prompt text

当前源码：

```python
expanded_content = self.expand_prompt_text(content)
```

这一步属于后续 skills 和 prompt templates 的扩展。

Phase 8 初始版本可以先理解为：

```text
用户输入 content
  -> 可能被扩展
  -> 交给 AgentHarness.prompt()
```

例如后续可能支持：

```text
/skill:python-review 这段代码哪里有问题？
```

或者：

```text
/prompt:commit-message
```

但 Phase 8 的主线不是这些资源系统。

## 17. prompt() 的核心：调用 harness

核心循环是：

```python
persisted_count = len(self._harness.messages)

async for event in self._harness.prompt(expanded_content):
    if isinstance(event, MessageEndEvent):
        persisted_count = await self._persist_messages_since(persisted_count)
    yield event
```

这段非常关键。

先记录：

```python
persisted_count = len(self._harness.messages)
```

意思是：

在这次 prompt 开始前，harness 里已经有多少条消息。

然后运行：

```python
self._harness.prompt(expanded_content)
```

`AgentHarness` 会把用户消息加入 transcript，然后调用 agent loop。

每当 agent loop 产生事件，`CodingSession` 会继续把事件转发给上层：

```python
yield event
```

也就是说：

```text
Provider events / Agent events
  -> AgentHarness
  -> CodingSession.prompt()
  -> CLI/TUI renderer
```

`CodingSession` 不是 renderer。

它不负责把事件画出来。

它只负责：

- 调用 harness
- 观察事件
- 在合适时机持久化消息
- 把事件继续往外抛

## 18. durable-message boundary：MessageEndEvent

`dev-notes/design/04-sessions.md` 里有一句很重要：

`CodingSession` treats `MessageEndEvent` as the durable-message boundary.

翻译一下：

`CodingSession` 把 `MessageEndEvent` 当成“这条消息已经完整，可以持久化”的边界。

为什么不是看到一段文字 delta 就保存？

因为 streaming 时 assistant 可能一点一点吐字：

```text
"Hel"
"lo"
"!"
```

这些中间片段不应该各自变成一条消息。

只有模型最终完成一条 assistant message，agent loop 发出 `MessageEndEvent` 时，才说明：

```text
这条消息完整了，可以保存成 MessageEntry。
```

所以源码里：

```python
if isinstance(event, MessageEndEvent):
    persisted_count = await self._persist_messages_since(persisted_count)
```

这比“整个 run 完成后再保存”更稳。

因为如果 assistant 已经完成一条 tool call message，然后进程崩了，已经完成的消息仍可以落盘。

## 19. _persist_messages_since() 做了什么

源码：

```python
async def _persist_messages_since(self, persisted_count: int) -> int:
    new_messages = self._harness.messages[persisted_count:]
    if not new_messages:
        return persisted_count

    for message in new_messages:
        entry = MessageEntry(parent_id=self._last_parent_id, message=message)
        await self._append_session_entry(entry)
        self._last_parent_id = entry.id
        leaf = LeafEntry(parent_id=entry.id, entry_id=entry.id)
        await self._append_session_entry(leaf)

    await self._refresh_persisted_state()
    return persisted_count + len(new_messages)
```

一步一步看。

### 找出新消息

```python
new_messages = self._harness.messages[persisted_count:]
```

这是 Python 切片。

如果：

```python
self._harness.messages = [m0, m1, m2, m3]
persisted_count = 2
```

那么：

```python
self._harness.messages[persisted_count:]
```

得到：

```python
[m2, m3]
```

也就是还没保存的新消息。

### 每条消息变成 MessageEntry

```python
entry = MessageEntry(parent_id=self._last_parent_id, message=message)
```

这把普通 message 包装成 session entry。

`parent_id` 负责把它接到 session tree 上。

### append 到 storage

```python
await self._append_session_entry(entry)
```

最终会写入 JSONL。

### 更新 parent

```python
self._last_parent_id = entry.id
```

下一条消息就接在这条消息后面。

### 写 LeafEntry

```python
leaf = LeafEntry(parent_id=entry.id, entry_id=entry.id)
await self._append_session_entry(leaf)
```

每保存一条消息，都追加一个 leaf。

leaf 的意思是：

```text
当前 active branch 指向这条消息。
```

这样 TUI 在运行中也能看到当前 branch 进展。

## 20. _append_session_entry() 为什么先 ensure initialized

源码：

```python
async def _append_session_entry(self, entry: SessionEntry) -> None:
    await self._ensure_session_initialized()
    await self._config.storage.append(entry)
```

它先调用：

```python
await self._ensure_session_initialized()
```

原因是前面说过：

空 session 的 initial metadata 是 pending 的。

第一次真正 append 时，要先把这些 pending entries 写进去。

源码：

```python
async def _ensure_session_initialized(self) -> None:
    if not self._pending_initial_entries:
        return
    for entry in self._pending_initial_entries:
        await self._config.storage.append(entry)
    self._pending_initial_entries = ()
```

所以第一次用户 prompt 后，JSONL 顺序会是：

```text
SessionInfoEntry
ModelChangeEntry
ThinkingLevelChangeEntry
MessageEntry(user)
LeafEntry(user)
MessageEntry(assistant)
LeafEntry(assistant)
```

测试 `test_prompt_persists_user_assistant_and_leaf_entries` 验证的就是这个行为。

## 21. _refresh_persisted_state() 的作用

保存消息后，内存里的 durable state 也要更新。

源码：

```python
entries = await self._read_session_entries()
self._state = SessionState.from_entries(entries)
```

这表示：

每次持久化后，重新从 storage replay 一次，得到最新 `SessionState`。

这有两个好处：

1. 内存状态和磁盘状态保持一致
2. session tree / compaction / branch 这些行为都用同一套 replay 逻辑

它不是自己手动改一堆字段：

```python
self._state.messages += ...
self._state.model = ...
```

而是让 `SessionState.from_entries()` 成为唯一的状态恢复规则。

这是一个很好的工程习惯：

```text
保存格式是什么，恢复逻辑就从保存格式推导。
```

## 22. continue_() 和 prompt() 的区别

`prompt()` 会先追加一个新的 user message。

`continue_()` 不追加新用户消息，只是让 agent 从当前 transcript 继续。

源码：

```python
async def continue_(self) -> AsyncIterator[AgentEvent]:
    persisted_count = len(self._harness.messages)
    async for event in self._harness.continue_():
        if isinstance(event, MessageEndEvent):
            persisted_count = await self._persist_messages_since(persisted_count)
        yield event
```

什么时候用 `continue_()`？

典型场景：

- 恢复了一个 session
- 最后一条消息是 user message
- 需要让 assistant 继续回答

测试：

```python
test_continue_persists_only_new_messages
```

它先手动写入一条 user message：

```python
MessageEntry(id="user", message=UserMessage(content="Continue me"))
```

然后 load session，再调用：

```python
session.continue_()
```

最后确认 storage 里只有：

```text
UserMessage("Continue me")
AssistantMessage("Continued")
```

不会重复保存旧 user message。

## 23. tool result 也会被持久化

Phase 3 / Phase 4 的 agent loop 支持工具调用。

当 assistant 发起 tool call，loop 会执行工具，并把工具结果放回 transcript。

这些消息也在 harness 的 messages 里。

所以 `CodingSession` 不需要特别认识每一种消息。

它只要做：

```python
new_messages = self._harness.messages[persisted_count:]
```

然后统一保存成：

```python
MessageEntry(...)
```

测试：

```python
test_tool_results_are_persisted
```

会确认 messages 中存在：

```python
ToolResultMessage
```

这说明 `CodingSession` 的持久化边界足够通用。

## 24. slash command seam

Phase 8 的架构文档说：

`CodingSession.handle_command()` 先支持一个很小的命令入口。

当前代码已经把命令逻辑扩展到了 `src/tau_coding/commands.py`。

`CodingSession` 里是：

```python
def handle_command(self, text: str) -> CommandResult:
    if expand_prompt_template_command(text, self._prompt_templates) is not None:
        return CommandResult(handled=False)
    return self._command_registry.execute(self, text)
```

这说明 `CodingSession` 不再手写：

```python
if text == "/help":
    ...
```

而是委托给：

```python
CommandRegistry
```

这是后续 phase 发展出来的结果。

但是从 Phase 8 的角度看，重点不是命令数量，而是这个边界：

```text
普通用户 prompt -> handled=False -> 交给 prompt()
slash command  -> handled=True  -> UI/CLI 根据 CommandResult 行动
```

## 25. CommandResult 是命令结果对象

`src/tau_coding/commands.py` 里有：

```python
@dataclass(frozen=True, slots=True)
class CommandResult:
    handled: bool
    exit_requested: bool = False
    clear_requested: bool = False
    new_session_requested: bool = False
    ...
    message: str | None = None
```

它不是直接执行所有 UI 行为，而是返回一个结果。

例如：

```python
CommandResult(handled=True, exit_requested=True, message="Exiting session.")
```

上层 TUI 或 CLI 看到 `exit_requested=True`，再决定退出。

为什么这样设计？

因为 `CodingSession` 不应该直接控制具体前端。

它只表达：

```text
这个命令请求退出
这个命令请求新 session
这个命令请求 export
这个命令只是返回一段 message
```

真正怎么显示 message、怎么退出，是 UI 层的事。

## 26. 当前代码和 Phase 8 文档的差异

你会发现一个现象：

`phase-8-coding-session.md` 里说 Phase 8 的命令非常少，但当前 `commands.py` 已经有很多命令：

- `/quit`
- `/new`
- `/compact`
- `/export`
- `/session`
- `/skill`
- `/hotkeys`
- `/reload`
- `/resume`
- `/tree`
- `/name`
- `/model`
- `/scoped-models`
- `/theme`
- `/login`
- `/logout`

这是因为仓库代码已经走到了后续 phase。

所以学习时要这样分层：

```text
Phase 8 要学：
  CodingSession 这层为什么存在
  它如何 load/replay
  它如何创建 harness
  它如何持久化新消息
  它如何提供 command seam

后续 phase 再学：
  skill / prompt template
  system prompt assembly
  session manager / resume
  provider config
  compaction
  branching
```

不要因为当前 `session.py` 很大，就误以为 Phase 8 一次做完了所有事情。

## 27. terminal command 输入：! 和 !!

当前 `session.py` 还有：

```python
def parse_terminal_command(text: str) -> TerminalCommandRequest | None:
    stripped = text.strip()
    if stripped.startswith("!!"):
        command = stripped[2:].strip()
        ...
        return TerminalCommandRequest(command=command, add_to_context=False)
    if stripped.startswith("!"):
        command = stripped[1:].strip()
        ...
        return TerminalCommandRequest(command=command, add_to_context=True)
    return None
```

这表示输入栏可以解析两种 shell 命令：

```text
! pwd
```

运行命令，并把输出加入 agent 上下文。

```text
!! pwd
```

运行命令，但不加入 agent 上下文。

返回对象是：

```python
TerminalCommandRequest(command="pwd", add_to_context=True)
```

注意这里 `!!` 要先判断。

如果先判断 `!`，那么 `!! pwd` 也会被当成单个 `!` 开头，解析就错了。

测试：

```python
test_parse_terminal_command_prefixes
```

验证了：

- `! pwd` -> add_to_context True
- `!! pwd` -> add_to_context False
- `hello` -> None

## 28. run_terminal_command()

当前代码还有：

```python
async def run_terminal_command(
    self,
    command: str,
    *,
    add_to_context: bool,
) -> TerminalCommandResult:
```

它的作用是：

在 session cwd 下运行一个 shell 命令，并可选地把结果作为 user message 保存进上下文。

核心步骤：

1. 去掉命令两边空白
2. 创建 bash tool
3. 执行 bash tool
4. 如果 `add_to_context=True`，把命令和输出包装成 `UserMessage`
5. 调用 `_persist_messages_since()` 保存
6. 返回 `TerminalCommandResult`

如果加入上下文，它构造的 message 大概是：

```text
Terminal command executed by the user.

Command:
```bash
printf hello
```

Output:
```text
hello
```
```

这样 agent 后续能知道：

用户刚刚运行了什么命令，输出是什么。

测试：

```python
test_terminal_command_can_persist_output_to_context
test_terminal_command_can_run_without_context
```

分别验证加入上下文和不加入上下文两种情况。

## 29. Python 知识：Literal 类型

源码中有：

```python
StreamingBehavior = Literal["steer", "follow_up"]
```

`Literal` 来自：

```python
from typing import Literal
```

它表示某个变量只能是固定字面量之一。

这里表示：

```python
streaming_behavior
```

只能是：

```text
"steer"
"follow_up"
None
```

这对类型检查器很有用。

例如你写：

```python
session.prompt("hi", streaming_behavior="abc")
```

类型检查器就能提醒你不对。

## 30. Python 知识：Final

源码中有：

```python
_UNSET_LEAF_ID: Final[object] = object()
```

`Final` 表示这个变量不应该再被重新赋值。

这里 `_UNSET_LEAF_ID` 是一个哨兵对象。

哨兵对象的用途是区分：

```python
leaf_id 没传
```

和：

```python
leaf_id 明确传了 None
```

为什么要区分？

因为在 session tree 里：

- 没传 leaf_id：按默认逻辑恢复
- 传 `leaf_id=None`：可能表示恢复空分支

这两种语义不一样。

所以不能只用 `None`。

## 31. Python 知识：cast

源码里有：

```python
cast(str | None, leaf_id)
```

`cast` 来自：

```python
from typing import cast
```

它主要是给类型检查器看的。

运行时基本不改变值。

它的意思是：

```text
我作为程序员确认：这里的 leaf_id 可以当成 str | None。
```

为什么需要？

因为函数参数类型里允许：

```python
str | None | object
```

也就是可能是哨兵对象。

但经过判断：

```python
if leaf_id is _UNSET_LEAF_ID:
    ...
else:
    ...
```

在 else 分支里，开发者知道它不是哨兵了。

类型检查器有时没法完全推断，所以用 `cast` 帮它。

## 32. Python 知识：isinstance

源码里经常出现：

```python
if isinstance(event, MessageEndEvent):
    ...
```

`isinstance(obj, Class)` 用来判断对象是不是某个类型。

例如：

```python
message = UserMessage(content="Hi")

if isinstance(message, UserMessage):
    print("这是用户消息")
```

在 Tau 里，事件和消息都是多种类型的联合。

所以经常要判断：

- 这是 `MessageEndEvent` 吗？
- 这是 `ErrorEvent` 吗？
- 这是 `UserMessage` 吗？
- 这是 `AssistantMessage` 吗？
- 这是 `ToolResultMessage` 吗？

## 33. Python 知识：tuple 类型标注

源码中有：

```python
pending_initial_entries: tuple[SessionEntry, ...] = ()
```

`tuple[SessionEntry, ...]` 的意思是：

这是一个 tuple，里面每个元素都是 `SessionEntry`，数量不限。

如果写：

```python
tuple[str, int]
```

则表示固定两个元素：

```python
("Alice", 18)
```

但：

```python
tuple[SessionEntry, ...]
```

表示：

```python
()
(entry1,)
(entry1, entry2, entry3)
```

都可以。

## 34. __init__.py 的作用

`src/tau_coding/__init__.py` 把很多对象重新导出。

例如：

```python
from tau_coding.session import (
    CodingSession,
    CodingSessionConfig,
    ...
)
```

然后在 `__all__` 里列出来。

这让外部可以写：

```python
from tau_coding import CodingSession, CodingSessionConfig
```

而不是：

```python
from tau_coding.session import CodingSession, CodingSessionConfig
```

这种设计叫 package public API。

它的好处是：

- 外部导入更简洁
- 包的入口更稳定
- 内部文件以后可以调整，外部不一定受影响

## 35. tests/test_coding_session.py 怎么读

这个测试文件很大，因为当前 `CodingSession` 已经包含后续很多功能。

学习 Phase 8 时，先重点看这些测试：

```text
test_load_empty_session_defers_transcript_file
test_prompt_persists_user_assistant_and_leaf_entries
test_load_restores_existing_transcript
test_continue_persists_only_new_messages
test_tool_results_are_persisted
test_parse_terminal_command_prefixes
test_terminal_command_can_persist_output_to_context
test_terminal_command_can_run_without_context
test_minimal_commands_are_handled
```

这些测试覆盖 Phase 8 的主线：

- 空 session 加载
- 首次 prompt 后落盘
- transcript restore
- continue 不重复保存旧消息
- tool result 持久化
- terminal command 输入解析
- slash command seam

其他测试也很重要，但更多属于后续 phase：

- session export
- diagnostics
- queue steering
- tree branching
- thinking controls
- skills
- prompt templates
- resource reload
- compaction
- provider switching
- resume / new session

## 36. 一次 prompt 的完整流程

现在把 Phase 8 的主流程串起来。

### 第一次加载空 session

```text
CodingSession.load(config)
  -> storage.read_all()
  -> entries 为空
  -> 创建 SessionInfoEntry / ModelChangeEntry / ThinkingLevelChangeEntry
  -> 这些 entry 暂存在 pending_initial_entries
  -> 创建默认 coding tools
  -> 创建 AgentHarness
  -> 返回 CodingSession
```

此时磁盘还没有 session 文件。

### 用户输入 prompt

```text
session.prompt("Hello")
  -> expand_prompt_text("Hello")
  -> persisted_count = len(harness.messages)
  -> harness.prompt("Hello")
  -> 产生 AgentEvent
  -> 遇到 MessageEndEvent
  -> _persist_messages_since(persisted_count)
```

### 第一次持久化消息

```text
_persist_messages_since()
  -> 找到新消息
  -> _append_session_entry(MessageEntry)
      -> _ensure_session_initialized()
          -> 写 pending metadata
      -> storage.append(MessageEntry)
  -> 写 LeafEntry
  -> _refresh_persisted_state()
```

最终 JSONL 里有：

```text
session_info
model_change
thinking_level_change
message(user)
leaf(user)
message(assistant)
leaf(assistant)
```

## 37. 它和 Pi 设计的对应关系

Pi 的大结构可以粗略理解成：

```text
AgentHarness = 可复用 agent brain
AgentSession = 编程环境和会话状态
TUI = 前端
```

Tau 到 Phase 8 时对应：

```text
tau_agent.AgentHarness
  对应 AgentHarness

tau_coding.CodingSession
  开始对应 AgentSession

print-mode CLI / 未来 Textual app
  对应前端
```

`CodingSession` 还不是完整的 Pi `AgentSession`。

但它已经建立了最重要的方向：

```text
brain 和 coding environment 分离
```

这使得后面每个功能都有自然的位置：

- skills：session load 时加载资源
- system prompt：session load 时组装
- resume：session manager 选择 storage，再 load
- TUI：消费 session.prompt() 的事件
- compaction：向 session tree 追加 compaction entry
- branching：改变 active leaf

## 38. 初学者容易误解的点

### 误解 1：CodingSession 是 agent 大脑

不是。

真正的 agent 大脑是：

```python
AgentHarness
```

`CodingSession` 是运行环境和持久化包装。

### 误解 2：session.state 和 harness.messages 永远自动同步

不是完全自动。

`harness.messages` 是当前运行中的内存 transcript。

`session._state` 是从 durable entries replay 出来的状态。

保存新消息后，代码会调用：

```python
await self._refresh_persisted_state()
```

这时 durable state 才刷新。

### 误解 3：加载空 session 就一定创建 JSONL 文件

不是。

空 session 是 deferred file creation。

只有第一次 append durable entry 时才写文件。

### 误解 4：slash command 就是普通 prompt

不是。

普通 prompt：

```python
CommandResult(handled=False)
```

slash command：

```python
CommandResult(handled=True, ...)
```

上层前端会先问：

```python
result = session.handle_command(text)
```

如果没处理，再交给：

```python
session.prompt(text)
```

## 39. 你应该掌握的最小代码地图

Phase 8 学完后，你至少要能说清楚这些函数：

```text
CodingSessionConfig
  创建 CodingSession 需要的配置

CodingSession.load()
  从 storage 读 entries，replay state，创建 tools 和 AgentHarness

CodingSession.prompt()
  处理一次用户输入，转发 harness events，并持久化完成消息

CodingSession.continue_()
  不追加新 user message，从当前 transcript 继续运行

CodingSession._persist_messages_since()
  把 harness 中新增消息写成 MessageEntry + LeafEntry

CodingSession._ensure_session_initialized()
  第一次落盘前补写 pending metadata

CodingSession.handle_command()
  给 slash command 留出应用层入口

parse_terminal_command()
  解析 ! / !! 输入栏 shell 命令
```

## 40. 这个阶段新增的测试价值

Phase 8 的测试不是在测“模型聪不聪明”。

它测试的是 session wrapper 的工程行为：

- 空 session 不污染磁盘
- 第一次消息会写 metadata
- user / assistant messages 会保存
- leaf 会指向最新消息
- 旧 transcript 能恢复
- continue 不重复保存旧消息
- tool result 也能保存
- command seam 能区分普通输入和 slash command

这类测试非常适合 coding agent 项目。

因为 agent 本身输出不稳定，但 wrapper 行为应该稳定。

比如：

```text
给定 FakeProvider 返回 AssistantMessage("Hi")
调用 session.prompt("Hello")
storage 中必须出现 UserMessage("Hello") 和 AssistantMessage("Hi")
```

这是确定性的。

## 41. Phase 8 用一句话总结

Phase 8 的价值是：在 `tau_coding` 中建立 `CodingSession` 这一层，把可复用的 `AgentHarness` 接入本地 coding-agent 环境，并负责从 JSONL session 恢复 transcript、注册 coding tools、运行 prompt/continue、把完成消息追加为 durable session entries，为后续 skills、system prompt、resume、TUI、compaction 和 branching 提供稳定插入点。

## 42. 我的问题与推荐回答

问题：既然 `AgentHarness` 已经能接收 prompt 并调用模型，为什么 Tau 还需要 `CodingSession`？

我的推荐回答：

因为 `AgentHarness` 只应该是可复用的 agent brain，它不应该知道本地工作目录、session JSONL 文件、默认 coding tools、slash commands、资源加载、TUI 或 CLI。`CodingSession` 位于 `tau_coding`，负责把这些 coding-agent 环境能力包在 `AgentHarness` 外面：加载并 replay session entries，创建 harness，注册 read/write/edit/bash 工具，运行 prompt/continue，并在 `MessageEndEvent` 后把新消息持久化成 `MessageEntry` 和 `LeafEntry`。这样既保留了 `tau_agent` 的可移植性，也给后续 resume、skills、system prompt、compaction、branching 留出了清晰位置。
