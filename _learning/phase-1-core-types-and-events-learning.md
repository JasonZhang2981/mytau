# Phase 1 学习笔记：Core Types and Events

对应架构文档：`dev-notes/architecture/phase-1-core-types-and-events.md`

对应源码：

- `src/tau_agent/types.py`
- `src/tau_agent/tools.py`
- `src/tau_agent/messages.py`
- `src/tau_agent/events.py`
- `tests/test_agent_types.py`

## 1. 这一阶段到底在做什么

Phase 1 不负责调用大模型，不负责执行文件读写，也不负责做 TUI 界面。

它只做一件基础但非常重要的事：定义 Tau 内部统一使用的数据形状。

你可以把它理解为给后续所有模块先约定共同语言：

- 用户说的话长什么样：`UserMessage`
- 助手回复长什么样：`AssistantMessage`
- 助手想调用工具时长什么样：`ToolCall`
- 工具执行结果长什么样：`AgentToolResult`
- Agent 运行过程中对外广播的状态长什么样：`AgentEvent`
- 工具参数、事件附加信息这种 JSON 数据允许是什么类型：`JSONValue`

这样后续的 provider、agent loop、harness、CLI、Rich、Textual 都可以围绕同一套对象协作，而不是每个模块都传自己随手拼出来的字典。

## 2. 为什么这些代码放在 `tau_agent`

Tau 的核心分层是：

```text
tau_ai      模型/provider 适配层
tau_agent   可复用 agent 大脑：消息、工具、事件、循环、harness
tau_coding  面向 coding agent 的 CLI、TUI、资源、命令、工具
```

Phase 1 的 4 个文件都在 `src/tau_agent/` 下，因为它们属于可复用 agent 大脑。

它们不应该知道：

- OpenAI 或 Anthropic 的具体 API 格式
- Rich 怎么渲染
- Textual 怎么做 TUI
- CLI 参数怎么解析
- 本地 session 文件放在哪里

这就是架构文档里说的 provider-neutral 和 UI-neutral。

## 3. `types.py`：定义 JSON 数据的范围

源码：

```python
"""Shared low-level types for Tau's portable agent layer."""

# Pydantic needs PEP 695 named recursive aliases for JSON-like values.
type JSONPrimitive = str | int | float | bool | None
type JSONValue = JSONPrimitive | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]
```

### 3.1 `type JSONPrimitive = ...`

这是 Python 3.12+ 的类型别名语法，项目要求 Python `>=3.14`，所以可以使用这种写法。

`JSONPrimitive` 表示 JSON 里最基础的值：

- 字符串：`"hello"`
- 整数：`1`
- 小数：`3.14`
- 布尔值：`true/false`，在 Python 中是 `True/False`
- 空值：`null`，在 Python 中是 `None`

所以：

```python
type JSONPrimitive = str | int | float | bool | None
```

意思是：这个值可以是这些类型中的任意一种。

### 3.2 `JSONValue` 为什么递归

JSON 不只有基础值，还可以嵌套：

```json
{
  "path": "README.md",
  "options": {
    "encoding": "utf-8"
  },
  "lines": [1, 2, 3]
}
```

所以 `JSONValue` 被定义成：

```python
type JSONValue = JSONPrimitive | list[JSONValue] | dict[str, JSONValue]
```

它的意思是：

- 可以是一个基础值
- 可以是一个列表，列表里的每一项也必须是 JSONValue
- 可以是一个字典，key 是字符串，value 也必须是 JSONValue

这种“自己引用自己”的类型叫递归类型。

### 3.3 `JSONObject`

```python
type JSONObject = dict[str, JSONValue]
```

这表示一个 JSON 对象，也就是 Python 里的字典。

它会用于工具参数、事件附加数据、provider payload 等场景。

## 4. `tools.py`：定义工具调用和工具结果

这个文件定义三类东西：

- 工具调用请求：`ToolCall`
- 工具执行结果：`AgentToolResult`
- 工具本身：`AgentTool`

### 4.1 标准库导入

```python
from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from typing import Protocol
```

`from __future__ import annotations`：

让类型注解延迟解析。简单理解就是：Python 先把类型提示当成字符串一样保存起来，避免类还没定义完就被类型引用卡住。

`Mapping`：

表示“像字典一样可以读取 key-value 的对象”。它比 `dict` 更宽泛。函数参数用 `Mapping[str, JSONValue]`，意思是调用者传普通 dict 可以，传其他只读映射也可以。

`Awaitable`：

表示这个东西可以被 `await`。比如 async 函数调用后返回的对象就是 Awaitable。

`Protocol`：

表示一种“只要长得像就可以”的接口。Python 里不强制你继承某个父类，只要对象实现了需要的方法，类型检查器就认为它符合协议。

`dataclass`：

标准库提供的装饰器，用来快速定义主要保存数据的类，少写很多重复的 `__init__`。

### 4.2 `ToolCancellationToken`

```python
class ToolCancellationToken(Protocol):
    """Minimal cancellation interface accepted by tools."""

    def is_cancelled(self) -> bool:
        """Return whether tool execution should stop."""
        ...
```

这是一个协议，意思是：只要一个对象有 `is_cancelled() -> bool` 方法，就可以当成取消信号传给工具。

后面如果用户中断任务，工具可以周期性检查：

```python
if signal and signal.is_cancelled():
    ...
```

### 4.3 `ToolExecutor`

```python
class ToolExecutor(Protocol):
    def __call__(
        self,
        arguments: Mapping[str, JSONValue],
        signal: ToolCancellationToken | None = None,
    ) -> Awaitable[AgentToolResult]:
        ...
```

这是工具执行函数的形状。

一个 executor 必须满足：

- 可以被调用，也就是有 `__call__`
- 接收 JSON-like 参数
- 可选接收取消信号
- 返回一个可以 `await` 的 `AgentToolResult`

测试里有一个例子：

```python
async def executor(arguments, *, signal=None) -> AgentToolResult:
    return AgentToolResult(
        tool_call_id="call-1",
        name="echo",
        ok=True,
        content=str(arguments["text"]),
    )
```

因为它是 `async def`，所以调用它需要：

```python
result = await tool.execute({"text": "hi"})
```

### 4.4 `ToolCall`

```python
class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: dict[str, JSONValue] = Field(default_factory=dict)
```

`ToolCall` 是助手发出的“我要调用某个工具”的请求。

它不是工具本身。

比如助手说：我要读 `README.md`：

```python
ToolCall(
    id="call-1",
    name="read",
    arguments={"path": "README.md"},
)
```

字段解释：

- `id`：这次工具调用的唯一标识，用来把请求和结果对应起来
- `name`：工具名，比如 `read`
- `arguments`：工具参数，必须是 JSON-like 字典

`Field(default_factory=dict)` 的意思是：如果不传 `arguments`，就给每个实例创建一个新的空字典。

不要写成 `arguments: dict = {}`，因为可变默认值容易被多个对象共享，导致奇怪的问题。

### 4.5 `AgentToolResult`

```python
class AgentToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    name: str
    ok: bool
    content: str
    data: dict[str, JSONValue] | None = None
    details: dict[str, JSONValue] | None = None
    error: str | None = None
```

这是工具跑完之后返回给 agent loop 的结构。

字段解释：

- `tool_call_id`：对应哪个 `ToolCall.id`
- `name`：工具名
- `ok`：是否成功
- `content`：给模型继续阅读的文本结果
- `data`：可选的结构化结果
- `details`：可选的调试或补充信息
- `error`：失败时的错误文本

### 4.6 `AgentTool`

```python
@dataclass(frozen=True, slots=True)
class AgentTool:
    name: str
    description: str
    input_schema: Mapping[str, JSONValue]
    executor: ToolExecutor
    prompt_snippet: str | None = None
    prompt_guidelines: tuple[str, ...] = ()
```

`AgentTool` 描述一个可以暴露给 agent 的工具。

字段解释：

- `name`：工具名
- `description`：给模型看的工具说明
- `input_schema`：输入参数的 JSON Schema
- `executor`：真正执行工具的异步函数
- `prompt_snippet`：可选，放进系统提示词的工具说明片段
- `prompt_guidelines`：可选，工具使用规则

`@dataclass(frozen=True, slots=True)`：

- `dataclass`：自动生成初始化方法
- `frozen=True`：创建后不允许随便改字段，更像配置对象
- `slots=True`：减少对象内存开销，也防止随便加不存在的属性

执行工具时：

```python
async def execute(...):
    return await self.executor(arguments, signal=signal)
```

这说明 `AgentTool` 自己不关心工具怎么做事，它只是把参数交给 executor。

这就是解耦：agent loop 只知道“工具可以执行”，不知道工具内部是读文件、写文件还是跑 shell。

## 5. `messages.py`：定义 transcript 里的消息

这个文件定义 transcript，也就是对话记录里的消息类型。

### 5.1 导入

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
```

`Literal`：

表示某个字段只能是固定字符串。

比如：

```python
role: Literal["user"] = "user"
```

意思是 `role` 只能等于 `"user"`。

`BaseModel`：

Pydantic 的模型基类。继承它以后，这个类就具备：

- 参数校验
- 类型转换
- 序列化为字典或 JSON
- 清晰的错误信息

`ConfigDict(extra="forbid")`：

表示不允许传入未定义字段。

比如测试里：

```python
UserMessage(content="hello", unexpected=True)
```

会抛出 `ValidationError`。

这很重要，因为 agent 系统里数据到处流，如果允许多余字段悄悄混进去，后面排查会很难。

### 5.2 `UserMessage`

```python
class UserMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user"] = "user"
    content: str
```

它代表用户发的一条消息。

例子：

```python
UserMessage(content="Read README.md")
```

序列化后：

```python
{"role": "user", "content": "Read README.md"}
```

### 5.3 `AssistantMessage`

```python
class AssistantMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"] = "assistant"
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
```

它代表助手的一条回复。

助手回复可能只有文本：

```python
AssistantMessage(content="Hello")
```

也可能既有文本，又要求调用工具：

```python
AssistantMessage(
    content="I'll inspect the README.",
    tool_calls=[
        ToolCall(id="call-1", name="read", arguments={"path": "README.md"})
    ],
)
```

`tool_calls` 用 `Field(default_factory=list)`，原因和前面的 dict 一样：避免多个消息共享同一个列表。

### 5.4 `ToolResultMessage`

```python
class ToolResultMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["tool"] = "tool"
    tool_call_id: str
    name: str
    content: str
    ok: bool = True
    data: dict[str, JSONValue] | None = None
    details: dict[str, JSONValue] | None = None
    error: str | None = None
```

这是写入 transcript 的工具结果消息。

为什么工具结果也要成为消息？

因为模型下一轮要继续推理时，需要看到工具返回了什么。

流程是：

```text
UserMessage: 用户说读取 README
AssistantMessage: 助手请求 read 工具
ToolResultMessage: Tau 把 read 结果写回 transcript
AssistantMessage: 助手基于工具结果回答
```

### 5.5 `AgentMessage`

```python
type AgentMessage = UserMessage | AssistantMessage | ToolResultMessage
```

这是联合类型，意思是一条 agent 消息可以是以上三种之一。

后续函数可以写：

```python
messages: list[AgentMessage]
```

表示这个列表里可以混合放用户消息、助手消息、工具结果消息。

## 6. `events.py`：定义 agent 对外发出的事件

消息是 transcript 的内容，事件是运行过程中的状态通知。

这是两个不同概念：

- Message：会进入对话记录，影响模型后续推理
- Event：告诉外界发生了什么，通常给 CLI/Rich/Textual/测试消费

比如模型流式输出时，每吐出一点文本，就可以发一个：

```python
MessageDeltaEvent(delta="hello")
```

但是 transcript 里最终只需要保存完整的：

```python
AssistantMessage(content="hello")
```

### 6.1 事件都有稳定的 `type`

比如：

```python
class AgentStartEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["agent_start"] = "agent_start"
```

每个事件都有一个固定字符串 `type`。

这样 UI 或测试可以根据 `event.type` 判断发生了什么。

测试里就检查了：

```python
assert [event.type for event in events] == [
    "message_delta",
    "queue_update",
    "thinking_delta",
    "message_end",
    "tool_execution_start",
    "tool_execution_end",
    "error",
]
```

### 6.2 主要事件分组

生命周期事件：

- `AgentStartEvent`
- `AgentEndEvent`
- `TurnStartEvent`
- `TurnEndEvent`

消息流事件：

- `MessageStartEvent`
- `MessageDeltaEvent`
- `ThinkingDeltaEvent`
- `MessageEndEvent`

工具执行事件：

- `ToolExecutionStartEvent`
- `ToolExecutionUpdateEvent`
- `ToolExecutionEndEvent`

队列、重试、错误：

- `QueueUpdateEvent`
- `RetryEvent`
- `ErrorEvent`

### 6.3 `MessageEndEvent`

```python
class MessageEndEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["message_end"] = "message_end"
    message: AgentMessage
```

这个事件表示一条完整消息结束了。

它携带的是 `AgentMessage`，所以可能是用户消息、助手消息或工具结果消息。

### 6.4 `ToolExecutionStartEvent`

```python
class ToolExecutionStartEvent(BaseModel):
    type: Literal["tool_execution_start"] = "tool_execution_start"
    tool_call: ToolCall
```

这个事件告诉外界：某个工具调用要开始执行了。

### 6.5 `ToolExecutionEndEvent`

```python
class ToolExecutionEndEvent(BaseModel):
    type: Literal["tool_execution_end"] = "tool_execution_end"
    result: AgentToolResult
```

这个事件告诉外界：工具执行结束，并带上工具结果。

### 6.6 `AgentEvent`

```python
type AgentEvent = (
    AgentStartEvent
    | AgentEndEvent
    | TurnStartEvent
    | TurnEndEvent
    | QueueUpdateEvent
    | RetryEvent
    | MessageStartEvent
    | MessageDeltaEvent
    | ThinkingDeltaEvent
    | MessageEndEvent
    | ToolExecutionStartEvent
    | ToolExecutionUpdateEvent
    | ToolExecutionEndEvent
    | ErrorEvent
)
```

和 `AgentMessage` 一样，这是联合类型。

后续 agent loop 可以声明自己产出：

```python
AsyncIterator[AgentEvent]
```

意思是：异步地、一个个地产生 agent 事件。

## 7. Pydantic 在这里做了什么

Pydantic 是 Python 常用的数据建模和校验库。

在这个阶段，它主要负责三件事。

### 7.1 定义数据模型

比如：

```python
class UserMessage(BaseModel):
    role: Literal["user"] = "user"
    content: str
```

你可以像创建普通对象一样创建它：

```python
message = UserMessage(content="hello")
```

### 7.2 校验输入

如果传入不该有的字段：

```python
UserMessage(content="hello", unexpected=True)
```

因为设置了：

```python
ConfigDict(extra="forbid")
```

所以 Pydantic 会报错。

### 7.3 序列化

Pydantic 模型可以转成普通字典：

```python
message.model_dump()
```

测试里验证：

```python
assert message.model_dump() == {"role": "user", "content": "hello"}
```

这对 session 保存、JSON 输出、provider 转换都很重要。

## 8. 小白必须分清的几组概念

### 8.1 `ToolCall` 不是 `AgentTool`

`ToolCall` 是一次请求：

```text
我要调用 read，参数是 {"path": "README.md"}
```

`AgentTool` 是工具定义：

```text
我有一个 read 工具，它的说明、参数 schema、执行函数分别是什么
```

### 8.2 `AgentToolResult` 不是 `ToolResultMessage`

`AgentToolResult` 是工具 executor 返回给 agent loop 的结果。

`ToolResultMessage` 是 agent loop 把结果转换成 transcript 里的消息，给模型下一轮继续阅读。

### 8.3 `MessageDeltaEvent` 不是 `AssistantMessage`

`MessageDeltaEvent` 是流式过程中的一小段输出。

`AssistantMessage` 是最终完整的助手消息。

### 8.4 `data` 和 `content` 的区别

`content` 是给模型或人类阅读的文本。

`data` 是结构化信息，适合程序继续处理。

比如读文件工具可以返回：

```python
AgentToolResult(
    tool_call_id="call-1",
    name="read",
    ok=True,
    content="file contents...",
    data={"path": "README.md"},
)
```

## 9. 运行测试看这些类型如何被验证

只看 Phase 1，最相关的测试是：

```text
tests/test_agent_types.py
```

运行：

```bash
uv run pytest tests/test_agent_types.py
```

它验证了：

- `UserMessage` 可以序列化出固定 `role`
- `AssistantMessage` 可以包含 `ToolCall`
- `ToolResultMessage` 能保存工具输出
- Pydantic 模型会拒绝未知字段
- `AgentTool.execute()` 会调用异步 executor
- 事件的 `type` 字符串稳定

## 10. 用一句话总结 Phase 1

Phase 1 的价值是：先把 agent 系统里的消息、工具、JSON 参数和事件流定义成稳定、可校验、与 provider/UI 无关的数据结构，让后面的模型适配、agent loop、harness、CLI/TUI 都能围绕同一套语言协作。

## 11. 自测问题

1. 为什么工具执行结果要先是 `AgentToolResult`，之后还要变成 `ToolResultMessage`？
2. 为什么 `ToolCall` 只记录工具名和参数，而不直接执行工具？
3. 为什么 `events.py` 里的事件不应该依赖 Rich 或 Textual？
4. `Field(default_factory=list)` 解决的是什么问题？
5. `ConfigDict(extra="forbid")` 对 agent 系统有什么好处？

## 12. 我的问题与推荐回答

问题：为什么 Tau 在 Phase 1 先定义 `UserMessage`、`AssistantMessage`、`ToolCall`、`AgentToolResult` 和各种 `AgentEvent`，而不是一开始就直接调用模型 API 做对话？

我的推荐回答：

因为这些类型是整个 agent 系统的共同语言。模型 provider、agent loop、工具执行、session persistence、CLI/TUI 都要围绕同一套消息和事件协作。如果一开始直接写 provider 调用，后续很容易把 OpenAI 格式、工具实现、UI 展示和 session 存储混在一起。Phase 1 先定义 provider-neutral、可校验、可序列化的数据结构，等于先把系统边界打稳：provider 只负责产出统一事件，agent loop 只消费统一消息，UI 只渲染事件结果。
