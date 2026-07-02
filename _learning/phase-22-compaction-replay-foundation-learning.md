# Phase 22: Compaction Replay Foundation 学习笔记

这一篇讲的是 Tau 的上下文压缩基础。

如果你是 Python 小白，可以先把它理解成一句话：

```text
聊天历史文件永远不删旧内容，但真正发给模型的上下文可以用一条摘要替换旧消息。
```

也就是说：

- session 文件仍然是完整历史。
- agent 当前继续工作时，不一定把所有旧消息都塞进模型。
- 旧消息太多时，Tau 可以追加一条 `CompactionEntry` 摘要。
- 之后重放 session 时，Tau 用这条摘要替代被压缩的旧消息。

这就是这一 phase 的核心。

## 1. 这一 phase 涉及哪些文件

架构文档列出的实现文件是：

```text
src/tau_agent/session/entries.py
src/tau_agent/session/memory.py
src/tau_coding/context_window.py
src/tau_coding/session.py
src/tau_coding/commands.py
```

对应测试主要是：

```text
tests/test_session.py
tests/test_context_window.py
tests/test_commands.py
tests/test_coding_session.py
tests/test_tui_app.py
```

你可以先记住每个文件的职责：

```text
entries.py         定义 session 里可以保存哪些 entry
memory.py          把 append-only entries 重放成当前 SessionState
context_window.py  估算 token、构造 compaction summary prompt
session.py         在 CodingSession 里执行手动/自动 compaction
commands.py        让 /compact 和 /status 能触发或展示 compaction 信息
```

这里有一个很重要的架构边界：

```text
tau_agent 只知道怎么重放 session entries
tau_coding 才知道命令、模型、token 阈值、TUI、用户体验
```

这延续了 Tau 一直在守的边界：

```text
tau_agent = 可复用 agent 大脑
tau_coding = 编码场景应用层
```

## 2. 为什么需要 compaction

大模型有上下文窗口限制。

比如一个模型最多能处理 128000 tokens。如果一个 session 聊得很久，历史消息、工具结果、系统提示、技能文档、上下文文件都会占 token。

如果无限追加，迟早会出现：

```text
context length exceeded
```

或者模型响应变慢、变贵、变不稳定。

所以 Tau 需要一种机制：

```text
把旧对话浓缩成摘要，保留最近上下文，让模型继续工作。
```

但是 Tau 不能直接删除 session 文件里的旧消息。

因为 session 文件是 durable history，也就是可持久追溯的真实历史。

所以 Tau 的做法是：

```text
旧 entry 继续留在 JSONL 文件里
新增一条 CompactionEntry
重放时用 summary 替代旧 entry
```

这就是 architecture note 里说的：

```text
session file = durable history
SessionState.messages = reconstructed active context
```

## 3. append-only 是什么

append-only 的意思是：

```text
只追加，不修改，不删除旧记录
```

例如原始 session 里有：

```text
1. user: 请解释 session
2. assistant: session 是 append-only...
```

执行 compaction 后，不是把 1 和 2 删掉。

而是追加：

```text
3. compaction: 用户询问 session，助手解释了 append-only...
4. leaf: 当前叶子指向 compaction
```

文件里仍然可以看到完整历史。

只是重放给模型时，当前上下文变成：

```text
Previous conversation summary:
用户询问 session，助手解释了 append-only...
```

这个设计的好处是：

- 可审计：旧消息还在文件里。
- 可恢复：可以重新 replay session。
- 可分支：以后 session tree branching 能选择不同路径。
- 可控：active context 和 durable history 分离。

## 4. `entries.py`: 新增的 `CompactionEntry`

关键代码在 `src/tau_agent/session/entries.py`。

```python
class CompactionEntry(BaseSessionEntry):
    """A context summary that replaces older message entries during replay."""

    type: Literal["compaction"] = "compaction"
    summary: str
    replaces_entry_ids: list[str] = Field(default_factory=list)
```

逐行解释：

```python
class CompactionEntry(BaseSessionEntry):
```

定义一个类，继承 `BaseSessionEntry`。

所以它自动拥有：

- `id`
- `parent_id`
- `timestamp`

这些通用字段。

```python
type: Literal["compaction"] = "compaction"
```

这表示这个 entry 的类型固定是 `"compaction"`。

`Literal["compaction"]` 的意思是：

```text
这个字段不能随便填，只能是字符串 "compaction"
```

这对 JSONL 反序列化很重要。

因为 session 文件里有很多种 entry：

- message
- model_change
- thinking_level_change
- compaction
- branch_summary
- label
- leaf
- session_info
- custom

Pydantic 读取 JSON 时要根据 `type` 判断应该变成哪个 Python 类。

```python
summary: str
```

保存压缩后的摘要文本。

```python
replaces_entry_ids: list[str] = Field(default_factory=list)
```

保存“这条摘要替代了哪些旧 message entry”。

例如：

```python
replaces_entry_ids=["user", "assistant"]
```

意思是：

```text
重放时，把 id=user 和 id=assistant 的消息替换成这个 summary
```

## 5. `Field(default_factory=list)` 是什么

这是 Pydantic 的写法。

如果字段默认值是 list，不应该直接写：

```python
replaces_entry_ids: list[str] = []
```

因为可变对象作为默认值容易出现共享状态问题。

更安全的写法是：

```python
Field(default_factory=list)
```

意思是：

```text
每次创建 CompactionEntry 时，都调用 list() 生成一个新的空列表。
```

这是一种 Python 里很常见的安全习惯。

## 6. `SessionEntry` 联合类型也加入了 `CompactionEntry`

同一个文件里还有：

```python
type SessionEntry = Annotated[
    MessageEntry
    | ModelChangeEntry
    | ThinkingLevelChangeEntry
    | CompactionEntry
    | BranchSummaryEntry
    | LabelEntry
    | LeafEntry
    | SessionInfoEntry
    | CustomEntry,
    Field(discriminator="type"),
]
```

这段对小白来说比较吓人，但意思很简单：

```text
SessionEntry 可以是这些 entry 类型中的任意一种。
```

其中：

```python
Field(discriminator="type")
```

意思是：

```text
用 type 字段判断 JSON 应该解析成哪个具体类。
```

例如 JSONL 里有：

```json
{"type":"compaction","summary":"...","replaces_entry_ids":["a","b"]}
```

Pydantic 就知道应该把它变成 `CompactionEntry`。

这叫 discriminated union。

你可以先把它理解成：

```text
根据 type 自动分流到不同数据模型。
```

## 7. `memory.py`: compaction 真正生效的地方

`src/tau_agent/session/memory.py` 负责把 session entries 重放成当前状态。

核心类是：

```python
@dataclass(frozen=True, slots=True)
class SessionState:
    messages: tuple[AgentMessage, ...]
    model: str | None
    thinking_level: str | None
    label: str | None
    active_leaf_id: str | None
    session_info: SessionInfoEntry | None
    custom_entries: tuple[CustomEntry, ...]
    compaction_entries: tuple[CompactionEntry, ...]
    context_entry_ids: tuple[str, ...]
    entries: tuple[SessionEntry, ...]
```

`SessionState` 是“从 session 文件推导出来的当前状态”。

注意它不是直接等于文件。

文件是 append-only entries。

`SessionState` 是 replay 之后得到的：

- 当前发给模型的 messages
- 当前 model
- 当前 thinking level
- 当前 label
- 当前 active leaf
- 当前上下文 entry ids

## 8. `@dataclass(frozen=True, slots=True)` 是什么

`dataclass` 是 Python 标准库里的一个装饰器。

它可以根据类字段自动生成：

- `__init__`
- `__repr__`
- `__eq__`

例如：

```python
@dataclass
class Point:
    x: int
    y: int
```

就可以直接：

```python
p = Point(1, 2)
```

`frozen=True` 表示对象创建后尽量不可修改。

例如：

```python
state.model = "new-model"
```

会报错。

这适合 session replay 结果，因为它应该是一个稳定快照。

`slots=True` 是一种内存优化，也能减少随便添加新属性的风险。

你可以先记成：

```text
frozen=True 让对象更像不可变记录
slots=True 让对象更轻、更严格
```

## 9. `from_entries()` 是 replay 的入口

核心方法：

```python
@classmethod
def from_entries(
    cls,
    entries: list[SessionEntry],
    *,
    leaf_id: str | None | object = _UNSET_LEAF_ID,
) -> SessionState:
```

它接收一组 entries，然后返回 `SessionState`。

这里的 `@classmethod` 表示：

```text
这个方法属于类本身，而不是某个实例。
```

所以可以这样调用：

```python
SessionState.from_entries(entries)
```

不用先：

```python
state = SessionState(...)
```

## 10. `leaf_id` 用来支持 session tree

方法里有这段：

```python
replay_all = leaf_id is _UNSET_LEAF_ID
resolved_leaf_id = None if replay_all else cast(str | None, leaf_id)
replay_entries = (
    entries
    if replay_all
    else path_to_entry(entries, resolved_leaf_id)
    if resolved_leaf_id is not None
    else []
)
```

先不用被三元表达式绕晕。

它的意思是：

如果没有传 `leaf_id`：

```text
按 storage 顺序线性重放所有 entries。
```

如果传了 `leaf_id`：

```text
只重放 session tree 中从 root 到这个 leaf 的路径。
```

这样以后分支历史里，compaction 只影响当前分支路径，不会错误压缩别的分支。

## 11. `match entry.type`: 根据 entry 类型处理

`from_entries()` 里最核心的是：

```python
for entry in replay_entries:
    match entry.type:
        case "message":
            message_rows.append((entry.id, entry.message))
        case "model_change":
            model = entry.model
        case "thinking_level_change":
            thinking_level = entry.thinking_level
        case "label":
            label = entry.label
        case "leaf":
            active_leaf_id = entry.entry_id
        case "session_info":
            session_info = entry
        case "custom":
            custom_entries.append(entry)
        case "compaction":
            compaction_entries.append(entry)
            message_rows = _apply_compaction(message_rows, entry)
        case "branch_summary":
            message_rows.append(
                (entry.id, UserMessage(content=_format_branch_summary(entry)))
            )
```

这是 Python 的结构化模式匹配，语法是：

```python
match 值:
    case 某种情况:
        ...
```

你可以把它当成其他语言里的 `switch`。

这里最关键的是：

```python
case "compaction":
    compaction_entries.append(entry)
    message_rows = _apply_compaction(message_rows, entry)
```

当 replay 遇到 compaction entry 时：

1. 把这条 compaction 记录到 `compaction_entries`。
2. 调用 `_apply_compaction()` 改写当前 active message rows。

## 12. 为什么用 `message_rows`

代码不是只存 message，而是存：

```python
message_rows: list[tuple[str, AgentMessage]] = []
```

每一项是：

```python
(entry_id, message)
```

这是因为 compaction 不是按 message 内容替换，而是按 entry id 替换。

例如：

```text
id=user       -> UserMessage(...)
id=assistant  -> AssistantMessage(...)
id=recent     -> UserMessage(...)
```

`CompactionEntry.replaces_entry_ids` 可能是：

```python
["user", "assistant"]
```

所以必须保留 entry id，才能知道哪些 message 被 summary 替代。

最后返回 `SessionState` 时才把 message 拿出来：

```python
messages=tuple(message for _entry_id, message in message_rows)
context_entry_ids=tuple(entry_id for entry_id, _message in message_rows)
```

## 13. `_apply_compaction()` 如何替换旧消息

核心函数：

```python
def _apply_compaction(
    message_rows: list[tuple[str, AgentMessage]],
    entry: CompactionEntry,
) -> list[tuple[str, AgentMessage]]:
    replaced_ids = set(entry.replaces_entry_ids)
    retained: list[tuple[str, AgentMessage]] = []
    inserted_summary = False
    for entry_id, message in message_rows:
        if entry_id not in replaced_ids:
            retained.append((entry_id, message))
            continue
        if not inserted_summary:
            retained.append(
                (entry.id, UserMessage(content=_format_compaction_summary(entry.summary)))
            )
            inserted_summary = True

    if not inserted_summary:
        retained.append((entry.id, UserMessage(content=_format_compaction_summary(entry.summary))))
    return retained
```

我们一步一步拆。

```python
replaced_ids = set(entry.replaces_entry_ids)
```

把 list 变成 set。

为什么？

因为判断：

```python
entry_id in replaced_ids
```

set 通常比 list 更快。

```python
retained = []
```

这个列表保存压缩后的新 message rows。

```python
inserted_summary = False
```

用一个布尔值记录摘要是否已经插入过。

为什么需要？

假设旧消息有两条都被替换：

```text
user
assistant
```

摘要只能插入一次，不能每遇到一个被替换消息都插入一次。

## 14. `_apply_compaction()` 的实际例子

压缩前：

```text
[
  ("user", UserMessage("Explain sessions.")),
  ("assistant", AssistantMessage("Sessions are append-only.")),
  ("followup", UserMessage("Continue."))
]
```

compaction：

```python
CompactionEntry(
    id="compact",
    summary="The user asked about sessions...",
    replaces_entry_ids=["user", "assistant"],
)
```

压缩后：

```text
[
  ("compact", UserMessage("Previous conversation summary:\nThe user asked about sessions...")),
  ("followup", UserMessage("Continue."))
]
```

注意：summary 在 active context 里被包装成 `UserMessage`。

这不是说真实用户说过这句话。

而是把摘要作为“给模型看的上下文提示”放到对话里。

## 15. summary 的稳定格式

函数：

```python
def _format_compaction_summary(summary: str) -> str:
    return f"Previous conversation summary:\n{summary}"
```

所以 compaction summary 在上下文里的格式固定是：

```text
Previous conversation summary:
<summary>
```

稳定格式很重要。

因为后面的 `context_window.py` 还能识别这个前缀，然后判断：

```text
这是不是上一轮 compaction summary？
```

## 16. `context_window.py`: token 估算和摘要 prompt

`src/tau_coding/context_window.py` 是 Tau coding 层的上下文窗口工具。

它做几件事：

1. 粗略估算文本 token 数。
2. 粗略估算 message token 数。
3. 粗略估算 tool schema token 数。
4. 计算整个 provider context 的 token。
5. 生成 compaction summary prompt。
6. 把 messages 序列化成适合总结模型读取的文本。

它在 `tau_coding`，不是 `tau_agent`。

因为 token 阈值、具体 prompt、summary UX 都属于应用层策略。

`tau_agent` 不应该关心这些。

## 17. token 粗略估算

文件开头：

```python
CHARS_PER_TOKEN = 4
MESSAGE_OVERHEAD_TOKENS = 4
TOOL_OVERHEAD_TOKENS = 16
```

这里没有使用具体 provider tokenizer。

它用一个简单规则：

```text
大约 4 个字符算 1 个 token
```

为什么不直接用 OpenAI 或 Anthropic 的 tokenizer？

因为 Tau 的 core 不应该被某个 provider 绑定。

而且这里的目标不是精确计费，而是有一个稳定、可测试、可解释的阈值。

## 18. `estimate_text_tokens()`

```python
def estimate_text_tokens(text: str) -> int:
    """Return a deterministic rough token estimate for text."""
    if not text:
        return 0
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)
```

如果文本为空，返回 0。

否则根据字符数估算 token。

这段：

```python
(len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN
```

是在做“向上取整除法”。

比如 `CHARS_PER_TOKEN = 4`：

```text
1 个字符  -> 1 token
4 个字符  -> 1 token
5 个字符  -> 2 tokens
8 个字符  -> 2 tokens
9 个字符  -> 3 tokens
```

`//` 是 Python 的整除。

## 19. `estimate_message_tokens()`

```python
def estimate_message_tokens(message: AgentMessage) -> int:
    match message.role:
        case "user":
            return MESSAGE_OVERHEAD_TOKENS + estimate_text_tokens(message.content)
        case "assistant":
            tool_call_tokens = sum(
                estimate_text_tokens(call.name) + estimate_text_tokens(str(call.arguments))
                for call in message.tool_calls
            )
            return (
                MESSAGE_OVERHEAD_TOKENS + estimate_text_tokens(message.content) + tool_call_tokens
            )
        case "tool":
            return (
                MESSAGE_OVERHEAD_TOKENS
                + estimate_text_tokens(message.name)
                + estimate_text_tokens(message.content)
            )
```

不同角色的 message 估算方式不同：

- user：内容 token + message 固定开销。
- assistant：内容 token + tool call token + message 固定开销。
- tool：工具名 token + 工具结果 token + message 固定开销。

这里的 `sum(...) for call in message.tool_calls` 是生成器表达式。

它会逐个 tool call 计算 token，然后求和。

## 20. `ContextUsageEstimate`

```python
@dataclass(frozen=True, slots=True)
class ContextUsageEstimate:
    """Deterministic context-size accounting for one provider request."""

    total_tokens: int
    system_tokens: int
    message_tokens: int
    tool_tokens: int
    message_count: int
    tool_count: int
```

这个 dataclass 用来返回结构化估算结果。

不是只返回一个数字，而是告诉你：

- 总 token 多少
- system prompt 占多少
- messages 占多少
- tools 占多少
- message 有几条
- tool 有几个

这样 `/status` 可以展示更清楚的信息。

## 21. 自动 compaction 阈值

```python
DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
DEFAULT_COMPACTION_RESERVE_TOKENS = 16_384
```

`DEFAULT_CONTEXT_WINDOW_TOKENS` 是未知模型的默认上下文窗口。

`DEFAULT_COMPACTION_RESERVE_TOKENS` 是保留空间。

函数：

```python
def auto_compaction_threshold_for_context_window(context_window_tokens: int) -> int | None:
    """Return Pi-style automatic compaction threshold for a model context window."""
    if context_window_tokens <= 0:
        return None
    return max(1, context_window_tokens - DEFAULT_COMPACTION_RESERVE_TOKENS)
```

例如模型上下文窗口是 128000：

```text
128000 - 16384 = 111616
```

这表示：

```text
估算上下文超过 111616 tokens 时，可以触发自动压缩。
```

保留 16384 tokens 是为了给新回复、工具结果、误差留空间。

## 22. compaction summary prompt

`context_window.py` 定义了：

```python
SUMMARIZATION_SYSTEM_PROMPT
SUMMARIZATION_PROMPT
UPDATE_SUMMARIZATION_PROMPT
TURN_PREFIX_SUMMARIZATION_PROMPT
```

其中 Phase 22 主要用：

- `SUMMARIZATION_SYSTEM_PROMPT`
- `SUMMARIZATION_PROMPT`
- `UPDATE_SUMMARIZATION_PROMPT`

`SUMMARIZATION_SYSTEM_PROMPT` 告诉模型：

```text
你是上下文总结助手，只输出结构化 summary，不要继续对话。
```

`SUMMARIZATION_PROMPT` 要求模型输出固定结构：

```text
## Goal
## Constraints & Preferences
## Progress
## Key Decisions
## Next Steps
## Critical Context
```

这很重要。

因为 compaction summary 不是普通闲聊摘要。

它是给下一个 LLM continuation 使用的“工作交接单”。

## 23. `build_compaction_summary_prompt()`

```python
def build_compaction_summary_prompt(
    messages: tuple[AgentMessage, ...],
    *,
    custom_instructions: str | None = None,
) -> str:
```

这个函数根据当前 messages 构造总结 prompt。

其中：

```python
previous_summary, new_messages = _split_previous_compaction_summary(messages)
```

先检查第一条消息是不是之前的 compaction summary。

如果是，就说明：

```text
现在不是第一次总结，而是在旧 summary 基础上继续更新。
```

于是使用 `UPDATE_SUMMARIZATION_PROMPT`。

如果不是，就使用 `SUMMARIZATION_PROMPT`。

这就是 Pi-style summary 的一个关键点：

```text
旧 summary 不丢，新的消息合并进去。
```

## 24. 自定义 instructions

`/compact` 支持：

```text
/compact Focus on session persistence.
```

这些额外说明会进入：

```python
if instructions:
    base_prompt = f"{base_prompt}\n\nAdditional focus: {instructions}"
```

也就是说用户可以告诉总结模型：

```text
这次总结重点关注什么。
```

例如：

```text
/compact 重点保留文件路径和测试命令
```

## 25. `serialize_messages_for_compaction()`

```python
def serialize_messages_for_compaction(messages: tuple[AgentMessage, ...]) -> str:
```

这个函数把 provider-neutral messages 转成文本。

它会按角色生成类似：

```text
<message index=1 role=user>
...
</message>
```

assistant 如果有 tool calls，会加：

```text
<tool-calls>
- bash: {"command": "..."}
</tool-calls>
```

tool result 会加：

```text
<message index=3 role=tool name=bash ok=True>
...
</message>
```

这样总结模型不仅能看到用户和助手文字，还能看到工具调用与结果。

## 26. `commands.py`: `/compact` 和 `/status`

`src/tau_coding/commands.py` 里注册了：

```python
SlashCommand(
    name="compact",
    usage="/compact [instructions]",
    description="Summarize and compact active context.",
    handler=_compact_command,
)
```

对应 handler：

```python
def _compact_command(context: CommandContext) -> CommandResult:
    return CommandResult(
        handled=True,
        compact_summary=context.args.strip(),
    )
```

注意这个函数本身不执行 compaction。

它只是解析命令并返回：

```python
CommandResult(compact_summary="...")
```

真正执行是在 TUI 或 session 上层逻辑里看到 `compact_summary` 后调用：

```python
session.compact(...)
```

这是一个常见设计：

```text
command parser 只负责理解命令
业务对象负责执行行为
UI 层负责调度
```

## 27. `/status` 展示上下文估算

`_status_command()` 里有：

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

所以用户执行 `/status` 时可以看到：

```text
Estimated context tokens: <count>
Context window: <count>
```

如果有 `context_usage`，还会展示 breakdown：

```text
Context token breakdown: system=..., messages=..., tools=...
```

如果自动 compaction 启用，还会展示：

```text
Auto compact threshold: ...
```

这让用户知道当前上下文离阈值还有多远。

## 28. `session.py`: `CodingSession` 里的 compaction plan

`src/tau_coding/session.py` 里有：

```python
@dataclass(frozen=True, slots=True)
class CompactionPlan:
    """Prepared active-context entries for a compaction run."""

    replace_entry_ids: tuple[str, ...]
    messages_to_summarize: tuple[AgentMessage, ...]
```

这个对象是“压缩计划”。

它说明：

- 哪些 entry id 要被 summary 替换。
- 哪些 message 要拿去给模型总结。

为什么需要 plan？

因为真正 compaction 之前要先算清楚：

```text
我要总结哪些消息？
我要替换哪些 entry？
```

这比在多个函数里临时拼逻辑更清楚。

## 29. `context_token_estimate`

`CodingSession` 里：

```python
@property
def context_token_estimate(self) -> int:
    """Return a rough token estimate for the active provider context."""
    return self.context_usage.total_tokens
```

这是一个 property。

调用时像属性：

```python
session.context_token_estimate
```

但背后会执行函数。

`context_usage` 又会调用：

```python
estimate_context_usage(
    system=self._harness.config.system,
    messages=self._harness.messages,
    tools=tuple(self._harness.config.tools),
)
```

也就是说，Tau 估算的是：

```text
system prompt + 当前 active messages + tools
```

而不是整个 session 文件。

这很合理。

因为 provider 请求真正发送的是 active context，不是 JSONL 文件里的全部历史。

## 30. `auto_compact_token_threshold`

```python
@property
def auto_compact_token_threshold(self) -> int | None:
    """Return the effective automatic compaction threshold, if any."""
    if not self._auto_compact_enabled:
        return None
    if self._auto_compact_token_threshold is not None:
        return self._auto_compact_token_threshold
    return auto_compaction_threshold_for_context_window(self.context_window_tokens)
```

逻辑是：

1. 如果关闭自动 compaction，返回 `None`。
2. 如果用户显式传了阈值，就用用户传的。
3. 否则根据模型 context window 自动计算。

命令行里可以用：

```bash
tau --auto-compact-threshold 100000
```

这会覆盖默认阈值。

## 31. 手动 compaction: `compact()`

核心方法：

```python
async def compact(self, instructions: str | None = None) -> str:
    """Generate a manual compaction summary and rebuild active context."""
    plan = self._manual_compaction_plan()
    summary = await self._generate_compaction_summary(
        plan.messages_to_summarize,
        custom_instructions=instructions,
    )
    compaction = await self._append_compaction(
        summary,
        replace_entry_ids=plan.replace_entry_ids,
    )
    return f"Compacted {len(compaction.replaces_entry_ids)} context entries."
```

一步一步：

1. `_manual_compaction_plan()` 找出当前 active context 中所有 message。
2. `_generate_compaction_summary()` 调模型生成 summary。
3. `_append_compaction()` 把 `CompactionEntry` 写入 session。
4. 返回一条给用户看的消息。

这里是 `async def`。

说明它是异步函数。

调用时要：

```python
await session.compact(...)
```

因为它内部需要等待 provider 流式返回 summary，还要写 storage。

## 32. `await` 是什么

`await` 用在异步函数里。

可以把它理解成：

```text
这里要等一个异步操作完成，但不会阻塞整个事件循环。
```

例如模型流式响应、文件异步写入、网络请求都适合用 async。

Tau 的 agent loop 本身就是异步的，所以 compaction 也保持异步边界。

## 33. `_generate_compaction_summary()` 如何调用模型

核心代码：

```python
async for event in self._harness.config.provider.stream_response(
    model=self.model,
    system=SUMMARIZATION_SYSTEM_PROMPT,
    messages=summary_messages,
    tools=[],
):
    if isinstance(event, ProviderTextDeltaEvent):
        text_parts.append(event.delta)
    elif isinstance(event, ProviderResponseEndEvent):
        final_text = event.message.content
    elif isinstance(event, ProviderErrorEvent):
        details = f": {event.data}" if event.data is not None else ""
        raise RuntimeError(f"Compaction summarization failed: {event.message}{details}")
```

这里用了 `async for`。

因为 provider 是流式输出事件：

- `ProviderTextDeltaEvent`: 一小段文本
- `ProviderResponseEndEvent`: 完整结束消息
- `ProviderErrorEvent`: provider 出错

`tools=[]` 表示总结时不允许调用工具。

这是合理的。

总结上下文只需要读已有 messages，不应该执行代码或访问文件。

## 34. summary 为空时会报错

```python
summary = (final_text if final_text is not None else "".join(text_parts)).strip()
if not summary:
    raise RuntimeError("Compaction summarization returned an empty summary")
return summary
```

如果模型没有返回任何有效文本，就抛异常。

这比默默写入空 summary 更安全。

因为空 summary 会导致后续上下文丢失。

## 35. `_append_compaction()` 写入 session 并刷新 harness

```python
async def _append_compaction(
    self,
    summary: str,
    *,
    replace_entry_ids: tuple[str, ...],
) -> CompactionEntry:
```

核心步骤：

```python
compaction = CompactionEntry(
    parent_id=self._last_parent_id,
    summary=summary,
    replaces_entry_ids=list(replace_entry_ids),
)
await self._append_session_entry(compaction)
leaf = LeafEntry(parent_id=compaction.id, entry_id=compaction.id)
await self._append_session_entry(leaf)
self._last_parent_id = compaction.id

await self._refresh_persisted_state(leaf_id=compaction.id)
self._harness.replace_messages(self._state.messages)
return compaction
```

这几步非常关键：

1. 创建 `CompactionEntry`。
2. 追加到 session storage。
3. 追加一个 `LeafEntry`，让当前 branch 指向 compaction。
4. 更新 `_last_parent_id`。
5. 重新读取 session 并 replay。
6. 用 replay 后的 messages 替换 harness 当前 messages。

最后一步：

```python
self._harness.replace_messages(self._state.messages)
```

很重要。

它让 agent 后续继续对话时，使用压缩后的 active context。

否则文件写了 compaction，但内存里的 harness 还拿着旧 messages，就没有实际效果。

## 36. 自动 compaction: 什么时候触发

`prompt()` 里有：

```python
await self._try_auto_compact(context=context, phase="auto_compact_before_prompt")
```

也就是用户新 prompt 之前，先看看要不要压缩。

模型回复结束后还有：

```python
await self._try_auto_compact(context=context, phase="auto_compact_after_prompt")
```

`continue_()` 后也有：

```python
await self._try_auto_compact(context=context, phase="auto_compact_after_continue")
```

所以自动 compaction 可能发生在：

- 新 prompt 前
- prompt 完成后
- continue 完成后

## 37. `_maybe_auto_compact()`

```python
async def _maybe_auto_compact(self) -> bool:
    threshold = self.auto_compact_token_threshold
    if threshold is None or threshold <= 0:
        return False
    if len(self._state.context_entry_ids) < 2:
        return False
    if self.context_token_estimate <= threshold:
        return False
    plan = self._recent_preserving_compaction_plan()
    if plan is None:
        return False
    summary = await self._generate_compaction_summary(plan.messages_to_summarize)
    await self._append_compaction(summary, replace_entry_ids=plan.replace_entry_ids)
    return True
```

判断顺序：

1. 没有阈值，不压缩。
2. active context 消息太少，不压缩。
3. token 估算没超过阈值，不压缩。
4. 生成 recent-preserving plan。
5. 调模型生成 summary。
6. 写入 compaction。

`recent-preserving` 的意思是：

```text
尽量保留最近一段上下文，只压缩更早的部分。
```

## 38. 为什么自动 compaction 只压缩旧部分

手动 `/compact` 会压缩当前所有 active messages。

自动 compaction 不一样。

它使用：

```python
_recent_preserving_compaction_plan()
```

这会保留最近约：

```python
DEFAULT_COMPACTION_KEEP_RECENT_TOKENS = 20_000
```

为什么？

因为最新上下文通常最重要。

例如你正在改一个 bug，最近几条消息包含：

- 当前错误
- 最新测试结果
- 刚修改的文件
- 用户最新要求

这些不应该过早被总结掉。

自动 compaction 更像：

```text
旧历史变 summary，新近上下文保持原样。
```

## 39. overflow-triggered retry

`prompt()` 里还有一段处理上下文溢出：

```python
if isinstance(event, ErrorEvent) and not event.recoverable:
    ...
    if _is_context_overflow_error(event):
        overflow_event = event
```

如果 provider 返回不可恢复错误，并且看起来像 context overflow，Tau 会尝试：

```python
compacted = await self._try_overflow_compact(context=context)
if compacted:
    async for retry_event in self._harness.continue_():
        ...
```

意思是：

```text
如果刚才是上下文太大导致失败，就先压缩，再 retry 一次 continue。
```

这是一种自动兜底。

但只尝试一个 compact-and-retry cycle。

这样可以避免无限重试。

## 40. `_try_auto_compact()` 为什么吞掉异常

```python
async def _try_auto_compact(...):
    try:
        return await self._maybe_auto_compact()
    except Exception as exc:
        self._last_diagnostic_log_path = self._diagnostic_logger.log_exception(...)
        return False
```

如果自动 compaction 出错，Tau 不应该直接丢掉用户这轮对话。

所以它会：

1. 记录 diagnostic log。
2. 返回 `False`。
3. 继续原本流程。

这是应用层鲁棒性设计。

手动 compaction 出错可以让用户看到错误。

自动 compaction 出错则尽量不要破坏主流程。

## 41. `tests/test_session.py`: replay 行为怎么测

测试：

```python
def test_compaction_entry_round_trips_jsonl() -> None:
    entry = CompactionEntry(
        id="compact",
        summary="The user asked about session replay.",
        replaces_entry_ids=["user", "assistant"],
    )

    line = entry_to_json_line(entry)
    parsed = entry_from_json_line(line)

    assert parsed == entry
```

这个测试证明：

```text
CompactionEntry 可以写成 JSONL，也可以读回来，而且不丢字段。
```

`round trip` 就是：

```text
对象 -> JSON -> 对象
```

前后应该一致。

## 42. replay compaction 的测试

测试：

```python
def test_session_state_replays_compaction_as_context_summary() -> None:
```

它构造：

```text
user -> assistant -> compaction -> followup
```

然后断言 replay 后的 messages 是：

```python
(
    UserMessage(
        content=(
            "Previous conversation summary:\n"
            "The user asked about sessions. The assistant explained append-only replay."
        )
    ),
    UserMessage(content="Continue."),
)
```

这证明旧的 user/assistant 被 summary 替代，而 followup 被保留。

## 43. `tests/test_coding_session.py`: manual compaction 怎么测

测试：

```python
async def test_session_compact_persists_summary_and_rebuilds_context(...)
```

它用 fake provider 模拟三次模型调用：

1. 第一次回答用户。
2. 第二次生成 session summary。
3. 第三次继续对话。

测试断言：

```python
assert compactions[0].summary == "Generated session summary"
assert compactions[0].replaces_entry_ids == message_entries_before
assert leaves[-1].entry_id == compactions[0].id
```

这证明：

- summary 被写进 `CompactionEntry`。
- 被替换的 entry ids 是 compaction 前的 message ids。
- 当前 leaf 指向 compaction。

还断言：

```python
assert provider.calls[2][2] == [
    UserMessage(content=("Previous conversation summary:\nGenerated session summary")),
    UserMessage(content="Continue."),
]
```

这非常关键。

它证明 compaction 后再继续 prompt 时，provider 收到的上下文已经变成：

```text
summary + 新用户消息
```

而不是旧的完整消息列表。

## 44. fake provider 是什么

测试里经常用 `FakeProvider`。

它不真的请求 OpenAI 或 Anthropic。

它按预设事件返回结果。

好处是：

- 测试稳定。
- 不需要网络。
- 不消耗 API 费用。
- 可以精确验证 provider calls。

对 agent loop 这种异步流式系统，fake provider 非常重要。

## 45. Phase 22 的关键 Python 包和模块

这一 phase 主要用到这些：

### 45.1 `dataclasses`

来自 Python 标准库。

用途：

```text
快速定义只保存数据的类。
```

常见写法：

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class CompactionPlan:
    replace_entry_ids: tuple[str, ...]
    messages_to_summarize: tuple[AgentMessage, ...]
```

### 45.2 `typing`

来自 Python 标准库。

这一 phase 里常见：

- `Literal`
- `Annotated`
- `Final`
- `cast`
- `Protocol`

`Literal["compaction"]` 表示字段只能是固定值。

`Annotated[..., Field(...)]` 给类型加额外元信息。

`Final` 表示常量倾向于不被修改。

`cast()` 是给类型检查器看的，不会在运行时真的转换对象。

### 45.3 `pydantic`

第三方数据建模库。

Tau 用它定义 session entry，因为 session entry 要：

- 能校验字段
- 能序列化成 JSON
- 能从 JSON 解析回来
- 能根据 `type` 字段分辨具体 entry 类

常见写法：

```python
from pydantic import BaseModel, Field
```

### 45.4 `async` / `await`

这是 Python 异步编程语法。

Tau 的 provider streaming 是异步的，所以 compaction summary 生成也用异步。

常见写法：

```python
summary = await self._generate_compaction_summary(...)
```

以及：

```python
async for event in provider.stream_response(...):
    ...
```

## 46. 小白容易混淆的概念

### 46.1 compaction 不是删除历史

旧消息仍然留在 JSONL 文件里。

compaction 只是影响 active context replay。

### 46.2 summary message 不是真实用户消息

Replay 后 summary 被包装成 `UserMessage`。

这是为了把摘要作为上下文喂给模型。

它不代表用户真的发送过这句话。

### 46.3 token estimate 不是精确 tokenizer

Tau 使用字符估算。

目标是稳定、简单、可测试。

不是精确计算每家 provider 的真实 token。

### 46.4 manual compaction 和 automatic compaction 不一样

手动 `/compact`：

```text
压缩当前 active context 的所有 message。
```

自动 compaction：

```text
保留最近上下文，只压缩较旧部分。
```

### 46.5 session file 和 harness messages 不一样

session file：

```text
完整 append-only 历史。
```

harness messages：

```text
当前实际发给 provider 的 active context。
```

## 47. 这一 phase 的架构价值

Phase 22 很重要，因为它把 Tau 从“只会一直追加对话”推进到：

```text
可以长期运行、可以控制上下文、可以保留 durable history。
```

对 coding agent 来说，这非常关键。

因为真实开发任务可能持续很久。

没有 compaction，agent 很容易因为上下文太长而失效。

有了 compaction，Tau 后面才能继续做：

- 更强的 session resume
- branch summary
- 长任务 continuation
- TUI session tree 操作
- 更接近 Pi 的长期会话体验

## 48. 如何运行测试

Phase 22 对应 focused tests：

```bash
uv run pytest tests/test_session.py tests/test_context_window.py tests/test_commands.py tests/test_coding_session.py tests/test_tui_app.py
```

本次我实际运行了：

```bash
uv run pytest tests/test_agent_harness.py tests/test_agent_loop.py tests/test_coding_session.py tests/test_context_window.py tests/test_provider_config.py tests/test_rendering.py tests/test_session_export.py tests/test_skills.py tests/test_tau_ai.py tests/test_tui_adapter.py tests/test_tui_app.py tests/test_tui_config.py
```

结果：

```text
378 passed
```

这个结果来自上一份 pre-extension hardening 的 focused gate。Phase 22 后我还会跑 Phase 22 自己的 focused tests。

## 49. 用一句话总结

Phase 22 的核心价值是：Tau 通过 `CompactionEntry` 在 append-only session 文件中追加摘要记录，并在 `SessionState.from_entries()` replay 时用摘要替换旧 active messages，从而既保留完整历史，又让 provider 上下文可压缩、可继续、可测试。

## 50. 我的问题与推荐回答

问题：为什么 Tau 不直接删除旧 message entry，而是追加 `CompactionEntry` 并在 replay 时替换 active context？

我的推荐回答：

因为 Tau 要同时满足两个目标：session 文件必须保留完整、可审计、可重放的 durable history；但 provider 请求又不能无限携带所有旧上下文。追加 `CompactionEntry` 可以让 JSONL 历史保持 append-only，不破坏旧记录，同时让 `SessionState.from_entries()` 在构造 active context 时用 `"Previous conversation summary:\n..."` 替代被压缩的旧消息。这样既节省上下文窗口，又保留原始会话历史和未来 session tree 分支能力。
