# Phase 3 学习笔记：Pure Agent Loop

对应架构文档：`dev-notes/architecture/phase-3-agent-loop.md`

对应源码：

- `src/tau_agent/loop.py`
- `tests/test_agent_loop.py`

前置阶段：

- Phase 1：定义 `AgentMessage`、`AgentTool`、`AgentToolResult`、`AgentEvent`
- Phase 2：定义 `ModelProvider`、`ProviderEvent`、`FakeProvider`

## 1. 这一阶段到底在做什么

Phase 3 是 Tau 第一次出现真正的 agent engine。

它把前两阶段串起来：

```text
messages transcript
        ↓
run_agent_loop()
        ↓
ModelProvider.stream_response()
        ↓
ProviderEvent
        ↓
AgentEvent
        ↓
必要时执行 AgentTool
        ↓
追加 AssistantMessage / ToolResultMessage 到 transcript
```

一句话说：Phase 3 的 `run_agent_loop()` 负责协调模型流、对话记录、工具执行和事件输出。

它仍然是纯 agent 层，不知道 CLI、Rich、Textual、文件路径、slash command、session 存储这些应用层细节。

## 2. 为什么叫 Pure Agent Loop

`src/tau_agent/loop.py` 里的循环叫 pure，不是说它没有副作用。

它其实会修改传入的 `messages` 列表。

这里的 pure 更接近架构边界上的“纯”：

- 不依赖具体 provider SDK
- 不依赖 OpenAI 或 Anthropic 原始数据结构
- 不依赖 CLI
- 不依赖 TUI
- 不知道 coding 工具内部怎么读写文件
- 不知道 session 怎么保存

它只认识 Tau 自己的通用类型：

- `AgentMessage`
- `AssistantMessage`
- `ToolResultMessage`
- `AgentTool`
- `ToolCall`
- `AgentEvent`
- `ProviderEvent`

## 3. `run_agent_loop()` 的函数签名

源码：

```python
async def run_agent_loop(
    *,
    provider: ModelProvider,
    model: str,
    system: str,
    messages: list[AgentMessage],
    tools: list[AgentTool],
    max_turns: int | None = None,
    signal: CancellationToken | None = None,
    get_steering_messages: Callable[[], Sequence[AgentMessage]] | None = None,
    get_follow_up_messages: Callable[[], Sequence[AgentMessage]] | None = None,
    get_queue_update: Callable[[], QueueUpdateEvent] | None = None,
) -> AsyncIterator[AgentEvent]:
```

这个函数是 Phase 3 的主入口。

调用方式大概是：

```python
async for event in run_agent_loop(
    provider=provider,
    model="fake",
    system="You are Tau.",
    messages=messages,
    tools=tools,
):
    ...
```

### 3.1 为什么是 `async def`

因为它要等待 provider 的流式响应，也要等待工具执行。

provider 和工具都可能涉及网络、文件、子进程等耗时操作，所以用异步更合适。

### 3.2 为什么返回 `AsyncIterator[AgentEvent]`

它不是一次性返回最终结果，而是边运行边产出事件。

比如普通文本回复会产出：

```text
agent_start
turn_start
message_start
message_delta
message_delta
message_end
turn_end
agent_end
```

UI 或 CLI 可以一边收到事件，一边显示给用户。

### 3.3 为什么参数前面有 `*`

`*` 后面的参数都必须用关键字传。

这样调用时很清楚：

```python
run_agent_loop(
    provider=provider,
    model="fake",
    system="You are Tau.",
    messages=messages,
    tools=[],
)
```

不会因为位置参数顺序写错而传乱。

## 4. `messages` 为什么是可变列表

源码注释说：

```python
The passed `messages` list is the transcript owned by the caller.
The loop appends assistant messages and tool result messages to it.
```

也就是说：

- `messages` 由调用者拥有
- loop 只负责往里面追加新消息
- loop 不负责持久化
- loop 不负责决定消息从哪里来

例如测试里：

```python
messages = [UserMessage(content="Say hello")]
```

运行后变成：

```python
[
    UserMessage(content="Say hello"),
    AssistantMessage(content="Hello"),
]
```

这使得后面的 `AgentHarness` 可以拥有 transcript，把它传给 loop，等 loop 追加完再保存。

## 5. 导入部分怎么看

`loop.py` 的导入可以分三组理解。

### 5.1 Python 标准库类型

```python
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
```

- `AsyncIterator`：异步迭代器，表示可以 `async for`
- `Callable`：可调用对象，比如函数
- `Mapping`：像字典一样可读取 key-value 的对象
- `Sequence`：有顺序的一组对象，比如 list 或 tuple

这里的 queue 回调：

```python
get_steering_messages: Callable[[], Sequence[AgentMessage]] | None
```

意思是：

```text
这是一个不接收参数的函数，调用后返回一组 AgentMessage；也可能没有这个函数。
```

### 5.2 `tau_agent` 类型

```python
from tau_agent.events import AgentStartEvent, MessageDeltaEvent, ...
from tau_agent.messages import AgentMessage, AssistantMessage, ToolResultMessage
from tau_agent.tools import AgentTool, AgentToolResult, ToolCall
```

这些是 loop 对外使用的 agent 层语言。

### 5.3 `tau_ai` 类型

```python
from tau_ai.events import ProviderErrorEvent, ProviderResponseEndEvent, ...
from tau_ai.provider import CancellationToken, ModelProvider
```

这些是 provider 层语言。

Phase 3 的核心就是把 provider 层语言转换成 agent 层语言。

## 6. 主流程第一步：先发 `AgentStartEvent`

源码：

```python
yield AgentStartEvent()
```

`yield` 在 async generator 里表示“产出一个事件给外部消费”。

所以调用方会先收到：

```text
agent_start
```

这让 UI 或测试知道：agent run 已经开始。

## 7. max_turns 参数检查

源码：

```python
if max_turns is not None and max_turns < 1:
    yield ErrorEvent(message="max_turns must be at least 1", recoverable=False)
    yield AgentEndEvent()
    return
```

`max_turns` 是最多允许多少轮模型调用。

如果调用者传了 0 或负数，这是非法配置，所以直接产出不可恢复错误，然后结束。

注意：

```python
return
```

在 async generator 里表示停止继续产出事件。

## 8. 工具索引：`tool_by_name`

源码：

```python
tool_by_name = {tool.name: tool for tool in tools}
```

这是字典推导式。

如果 `tools` 是：

```python
[
    AgentTool(name="read", ...),
    AgentTool(name="write", ...),
]
```

就会变成：

```python
{
    "read": read_tool,
    "write": write_tool,
}
```

这样后面模型请求：

```python
ToolCall(name="read", ...)
```

loop 可以用：

```python
tool_by_name.get(tool_call.name)
```

快速找到对应工具。

## 9. turn 循环

源码：

```python
turn = 1

while max_turns is None or turn <= max_turns:
    ...
```

一轮 turn 可以理解为“一次 provider/model 响应”。

如果模型没有请求工具，一般一轮就结束。

如果模型请求工具，loop 会：

1. 执行工具
2. 把工具结果写入 transcript
3. 开始下一轮 provider 调用

所以工具调用场景通常至少有两轮：

```text
Turn 1: 模型说我要调用 read
Tool: Tau 执行 read
Turn 2: 模型看到 read 结果后给最终回答
```

## 10. 取消信号

源码：

```python
if signal is not None and signal.is_cancelled():
    yield ErrorEvent(message="Agent run cancelled", recoverable=True)
    break
```

`signal` 是取消令牌。

如果外部已经取消运行，loop 会产出可恢复错误，然后跳出循环。

这里 `recoverable=True` 表示这不是程序 bug，而是用户/系统主动取消。

## 11. turn 开始

源码：

```python
yield TurnStartEvent(turn=turn)
assistant_message: AssistantMessage | None = None
saw_provider_error = False
```

每一轮开始都会产出：

```text
turn_start
```

`assistant_message` 用来保存这一轮 provider 最终返回的完整助手消息。

`saw_provider_error` 用来记住 provider 是否报错。

## 12. 调用 provider 并消费 ProviderEvent

源码：

```python
async for provider_event in provider.stream_response(
    model=model,
    system=system,
    messages=messages,
    tools=tools,
    signal=signal,
):
    ...
```

这里调用的是 Phase 2 定义的 provider 接口。

loop 把当前 transcript 和工具列表交给 provider。

provider 会异步产出 `ProviderEvent`。

loop 逐个处理这些事件。

## 13. ProviderEvent 到 AgentEvent 的转换

这是 Phase 3 最重要的逻辑之一。

### 13.1 response_start -> message_start

```python
if isinstance(provider_event, ProviderResponseStartEvent):
    yield MessageStartEvent()
```

provider 说模型响应开始。

agent loop 对外说一条 assistant message 开始。

### 13.2 text_delta -> message_delta

```python
elif isinstance(provider_event, ProviderTextDeltaEvent):
    yield MessageDeltaEvent(delta=provider_event.delta)
```

provider 流式返回文本片段。

agent loop 对外转成消息文本片段。

### 13.3 thinking_delta -> thinking_delta

```python
elif isinstance(provider_event, ProviderThinkingDeltaEvent):
    yield ThinkingDeltaEvent(delta=provider_event.delta)
```

这是后续增强。

thinking/reasoning 片段会被转发成 agent 层的 `ThinkingDeltaEvent`。

注意：thinking delta 不会被写进 transcript。

测试里验证：

```python
assert messages == [UserMessage(...), assistant]
```

也就是说，最终 transcript 只保存 `AssistantMessage(content="Done")`，不保存 `"hidden reasoning"`。

### 13.4 retry -> retry

```python
elif isinstance(provider_event, ProviderRetryEvent):
    yield RetryEvent(...)
```

provider 层发生临时失败并准备重试，loop 转发成 agent 层 retry 事件。

这让 UI 可以显示“正在重试”，但不需要知道 provider 内部怎么计算重试。

### 13.5 response_end -> message_end + 追加 transcript

```python
elif isinstance(provider_event, ProviderResponseEndEvent):
    assistant_message = provider_event.message
    messages.append(assistant_message)
    yield MessageEndEvent(message=assistant_message)
```

这是关键副作用。

provider 最终返回完整 `AssistantMessage` 后，loop 会：

1. 保存到 `assistant_message`
2. 追加到 transcript：`messages.append(...)`
3. 对外产出 `MessageEndEvent`

### 13.6 provider error -> agent error

```python
elif isinstance(provider_event, ProviderErrorEvent):
    saw_provider_error = True
    yield ErrorEvent(
        message=provider_event.message,
        recoverable=False,
        data=provider_event.data,
    )
```

provider 报错后，loop 产出 agent 层错误事件。

测试里：

```python
provider = FakeProvider([[ProviderErrorEvent(message="provider failed")]])
```

最终事件是：

```text
agent_start
turn_start
error
turn_end
agent_end
```

## 14. 如果 provider 没有返回 assistant message

源码：

```python
if assistant_message is None:
    if signal is not None and signal.is_cancelled():
        yield ErrorEvent(message="Agent run cancelled", recoverable=True)
        yield TurnEndEvent(turn=turn)
        break
    yield TurnEndEvent(turn=turn)
    if saw_provider_error:
        break
    yield ErrorEvent(message="Provider stream ended without an assistant message")
    break
```

正常 provider 应该最终返回 `ProviderResponseEndEvent`。

如果没有，loop 要判断原因：

- 如果是取消：发取消错误
- 如果已经有 provider error：正常停止
- 如果无错误但也无助手消息：发一个错误说明 provider stream 不完整

## 15. 没有 tool_calls：正常结束或注入队列消息

源码：

```python
if not assistant_message.tool_calls:
    yield TurnEndEvent(turn=turn)
    queue_events = _drain_queued_messages(...)
    if queue_events:
        ...
        turn += 1
        continue
    ...
    break
```

如果助手消息没有工具调用，说明这轮通常可以结束。

但当前源码有后续增强：支持 queued steering 和 follow-up。

你可以先按 Phase 3 主线理解：

```text
没有工具调用 -> turn_end -> agent_end
```

然后再理解增强：

- 如果有 steering 消息，追加到 transcript，再继续下一轮
- 如果有 follow-up 消息，追加到 transcript，再继续下一轮

## 16. 有 tool_calls：执行工具后继续下一轮

源码：

```python
async for tool_event in _execute_tool_calls(
    assistant_message.tool_calls,
    tool_by_name,
    messages,
    signal,
):
    yield tool_event

yield TurnEndEvent(turn=turn)
...
turn += 1
```

如果助手消息里有 `tool_calls`，loop 会调用 `_execute_tool_calls()`。

工具执行完后：

- 每个工具结果会被追加为 `ToolResultMessage`
- loop 结束当前 turn
- 然后进入下一轮 provider 调用

下一轮 provider 会看到更新后的 transcript。

## 17. 工具调用完整流程

测试里的例子：

```python
messages = [UserMessage(content="Read README.md")]
```

第一轮 provider 返回：

```python
AssistantMessage(
    content="I'll read it.",
    tool_calls=[
        ToolCall(id="call-1", name="read", arguments={"path": "README.md"})
    ],
)
```

loop 执行 read 工具后，transcript 变成：

```python
[
    UserMessage(content="Read README.md"),
    AssistantMessage(... tool_calls=[...]),
    ToolResultMessage(
        tool_call_id="call-1",
        name="read",
        content="contents of README.md",
        ok=True,
    ),
]
```

第二轮 provider 看到这三条消息，再返回：

```python
AssistantMessage(content="README.md contains project documentation.")
```

最终 transcript 变成：

```python
[
    UserMessage(...),
    AssistantMessage(... tool_calls=[...]),
    ToolResultMessage(...),
    AssistantMessage(content="README.md contains project documentation."),
]
```

这就是 agent tool loop 的核心。

## 18. `_execute_tool_calls()`：顺序执行工具

源码：

```python
async def _execute_tool_calls(
    tool_calls: list[ToolCall],
    tool_by_name: Mapping[str, AgentTool],
    messages: list[AgentMessage],
    signal: CancellationToken | None,
) -> AsyncIterator[AgentEvent]:
    for index, tool_call in enumerate(tool_calls):
        ...
```

这里用 `for` 顺序执行工具调用。

`enumerate(tool_calls)` 会同时给出：

- `index`：当前是第几个工具调用
- `tool_call`：当前工具调用对象

### 18.1 工具执行前发 start 事件

```python
yield ToolExecutionStartEvent(tool_call=tool_call)
```

UI 可以用它显示“正在执行 read 工具”。

### 18.2 查找工具

```python
tool = tool_by_name.get(tool_call.name)
if tool is None:
    result = _unknown_tool_result(tool_call)
else:
    result = await _execute_tool(tool, tool_call, signal)
```

如果模型请求了没有注册的工具，就生成失败结果。

如果找到了工具，就真正执行。

### 18.3 工具结果写入 transcript

```python
messages.append(_tool_result_message(result))
yield ToolExecutionEndEvent(result=result)
```

工具 executor 返回的是 `AgentToolResult`。

但 transcript 里要保存的是 `ToolResultMessage`。

所以中间会调用：

```python
_tool_result_message(result)
```

这正好对应 Phase 1 里你需要分清的概念：

```text
AgentToolResult  -> 工具执行返回值
ToolResultMessage -> 写入对话记录给模型看的消息
```

## 19. 取消时如何处理剩余工具调用

源码：

```python
if signal is not None and signal.is_cancelled():
    for cancelled_tool_call in tool_calls[index:]:
        result = _cancelled_tool_result(cancelled_tool_call)
        messages.append(_tool_result_message(result))
        yield ToolExecutionEndEvent(result=result)
    yield ErrorEvent(message="Agent run cancelled", recoverable=True)
    return
```

如果执行工具批次中途被取消，loop 会把还没执行的工具都记录成失败结果：

```text
Tool call cancelled
```

这样 transcript 不会留下“模型请求了工具但没有结果”的半截状态。

这是一个很细的工程处理。

## 20. `_execute_tool()`：工具异常隔离

源码：

```python
async def _execute_tool(
    tool: AgentTool,
    tool_call: ToolCall,
    signal: CancellationToken | None,
) -> AgentToolResult:
    try:
        result = await tool.execute(tool_call.arguments, signal=signal)
    except Exception as exc:
        return AgentToolResult(
            tool_call_id=tool_call.id,
            name=tool_call.name,
            ok=False,
            content=str(exc),
            error=str(exc),
        )
```

工具执行可能出错。

比如读文件工具可能遇到文件不存在。

loop 不让工具异常直接炸掉整个 agent run，而是把异常转换成失败的 `AgentToolResult`。

这就是注释里的意思：

```python
# tools are an isolation boundary
```

工具是隔离边界。工具坏了，要让模型看到失败结果并有机会恢复。

## 21. 修正 tool_call_id

源码：

```python
if result.tool_call_id != tool_call.id:
    return result.model_copy(update={"tool_call_id": tool_call.id})
return result
```

有些工具 executor 可能返回了错误的 `tool_call_id`。

loop 会强制修正成当前 `ToolCall.id`。

`model_copy(update=...)` 是 Pydantic 模型的复制方法：

- 不直接修改原对象
- 复制一份
- 更新指定字段

这样可以保证工具结果和工具请求能正确对应。

## 22. 未知工具处理

源码：

```python
def _unknown_tool_result(tool_call: ToolCall) -> AgentToolResult:
    message = f"Unknown tool: {tool_call.name}"
    return AgentToolResult(
        tool_call_id=tool_call.id,
        name=tool_call.name,
        ok=False,
        content=message,
        error=message,
    )
```

如果模型请求了没注册的工具，比如：

```python
ToolCall(id="call-1", name="missing", arguments={})
```

loop 不会崩溃。

它会生成：

```python
ToolResultMessage(
    tool_call_id="call-1",
    name="missing",
    content="Unknown tool: missing",
    ok=False,
    error="Unknown tool: missing",
)
```

然后下一轮模型可以看到这个失败结果，尝试换一种方式。

## 23. `_tool_result_message()`：把工具结果变成 transcript 消息

源码：

```python
def _tool_result_message(result: AgentToolResult) -> ToolResultMessage:
    data: dict[str, JSONValue] | None = result.data
    content = result.content
    if not result.ok and result.error and result.error not in content:
        content = f"{content}\n\nError: {result.error}"
    if data is not None and not content:
        content = str(data)

    return ToolResultMessage(...)
```

这个函数负责把 `AgentToolResult` 转换成 `ToolResultMessage`。

里面有两个小逻辑：

### 23.1 失败时补充 error

如果工具失败，而且 `content` 里没有包含 `error`，就把错误追加进去。

这样模型读 transcript 时能看到失败原因。

### 23.2 没有 content 但有 data

如果工具返回了结构化数据 `data`，但没有文本 `content`，就把 data 转成字符串作为内容。

因为 transcript 里的 tool message 必须有可阅读的 `content`。

## 24. 队列注入：后续增强但现在源码里已有

架构文档说明，后续 hardening 加了 queue-drain hooks。

对应源码：

```python
get_steering_messages
get_follow_up_messages
get_queue_update
```

你可以这样理解：

- steering：用户在 agent 正运行时插入的“调整方向”消息
- follow-up：当前 run 本来要停时，继续补问的消息
- queue_update：告诉 UI 队列状态变化

### 24.1 `_drain_queued_messages()`

源码：

```python
def _drain_queued_messages(
    messages: list[AgentMessage],
    get_messages: Callable[[], Sequence[AgentMessage]] | None,
    get_queue_update: Callable[[], QueueUpdateEvent] | None,
) -> tuple[AgentEvent, ...]:
```

它做的事情：

1. 调用 `get_messages()` 拿到队列里的消息
2. 把这些消息追加到 transcript
3. 为每条消息发 `MessageStartEvent` 和 `MessageEndEvent`
4. 如果有 `get_queue_update`，再发一个 `QueueUpdateEvent`

这是为了让 UI 能看到“用户插入的新消息已经进入 transcript”。

### 24.2 为什么这个增强仍然放在 loop

`AgentHarness` 拥有队列，但 loop 拥有注入点。

也就是说：

- 队列怎么存，由 harness 管
- 什么时候把队列消息插进 transcript，由 loop 决定

这样可以保证插入位置稳定。

## 25. max_turns 保护

源码：

```python
else:
    yield ErrorEvent(
        message=f"Agent loop stopped after reaching max_turns={max_turns}",
        recoverable=True,
    )
```

这是 Python `while ... else` 语法。

当 `while` 循环不是被 `break` 打断，而是条件自然结束时，会执行 `else`。

这里表示：

```text
turn 已经超过 max_turns 了
```

所以发一个可恢复错误。

测试里：

```python
max_turns=1
```

模型第一轮一直请求工具，loop 执行完第一轮后不再继续第二轮，并产出：

```text
Agent loop stopped after reaching max_turns=1
```

## 26. Phase 3 的几个典型事件流

### 26.1 纯文本回答

```text
agent_start
turn_start
message_start
message_delta
message_delta
message_end
turn_end
agent_end
```

transcript 变化：

```text
[UserMessage]
↓
[UserMessage, AssistantMessage]
```

### 26.2 工具调用回答

```text
agent_start
turn_start
message_start
message_end
tool_execution_start
tool_execution_end
turn_end
turn_start
message_start
message_delta
message_end
turn_end
agent_end
```

transcript 变化：

```text
[UserMessage]
↓
[UserMessage, AssistantMessage(tool_calls=[...])]
↓
[UserMessage, AssistantMessage(...), ToolResultMessage]
↓
[UserMessage, AssistantMessage(...), ToolResultMessage, AssistantMessage(final)]
```

### 26.3 provider error

```text
agent_start
turn_start
error
turn_end
agent_end
```

transcript 通常不追加 assistant message。

## 27. `tests/test_agent_loop.py` 怎么读

这份测试是 Phase 3 最好的学习入口。

建议按下面顺序看。

### 27.1 文本流和 transcript 追加

```python
test_agent_loop_streams_text_and_appends_assistant_message
```

看懂：

- provider text delta 怎么变成 message delta
- response end 怎么追加 assistant message
- 最终事件顺序是什么

### 27.2 工具调用主流程

```python
test_agent_loop_executes_tools_and_continues_until_no_tool_calls
```

看懂：

- 第一轮 assistant 请求工具
- loop 执行工具
- 追加 tool result
- 第二轮 provider 看到更新后的 transcript

### 27.3 未知工具

```python
test_agent_loop_records_unknown_tool_as_failed_tool_result
```

看懂：

- 模型请求不存在的工具时，loop 不崩溃
- 而是写入失败的 `ToolResultMessage`

### 27.4 provider error

```python
test_agent_loop_converts_provider_error_to_agent_error
```

看懂 provider 层错误如何转成 agent 层错误。

### 27.5 max_turns

```python
test_agent_loop_has_no_default_max_turn_limit
test_agent_loop_stops_after_configured_max_turns
```

看懂：

- 默认没有 turn 上限
- 调用者可以主动加安全上限

## 28. Phase 3 里用到的 Python 语法和包

### 28.1 async generator

`run_agent_loop()` 是 async generator。

因为它里面有：

```python
async def run_agent_loop(...):
    yield AgentStartEvent()
```

普通 async 函数通常用 `return` 返回一个结果。

async generator 用 `yield` 一次次产出结果。

消费方式是：

```python
async for event in run_agent_loop(...):
    ...
```

### 28.2 `async for`

用于消费异步迭代器。

provider stream 和 agent loop 都是异步事件流。

### 28.3 `isinstance()`

用于判断事件具体类型：

```python
if isinstance(provider_event, ProviderTextDeltaEvent):
    ...
```

这是把联合类型拆开的常见写法。

### 28.4 字典推导式

```python
tool_by_name = {tool.name: tool for tool in tools}
```

把工具列表转换成按名称索引的字典。

### 28.5 `while ... else`

```python
while max_turns is None or turn <= max_turns:
    ...
else:
    yield ErrorEvent(...)
```

只有 while 条件自然结束时才进入 else。

如果中途 `break`，不会进入 else。

### 28.6 `model_copy(update=...)`

Pydantic 模型复制并更新字段：

```python
result.model_copy(update={"tool_call_id": tool_call.id})
```

适合不直接修改原模型，而是生成修正后的新对象。

### 28.7 `# noqa: BLE001`

源码里：

```python
except Exception as exc:  # noqa: BLE001 - tools are an isolation boundary
```

`ruff` 通常不鼓励捕获所有 `Exception`。

但这里刻意捕获所有工具异常，因为工具是隔离边界。

`# noqa: BLE001` 是告诉 lint 工具：这里捕获宽泛异常是有意的。

## 29. 小白必须分清的几组概念

### 29.1 ProviderEvent 不是 AgentEvent

ProviderEvent 是模型适配层事件。

AgentEvent 是 agent loop 对外事件。

Phase 3 的 loop 负责转换它们。

### 29.2 AssistantMessage 不是 MessageDeltaEvent

`MessageDeltaEvent` 是流式片段。

`AssistantMessage` 是完整助手消息，会进入 transcript。

### 29.3 AgentToolResult 不是 ToolResultMessage

`AgentToolResult` 是工具 executor 的返回值。

`ToolResultMessage` 是写入 transcript、给模型下一轮看的消息。

### 29.4 工具执行不属于 tau_ai

`tau_ai` 只说“模型请求了工具”。

`tau_agent.loop` 才真正执行 `AgentTool`。

### 29.5 loop 不知道 coding 工具细节

loop 知道怎么执行 `AgentTool`。

但它不知道 read/write/edit/bash 是什么。

这些属于后面的 `tau_coding`。

## 30. 运行测试

Phase 3 最相关的测试是：

```text
tests/test_agent_loop.py
```

运行：

```bash
uv run pytest tests/test_agent_loop.py
```

这组测试覆盖：

- 文本流式事件
- thinking delta 转发
- 工具执行和继续下一轮
- 取消信号传递
- 取消后记录剩余工具失败结果
- steering/follow-up 队列注入
- 未知工具
- provider error
- provider retry 转发
- 默认无 max turn 限制
- 配置 max_turns 后停止

## 31. 用一句话总结 Phase 3

Phase 3 的价值是：实现一个 provider-neutral、UI-neutral、coding-tool-neutral 的 agent loop，把 provider 流式事件转换成 agent 事件，把 assistant 消息和工具结果写回 transcript，并在模型请求工具时执行已注册的 `AgentTool` 后继续下一轮推理。

## 32. 我的问题与推荐回答

问题：为什么 `run_agent_loop()` 要直接修改传入的 `messages` 列表，而不是自己创建并返回一个新的 transcript？

我的推荐回答：

因为 `messages` 是调用者拥有的 transcript，loop 只负责协调一次运行过程并把新产生的 `AssistantMessage` 和 `ToolResultMessage` 追加进去。这样 loop 可以保持轻量和无持久化责任；后面的 `AgentHarness`、session storage 或 CLI/TUI 可以自己决定 transcript 从哪里来、怎么保存、怎么恢复。换句话说，loop 负责“推进 agent 状态”，但不负责“拥有整个应用状态”。
