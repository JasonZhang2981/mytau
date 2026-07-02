# Phase 20.1 学习笔记：Context Accounting Refresh

对应架构文档：`dev-notes/architecture/phase-20-1-context-accounting.md`

对应源码：

- `src/tau_coding/context_window.py`
- `src/tau_coding/session.py`
- `src/tau_coding/commands.py`
- `src/tau_coding/tui/adapter.py`
- `src/tau_coding/tui/widgets.py`
- `src/tau_coding/tui/app.py`
- `tests/test_context_window.py`
- `tests/test_coding_session.py`
- `tests/test_commands.py`
- `tests/test_tui_adapter.py`
- `tests/test_tui_app.py`

## 1. 这一阶段到底在做什么

Phase 20.1 解决的问题是：

```text
Tau 怎么知道当前上下文大概用了多少 token？
这个数字什么时候刷新？
用户在哪里能看到？
TUI 为什么不能自己偷偷提前加消息？
```

前面阶段里 Tau 已经有：

- system prompt
- transcript messages
- tool definitions
- session persistence
- TUI event rendering
- compaction 基础

但 coding agent 继续运行时，必须随时关心一个现实问题：

```text
模型上下文窗口不是无限的。
```

如果上下文越来越大，最终 provider 会拒绝请求，或者效果变差。

所以 Tau 需要一个“粗略但稳定”的上下文估算。

## 2. 什么是 context

在 Tau 里，一次发给模型的上下文大致包括：

```text
system prompt
+ conversation messages
+ tool definitions
```

对应源码里的参数：

```python
estimate_context_usage(
    system=self._harness.config.system,
    messages=self._harness.messages,
    tools=tuple(self._harness.config.tools),
)
```

这三个部分加起来，就是模型下一次请求大概要看到的内容。

## 3. 什么是 token

token 可以粗略理解成：

```text
模型阅读文本时使用的小片段单位
```

不是一个字符，也不一定是一个单词。

真实 token 计算需要 tokenizer。

但 Tau 这里没有引入 provider-specific tokenizer。

原因是：

```text
tau_coding 要支持不同 provider
不能把上下文估算绑定到某一个模型 tokenizer
```

所以 Phase 20.1 用的是 deterministic rough estimate。

也就是：

```text
不追求完全精确
但每次同样输入得到同样结果
足够用于 UI 提示和自动压缩阈值判断
```

## 4. `context_window.py` 的常量

文件开头：

```python
CHARS_PER_TOKEN = 4
MESSAGE_OVERHEAD_TOKENS = 4
TOOL_OVERHEAD_TOKENS = 16
SUMMARY_MESSAGE_CHAR_LIMIT = 500
DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
DEFAULT_COMPACTION_RESERVE_TOKENS = 16_384
DEFAULT_COMPACTION_KEEP_RECENT_TOKENS = 20_000
```

这些常量决定了估算规则。

### 4.1 `CHARS_PER_TOKEN = 4`

意思是：

```text
粗略按 4 个字符约等于 1 个 token
```

例如：

```python
estimate_text_tokens("abcd") == 1
estimate_text_tokens("abcde") == 2
```

这个规则不精确，但稳定。

### 4.2 `MESSAGE_OVERHEAD_TOKENS = 4`

每条消息除了正文，还有角色、结构等额外成本。

所以估算一条 message 时，不只算文本，也加固定 overhead。

### 4.3 `TOOL_OVERHEAD_TOKENS = 16`

每个工具定义也不只是名字。

它还包括：

- name
- description
- input schema

所以工具也加固定 overhead。

### 4.4 `DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000`

默认模型上下文窗口粗略按 128k 处理。

如果 provider config 里有更具体的 `context_windows`，后续会用 provider/model 的值。

### 4.5 `DEFAULT_COMPACTION_RESERVE_TOKENS = 16_384`

自动压缩不会等到 128k 才触发。

它会保留一段安全空间。

默认阈值大概是：

```text
128000 - 16384 = 111616
```

测试里也验证了：

```python
assert auto_compaction_threshold_for_context_window(128_000) == 111_616
```

## 5. `ContextUsageEstimate`

Phase 20.1 的核心新增类型：

```python
@dataclass(frozen=True, slots=True)
class ContextUsageEstimate:
    total_tokens: int
    system_tokens: int
    message_tokens: int
    tool_tokens: int
    message_count: int
    tool_count: int
```

它不是只返回一个数字，而是返回一个结构化快照。

字段含义：

- `total_tokens`：总估算 token
- `system_tokens`：system prompt 部分
- `message_tokens`：对话消息部分
- `tool_tokens`：工具定义部分
- `message_count`：消息数量
- `tool_count`：工具数量

## 6. 为什么要结构化，而不是只返回 int

旧接口只需要：

```text
当前大概多少 tokens
```

但用户和开发者更需要知道：

```text
到底是哪部分变大了？
```

例如：

- system prompt 太长？
- conversation messages 太多？
- tool schema 太大？
- tool 数量太多？

所以 Phase 20.1 让 `/session` 可以打印 breakdown。

当前源码：

```python
Context token breakdown: system=..., messages=..., tools=...
```

## 7. `estimate_text_tokens()`

源码：

```python
def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)
```

这是文本估算的基础。

### 7.1 空字符串是 0

```python
if not text:
    return 0
```

如果没有内容，就不占 token。

### 7.2 非空字符串最少 1 个 token

```python
max(1, ...)
```

哪怕只有一个字符，也至少算 1 个 token。

### 7.3 向上取整

```python
(len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN
```

这是整数向上取整的常见写法。

如果 `CHARS_PER_TOKEN = 4`：

```text
len=4 -> (4+3)//4 = 1
len=5 -> (5+3)//4 = 2
```

## 8. `estimate_message_tokens()`

源码根据 message role 分支：

```python
match message.role:
    case "user":
        ...
    case "assistant":
        ...
    case "tool":
        ...
```

这里用了 Python 的 `match/case`。

你可以理解成更强的 `if/elif`。

### 8.1 user message

```python
case "user":
    return MESSAGE_OVERHEAD_TOKENS + estimate_text_tokens(message.content)
```

用户消息比较简单：

```text
固定消息开销 + 内容 token
```

### 8.2 assistant message

```python
case "assistant":
    tool_call_tokens = sum(
        estimate_text_tokens(call.name) + estimate_text_tokens(str(call.arguments))
        for call in message.tool_calls
    )
    return (
        MESSAGE_OVERHEAD_TOKENS + estimate_text_tokens(message.content) + tool_call_tokens
    )
```

assistant message 除了文本，还可能带 tool calls。

例如：

```python
ToolCall(name="read", arguments={"path": "README.md"})
```

这些 tool call 也会进入 provider 上下文。

所以要加上：

```text
工具名 token + 参数 token
```

### 8.3 tool result message

```python
case "tool":
    return (
        MESSAGE_OVERHEAD_TOKENS
        + estimate_text_tokens(message.name)
        + estimate_text_tokens(message.content)
    )
```

工具结果消息包含：

- 工具名
- 工具输出内容

所以两者都要算。

## 9. `estimate_tool_tokens()`

源码：

```python
def estimate_tool_tokens(tool: AgentTool) -> int:
    return (
        TOOL_OVERHEAD_TOKENS
        + estimate_text_tokens(tool.name)
        + estimate_text_tokens(tool.description)
        + estimate_text_tokens(str(tool.input_schema))
    )
```

工具定义会被发给模型，让模型知道：

```text
有哪些工具
每个工具怎么用
输入参数 schema 是什么
```

所以工具不只是名字。

尤其 `input_schema` 可能比较长。

这也是为什么工具数量和 schema 大小会影响上下文。

## 10. `estimate_context_usage()`

源码：

```python
def estimate_context_usage(
    *,
    system: str,
    messages: tuple[AgentMessage, ...],
    tools: tuple[AgentTool, ...],
) -> ContextUsageEstimate:
    system_tokens = estimate_text_tokens(system)
    message_tokens = sum(estimate_message_tokens(message) for message in messages)
    tool_tokens = sum(estimate_tool_tokens(tool) for tool in tools)
    return ContextUsageEstimate(
        total_tokens=system_tokens + message_tokens + tool_tokens,
        system_tokens=system_tokens,
        message_tokens=message_tokens,
        tool_tokens=tool_tokens,
        message_count=len(messages),
        tool_count=len(tools),
    )
```

这就是 Phase 20.1 的核心计算函数。

它做三件事：

```text
1. 估算 system prompt
2. 估算所有 messages
3. 估算所有 tools
```

然后组装成 `ContextUsageEstimate`。

## 11. `estimate_context_tokens()` 仍然保留

源码：

```python
def estimate_context_tokens(...) -> int:
    return estimate_context_usage(...).total_tokens
```

这是兼容旧代码的 shortcut。

有些地方只需要总数，不需要 breakdown。

所以旧接口保留，但内部改成复用新结构化估算。

## 12. `CodingSession.context_usage`

`src/tau_coding/session.py` 里：

```python
@property
def context_usage(self) -> ContextUsageEstimate:
    return estimate_context_usage(
        system=self._harness.config.system,
        messages=self._harness.messages,
        tools=tuple(self._harness.config.tools),
    )
```

这说明：

```text
CodingSession 不保存一个旧的 usage 数字
每次访问 context_usage 都从当前 harness 状态重新计算
```

这样有一个好处：

```text
只要 messages/tools/system 变了，context_usage 自然变
```

不需要到处手动更新缓存。

## 13. `context_token_estimate`

源码：

```python
@property
def context_token_estimate(self) -> int:
    return self.context_usage.total_tokens
```

这是兼容属性。

很多 UI 或测试只想显示一个数字。

比如 TUI compact line 里：

```python
session.context_token_estimate
```

就够了。

## 14. `context_window_tokens`

源码位置在 `CodingSession`。

它会尝试从当前 provider config 里找当前 model 的 context window。

如果找不到，就回退到：

```python
DEFAULT_CONTEXT_WINDOW_TOKENS
```

这让 Tau 至少有一个默认窗口大小，可以继续估算自动压缩阈值。

## 15. 自动压缩阈值

源码：

```python
def auto_compaction_threshold_for_context_window(context_window_tokens: int) -> int | None:
    if context_window_tokens <= 0:
        return None
    return max(1, context_window_tokens - DEFAULT_COMPACTION_RESERVE_TOKENS)
```

含义：

```text
如果上下文窗口无效，就不启用阈值
否则阈值 = 窗口大小 - 保留空间
```

例如：

```text
128000 - 16384 = 111616
```

## 16. `CodingSession.auto_compact_token_threshold`

源码：

```python
@property
def auto_compact_token_threshold(self) -> int | None:
    if not self._auto_compact_enabled:
        return None
    if self._auto_compact_token_threshold is not None:
        return self._auto_compact_token_threshold
    return auto_compaction_threshold_for_context_window(self.context_window_tokens)
```

逻辑：

```text
1. 如果禁用自动压缩，返回 None
2. 如果用户显式传了阈值，用用户传的
3. 否则根据 context window 自动计算
```

CLI 里对应参数：

```text
--auto-compact-threshold
```

## 17. `_maybe_auto_compact()`

源码：

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

这段说明 context accounting 会直接影响 compaction。

只有当：

- 自动压缩开启
- 有足够可压缩的历史
- 当前估算 token 超过阈值
- 能生成 compaction plan

才会真的压缩。

## 18. `/session` 命令显示 context 信息

架构文档里说 `/status`。

但当前源码和测试显示：

```text
/status 是未知命令
当前使用 /session
```

`src/tau_coding/commands.py` 里注册：

```python
SlashCommand(
    name="session",
    usage="/session",
    handler=_status_command,
)
```

函数名仍叫 `_status_command`，但命令名是 `/session`。

## 19. `_status_command()`

源码：

```python
context_usage = getattr(session, "context_usage", None)
lines = [
    f"Model: {session.model}",
    ...
    f"Estimated context tokens: {session.context_token_estimate}",
    f"Context window: {session.context_window_tokens}",
]
if context_usage is not None:
    lines.append(
        "Context token breakdown: "
        f"system={context_usage.system_tokens}, "
        f"messages={context_usage.message_tokens}, "
        f"tools={context_usage.tool_tokens}",
    )
```

注意这里用了：

```python
getattr(session, "context_usage", None)
```

这是为了兼容测试 fake session 或未来别的 session-like 对象。

如果对象没有 `context_usage`，也不会崩。

## 20. TUI 不再提前加用户消息

架构文档强调：

```text
The Textual app no longer pre-adds submitted user prompts to the visible transcript.
```

也就是说，TUI 不应该在用户按 Enter 后自己先把用户消息塞进界面。

它应该等待事件流。

为什么？

因为 Tau 的核心事件流已经会表达：

```text
message_start user
message_end user
```

UI 应该消费事件，而不是自己猜状态。

## 21. `TuiEventAdapter` 如何处理 user message

`src/tau_coding/tui/adapter.py`：

```python
if isinstance(event, MessageEndEvent):
    if event.message.role == "user":
        self.state.add_user_message(event.message.content)
        return
```

所以用户消息是由 `MessageEndEvent(UserMessage(...))` 渲染出来的。

这保持了架构边界：

```text
tau_agent / AgentHarness 发事件
tau_coding.tui.adapter 消费事件并更新 UI state
```

## 22. 为什么这会影响 context refresh

TUI 主流程在每个事件后刷新。

测试里用一个 fake session 模拟上下文变化：

```python
self.context_token_estimate = 10
yield AgentStartEvent()
self.context_token_estimate = 20
yield MessageEndEvent(message=UserMessage(content=text))
self.context_token_estimate = 30
yield MessageEndEvent(message=AssistantMessage(content="Using a tool."))
self.context_token_estimate = 40
yield ToolExecutionStartEvent(...)
yield ToolExecutionEndEvent(...)
self.context_token_estimate = 50
yield AgentEndEvent()
```

然后断言：

```python
observed_context == [10, 20, 30, 40, 40, 50]
```

说明 TUI 在每个事件边界都会看到最新 context 数字。

## 23. `render_compact_session_info()`

TUI 底部 compact info 里有：

```python
right.append(_context_usage(session), style=theme.completion_description)
```

`_context_usage()` 会显示：

```text
当前 token / 阈值 context
```

或：

```text
当前 token / context window context
```

例如：

```text
12k/112k context
```

这让用户知道当前上下文离压缩阈值还有多远。

## 24. `_compact_token_count()`

源码：

```python
def _compact_token_count(value: int) -> str:
    if value <= 0:
        return "0k"
    if value < 1000:
        return "<1k"
    return f"{(value + 500) // 1000}k"
```

这是显示层的小工具。

它把精确数字变成更短的 UI 文案：

```text
0      -> 0k
999    -> <1k
12034  -> 12k
```

注意它只是显示格式，不影响真实估算。

## 25. 测试如何覆盖这一阶段

### 25.1 `tests/test_context_window.py`

覆盖：

- 文本 token 估算稳定
- message token 会计算 role 和 tool call
- context token 包含 system/messages/tools
- auto compaction threshold 保留 Pi 风格 reserve
- `ContextUsageEstimate` breakdown 正确
- compaction summary prompt 格式

### 25.2 `tests/test_coding_session.py`

关键测试：

```python
test_context_usage_recalculates_after_prompt_and_compaction
```

验证：

- prompt 后 message count 增加
- token 总数变大
- `context_token_estimate` 等于 `context_usage.total_tokens`
- compaction 后 message count 减少
- token 总数变小

### 25.3 `tests/test_commands.py`

关键测试：

```python
test_session_command_includes_session_details
```

验证 `/session` 输出包括：

- model
- cwd
- tools
- skills
- context files
- estimated context tokens
- context window
- auto compact threshold
- session id

同时当前测试也明确：

```python
/status -> Unknown command
```

### 25.4 `tests/test_tui_adapter.py`

验证 user message 由 streamed event 渲染：

```python
MessageStartEvent(message_role="user")
MessageEndEvent(message=UserMessage(content="Hello Tau"))
```

最后 UI state 里出现：

```text
("user", "Hello Tau")
```

### 25.5 `tests/test_tui_app.py`

关键测试：

```python
test_tui_prompt_worker_refreshes_context_after_message_changes
```

验证 TUI 每个事件后刷新 context。

## 26. 小白必须分清的几组概念

### 26.1 token estimate 不是真实 tokenizer

Tau 当前估算方式是：

```text
字符数 / 4 + 固定 overhead
```

不是 provider 的真实 tokenizer。

它用于稳定提示和阈值判断，不用于精确计费。

### 26.2 context usage 不是 session 文件大小

`context_usage` 估算的是下一次 provider request 的上下文。

它不等于 `.jsonl` 文件大小。

session 文件可能保存完整历史，但 compaction 后 active context 可能变小。

### 26.3 `context_usage` 是结构化快照

它不仅有总数，也有 breakdown：

```text
system/messages/tools
```

这比一个 int 更适合调试。

### 26.4 `context_token_estimate` 是兼容快捷方式

如果只想显示一个数字，用：

```python
session.context_token_estimate
```

如果想知道构成，用：

```python
session.context_usage
```

### 26.5 TUI 显示应该跟事件流走

TUI 不自己提前构造 user message。

它等 `MessageEndEvent(UserMessage(...))`。

这样 UI、session、harness 都共享同一个事实来源。

## 27. 运行测试

Phase 20.1 相关测试：

```bash
uv run pytest tests/test_context_window.py tests/test_coding_session.py tests/test_commands.py tests/test_tui_adapter.py tests/test_tui_app.py
```

这组测试范围比单个文件大，因为 context accounting 会影响：

- 估算函数
- session runtime
- slash command 输出
- TUI event adapter
- TUI app refresh timing

## 28. 用一句话总结 Phase 20.1

Phase 20.1 的价值是：把“当前上下文用了多少”从一个模糊数字升级为稳定的结构化估算，并让 `CodingSession`、`/session`、TUI 侧边信息和自动 compaction 都围绕同一套 context accounting 刷新。

## 29. 我的问题与推荐回答

问题：为什么 Tau 不直接使用某个模型的真实 tokenizer 来计算 context，而是用 `len(text) / 4` 这种粗略估算？

我的推荐回答：

因为 Tau 的核心目标是 provider-neutral，不希望 context accounting 绑定到某个具体模型或 tokenizer。真实 tokenizer 会随 provider、模型和 API 格式变化，接入成本和维护成本都更高。Phase 20.1 选择稳定、简单、可测试的粗略估算：system prompt、messages、tools 都按固定规则计算，并返回 breakdown。这个数字不适合当精确计费依据，但足够用于 UI 提示、`/session` 状态说明和自动 compaction 阈值判断。
