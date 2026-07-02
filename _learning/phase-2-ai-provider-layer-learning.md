# Phase 2 学习笔记：AI Provider Layer

对应架构文档：`dev-notes/architecture/phase-2-ai-provider-layer.md`

对应源码：

- `src/tau_ai/events.py`
- `src/tau_ai/provider.py`
- `src/tau_ai/fake.py`
- `src/tau_ai/env.py`
- `src/tau_ai/openai_compatible.py`
- `tests/test_tau_ai.py`

## 1. 这一阶段到底在做什么

Phase 1 定义了 Tau 内部的通用数据形状：消息、工具、JSON 类型和 agent 事件。

Phase 2 开始解决另一个问题：Tau 怎么和不同的大模型 API 对接？

不同模型服务的接口并不一样：

- 请求地址不同
- 鉴权方式不同
- 消息格式不同
- 工具调用格式不同
- 流式响应格式不同
- 错误格式不同

Tau 不希望后面的 agent loop 直接理解这些 provider 细节。

所以 Phase 2 新增了 `tau_ai` 层：

```text
外部模型 API 原始数据
        ↓
tau_ai provider adapter
        ↓
Tau 自己的 ProviderEvent
        ↓
tau_agent loop 后续消费
```

一句话总结：`tau_ai` 负责把外部模型 API 翻译成 Tau 内部统一的 provider 事件流。

## 2. Phase 2 和 Phase 1 的关系

Phase 1 里的类型会被 Phase 2 复用。

比如：

- provider 最终会产出 `AssistantMessage`
- provider 看到模型请求工具时，会产出 `ToolCall`
- provider 接收历史 transcript：`list[AgentMessage]`
- provider 接收可用工具：`list[AgentTool]`

也就是说，`tau_ai` 是模型 API 适配层，但它仍然使用 `tau_agent` 定义的核心类型。

这就是“provider-specific 细节不要污染 agent loop”的基础。

## 3. 重要边界：`tau_ai` 不执行工具

这一点非常关键。

如果模型返回了工具调用，例如：

```text
call read({"path": "README.md"})
```

`tau_ai` 只负责把它翻译成：

```python
ProviderToolCallEvent(
    tool_call=ToolCall(
        id="call-1",
        name="read",
        arguments={"path": "README.md"},
    )
)
```

它不会真的去读 `README.md`。

真正执行工具是 Phase 3 之后 `tau_agent` loop 的责任。

所以边界是：

```text
tau_ai:
  模型说它想调用 read 工具，我把这个请求翻译成 ToolCall。

tau_agent:
  找到注册过的 AgentTool，执行它，把结果写回 transcript。
```

## 4. `events.py`：provider 层自己的事件

源码核心：

```python
class ProviderResponseStartEvent(BaseModel):
    type: Literal["response_start"] = "response_start"
    model: str

class ProviderTextDeltaEvent(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    delta: str

class ProviderToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool_call: ToolCall

class ProviderResponseEndEvent(BaseModel):
    type: Literal["response_end"] = "response_end"
    message: AssistantMessage
    finish_reason: str | None = None

class ProviderErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
    data: dict[str, JSONValue] | None = None
```

这些事件描述的是“模型 provider 正在流式返回什么”。

它们比 Phase 1 里的 `AgentEvent` 更底层。

### 4.1 provider event 和 agent event 的区别

Provider event：

```text
模型开始响应了
模型吐出一段文本
模型返回了一个工具调用
模型响应结束了
provider 请求失败了
```

Agent event：

```text
agent 运行开始
turn 开始
消息开始
消息增量
工具开始执行
工具执行结束
turn 结束
agent 运行结束
```

provider event 是模型适配层的语言。

agent event 是 agent loop 对外广播的语言。

后续 Phase 3 会把 provider event 转换成 agent event。

### 4.2 当前源码比原始 Phase 2 多两个事件

架构文档里列的是 Phase 2 原始核心事件。

当前源码里还多了：

```python
ProviderRetryEvent
ProviderThinkingDeltaEvent
```

这是后续硬化阶段加进来的能力：

- `ProviderRetryEvent`：provider 遇到临时失败，准备重试
- `ProviderThinkingDeltaEvent`：provider 流式返回 reasoning/thinking 文本

学习时你可以先抓住 Phase 2 主线：

```text
response_start
text_delta
tool_call
response_end
error
```

然后把 retry 和 thinking 理解成后续增强。

### 4.3 `ProviderEvent` 联合类型

源码：

```python
type ProviderEvent = (
    ProviderResponseStartEvent
    | ProviderRetryEvent
    | ProviderTextDeltaEvent
    | ProviderThinkingDeltaEvent
    | ProviderToolCallEvent
    | ProviderResponseEndEvent
    | ProviderErrorEvent
)
```

这和 Phase 1 的 `AgentMessage`、`AgentEvent` 思路一样。

它表示：一个 provider 事件可以是这些事件类型中的任意一种。

后续函数可以声明：

```python
AsyncIterator[ProviderEvent]
```

意思是：异步地、一个一个地产生 provider 事件。

## 5. `provider.py`：定义所有 provider 必须遵守的接口

源码：

```python
from collections.abc import AsyncIterator
from typing import Protocol

class CancellationToken(Protocol):
    def is_cancelled(self) -> bool:
        ...

class ModelProvider(Protocol):
    def stream_response(
        self,
        *,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        signal: CancellationToken | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        ...
```

### 5.1 `Protocol` 是什么

`Protocol` 可以理解成“接口约定”。

一个类不需要显式继承 `ModelProvider`，只要它实现了同名、同参数形状的 `stream_response()` 方法，类型检查器就可以认为它符合这个协议。

这很适合 provider 适配层。

未来可以有：

- `OpenAICompatibleProvider`
- `AnthropicProvider`
- `OpenAICodexProvider`
- 其他 provider

只要它们都提供 `stream_response()`，agent loop 就可以统一使用它们。

### 5.2 `AsyncIterator` 是什么

`AsyncIterator[ProviderEvent]` 表示一个异步迭代器。

普通迭代器是：

```python
for item in items:
    ...
```

异步迭代器是：

```python
async for event in provider.stream_response(...):
    ...
```

为什么这里要异步？

因为模型流式响应不是一次性返回完整文本，而是网络上陆续返回：

```text
Hel
lo
工具调用片段
结束
```

网络 IO 本身也适合用 async。

### 5.3 为什么参数前面有 `*`

源码里：

```python
def stream_response(
    self,
    *,
    model: str,
    system: str,
    messages: list[AgentMessage],
    tools: list[AgentTool],
    signal: CancellationToken | None = None,
) -> AsyncIterator[ProviderEvent]:
```

`*` 后面的参数必须用关键字传入。

也就是说必须这样：

```python
provider.stream_response(
    model="gpt-5",
    system="You are Tau.",
    messages=[],
    tools=[],
)
```

不能这样：

```python
provider.stream_response("gpt-5", "You are Tau.", [], [])
```

这样做的好处是可读性强，也不容易把参数顺序传错。

## 6. `fake.py`：可控的假 provider

源码核心：

```python
class FakeProvider:
    def __init__(self, streams: Iterable[Iterable[ProviderEvent]]) -> None:
        self._streams = [list(stream) for stream in streams]
        self.calls: list[tuple[str, str, list[AgentMessage], list[AgentTool]]] = []
```

`FakeProvider` 是测试用 provider。

它不会访问网络，也不会调用真实模型。

你提前给它一组事件，它就按顺序吐出来。

测试里：

```python
scripted = [
    ProviderResponseStartEvent(model="fake-model"),
    ProviderTextDeltaEvent(delta="hello"),
    ProviderResponseEndEvent(message={"role": "assistant", "content": "hello"}),
]
provider = FakeProvider([scripted])
```

然后：

```python
events = await _collect(
    provider.stream_response(
        model="fake-model",
        system="system prompt",
        messages=[UserMessage(content="hi")],
        tools=[],
    )
)
```

最后断言：

```python
assert events == scripted
```

### 6.1 为什么 FakeProvider 很重要

没有 FakeProvider，测试 agent loop 时就要真的访问模型 API。

这会带来很多问题：

- 需要 API key
- 需要网络
- 输出不可控
- 可能限流
- 测试慢
- 费用不可控

FakeProvider 让后续测试变成确定性的。

比如你可以让它固定返回：

```text
第一轮：助手请求 read 工具
第二轮：助手给最终答案
```

这样就能稳定测试 agent loop 是否会执行工具并继续下一轮。

### 6.2 `stream_response()` 里的嵌套 async 函数

源码：

```python
def stream_response(...) -> AsyncIterator[ProviderEvent]:
    self.calls.append(...)
    stream = self._streams.pop(0) if self._streams else []

    async def iterator() -> AsyncIterator[ProviderEvent]:
        for event in stream:
            if signal is not None and signal.is_cancelled():
                return
            yield event

    return iterator()
```

注意：外层 `stream_response()` 不是 `async def`。

它返回的是里面那个 async iterator。

调用方仍然这样消费：

```python
async for event in provider.stream_response(...):
    ...
```

### 6.3 `self.calls` 的作用

`self.calls` 会记录每次 provider 被调用时传入的：

```text
model, system, messages, tools
```

测试可以检查 agent loop 有没有把正确的 transcript 和工具列表传给 provider。

## 7. `env.py`：从环境变量读取 provider 配置

这个文件负责配置，不负责发请求。

### 7.1 常量

```python
DEFAULT_OPENAI_COMPATIBLE_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS = 60.0
DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES = 2
DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS = 1.0
```

这些是默认配置。

如果用户只设置了 `OPENAI_API_KEY`，其他参数就用默认值。

### 7.2 `OpenAICompatibleConfig`

```python
@dataclass(frozen=True, slots=True)
class OpenAICompatibleConfig:
    api_key: str
    base_url: str = DEFAULT_OPENAI_COMPATIBLE_BASE_URL
    headers: Mapping[str, str] | None = None
    timeout_seconds: float = DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES
    max_retry_delay_seconds: float = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS
    reasoning_effort: str | None = None
    reasoning_effort_parameter: str = "reasoning_effort"
```

它是一个配置对象。

字段解释：

- `api_key`：API 密钥
- `base_url`：provider 的 API 根地址
- `headers`：额外 HTTP header
- `timeout_seconds`：HTTP 超时时间
- `max_retries`：最多重试次数
- `max_retry_delay_seconds`：最大重试等待时间
- `reasoning_effort`：后续 reasoning 模型的配置
- `reasoning_effort_parameter`：reasoning 参数在请求里怎么命名

这里又用了：

```python
@dataclass(frozen=True, slots=True)
```

和 Phase 1 里的 `AgentTool` 类似，表示这是一个轻量、不可随便修改的配置对象。

### 7.3 `openai_compatible_config_from_env()`

源码主线：

```python
api_key = environ.get(api_key_var)
if not api_key:
    raise RuntimeError(...)

timeout_seconds = _timeout_seconds_from_env(...)
max_retries = _non_negative_int_from_env(...)
max_retry_delay_seconds = _non_negative_float_from_env(...)

return OpenAICompatibleConfig(...)
```

它读取这些环境变量：

```text
OPENAI_API_KEY
OPENAI_BASE_URL
OPENAI_TIMEOUT_SECONDS
OPENAI_MAX_RETRIES
OPENAI_MAX_RETRY_DELAY_SECONDS
```

其中 `OPENAI_API_KEY` 必须存在。

测试里用 `monkeypatch` 临时设置环境变量：

```python
monkeypatch.setenv("OPENAI_API_KEY", "test-key")
monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1/")
```

然后检查：

```python
assert config.api_key == "test-key"
assert config.base_url == "https://example.test/v1"
```

注意 `base_url` 末尾的 `/` 被去掉了：

```python
environ.get(base_url_var, DEFAULT_OPENAI_COMPATIBLE_BASE_URL).rstrip("/")
```

这样后面拼 URL 时不会出现双斜杠。

### 7.4 为什么要校验环境变量

比如：

```python
OPENAI_TIMEOUT_SECONDS=0
```

超时时间不能小于等于 0。

所以：

```python
if timeout_seconds <= 0:
    raise RuntimeError(...)
```

再比如：

```python
OPENAI_MAX_RETRIES=-1
```

重试次数不能是负数。

所以会抛错。

这种校验让配置错误尽早暴露，而不是等到请求时才出现更难懂的网络问题。

## 8. `openai_compatible.py`：OpenAI-compatible 适配器

这是 Phase 2 里最复杂的文件。

它的职责是：

1. 把 Tau 的消息和工具转换成 OpenAI-compatible 请求 payload
2. 用 `httpx.AsyncClient` 发起流式 HTTP 请求
3. 解析 SSE 流式返回
4. 把文本增量转成 `ProviderTextDeltaEvent`
5. 把工具调用增量拼起来转成 `ProviderToolCallEvent`
6. 最后产出 `ProviderResponseEndEvent`
7. 遇到错误时产出 `ProviderErrorEvent` 或 retry 事件

### 8.1 `httpx` 是什么

`httpx` 是 Python 的 HTTP 客户端库。

这个项目用它做异步 HTTP 请求：

```python
httpx.AsyncClient(...)
```

异步请求的好处是：模型流式返回时，程序可以边等网络边处理事件，不会把整个程序阻塞住。

测试里还用到了：

```python
httpx.MockTransport(handler)
```

这是 `httpx` 提供的测试工具，可以拦截请求并返回假的响应。

这样测试 OpenAI provider 时也不需要真的访问网络。

### 8.2 初始化 provider

```python
class OpenAICompatibleProvider:
    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._owns_client = client is None
```

它接收一个配置对象。

也可以传入已有的 `httpx.AsyncClient`。

如果没有传 client，它会自己创建，并记录：

```python
self._owns_client = client is None
```

这样 `aclose()` 时只关闭自己创建的 client，不会误关外部传入的 client。

### 8.3 `stream_response()` 的主线

这个方法返回 `AsyncIterator[ProviderEvent]`。

里面先构建：

```python
payload = _build_chat_payload(...)
headers = {
    **(dict(self._config.headers or {})),
    "Authorization": f"Bearer {self._config.api_key}",
}
url = f"{self._config.base_url.rstrip('/')}/chat/completions"
```

然后发请求：

```python
async with client.stream("POST", url, json=payload, headers=headers) as response:
    ...
```

这里的 `client.stream()` 表示流式读取响应，而不是等完整响应全部下载完。

### 8.4 请求 payload 如何构建

```python
def _build_chat_payload(...):
    payload = {
        "model": model,
        "stream": True,
        "messages": [
            _system_message(system),
            *[_message_to_openai(message) for message in messages],
        ],
    }
    if tools:
        payload["tools"] = [_tool_to_openai(tool) for tool in tools]
    return payload
```

核心字段：

- `model`：模型名
- `stream: True`：要求 provider 流式返回
- `messages`：系统提示词加历史消息
- `tools`：可用工具列表

`*[_message_to_openai(message) for message in messages]` 是列表展开。

比如：

```python
[
    _system_message(system),
    *converted_messages,
]
```

会变成：

```python
[
    system_message,
    message1,
    message2,
]
```

### 8.5 Tau 消息如何转成 OpenAI 消息

```python
def _message_to_openai(message: AgentMessage) -> dict[str, JSONValue]:
    if isinstance(message, UserMessage):
        return {"role": "user", "content": message.content}

    if isinstance(message, AssistantMessage):
        item = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            item["tool_calls"] = [...]
        return item

    if isinstance(message, ToolResultMessage):
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "name": message.name,
            "content": message.content,
        }
```

这里用了 `isinstance()` 判断消息具体是哪一种。

这就是 Phase 1 的 `AgentMessage` 联合类型在这里发挥作用。

### 8.6 Tau 工具如何转成 OpenAI 工具

```python
def _tool_to_openai(tool: AgentTool) -> dict[str, JSONValue]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.input_schema),
        },
    }
```

Tau 的 `AgentTool` 里有：

- `name`
- `description`
- `input_schema`

OpenAI-compatible API 需要：

```json
{
  "type": "function",
  "function": {
    "name": "...",
    "description": "...",
    "parameters": {...}
  }
}
```

所以 adapter 就负责格式转换。

### 8.7 SSE 是什么

OpenAI-compatible 流式接口通常返回 Server-Sent Events，简称 SSE。

它长得像：

```text
data: {"choices":[{"delta":{"content":"Hel"}}]}

data: {"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}

data: [DONE]
```

每一行 `data:` 后面是一段 JSON。

源码里：

```python
async for line in response.aiter_lines():
    event = _parse_sse_line(line)
```

`response.aiter_lines()` 会异步地一行一行读取响应。

### 8.8 `_parse_sse_line()`

```python
def _parse_sse_line(line: str) -> str | None:
    line = line.strip()
    if not line or not line.startswith("data:"):
        return None
    return line.removeprefix("data:").strip()
```

它做三件事：

1. 去掉行首行尾空白
2. 忽略空行或不是 `data:` 开头的行
3. 去掉 `data:` 前缀，得到真正的内容

例如：

```text
data: {"choices":[...]}
```

会变成：

```text
{"choices":[...]}
```

### 8.9 `_loads_object()`

```python
def _loads_object(value: str) -> dict[str, JSONValue] | None:
    try:
        loaded = loads(value)
    except JSONDecodeError:
        return None
    if isinstance(loaded, dict):
        return loaded
    return None
```

`json.loads()` 把 JSON 字符串转成 Python 对象。

如果解析失败，就返回 `None`。

如果解析出来不是字典，也返回 `None`。

这样调用方可以简单判断：

```python
chunk = _loads_object(event)
if chunk is None:
    yield ProviderErrorEvent(...)
    return
```

### 8.10 文本流如何转成事件

核心逻辑：

```python
content = delta.get("content")
if isinstance(content, str) and content:
    content_parts.append(content)
    yield ProviderTextDeltaEvent(delta=content)
```

模型每吐出一段文本，就立刻产出一个 `ProviderTextDeltaEvent`。

同时把它追加到 `content_parts`。

等流结束后：

```python
message = AssistantMessage(
    content="".join(content_parts),
    tool_calls=tool_calls,
)
yield ProviderResponseEndEvent(message=message, finish_reason=finish_reason)
```

也就是说：

- `ProviderTextDeltaEvent` 用于流式显示
- `ProviderResponseEndEvent.message` 用于最终完整消息

### 8.11 工具调用为什么要 builder

OpenAI-compatible API 的工具调用参数可能是分片返回的。

测试里模拟了这种情况：

```text
第一片：
{"function":{"name":"read","arguments":"{\"path\":"}}

第二片：
{"function":{"arguments":"\"README.md\"}"}}
```

两个片段拼起来才是：

```json
{"path":"README.md"}
```

所以源码里有：

```python
class _ToolCallBuilder:
    def __init__(self) -> None:
        self.id = ""
        self.name = ""
        self.arguments_parts: list[str] = []
```

每次收到工具调用 delta：

```python
builder.add_delta(tool_call_delta)
```

最后：

```python
builder.build(index)
```

生成 Tau 自己的 `ToolCall`。

### 8.12 `_ToolCallBuilder.build()`

```python
arguments_text = "".join(self.arguments_parts)
arguments = _loads_object(arguments_text) if arguments_text else {}
if arguments is None:
    arguments = {"_raw_arguments": arguments_text}

return ToolCall(
    id=self.id or f"tool-call-{index}",
    name=self.name,
    arguments=arguments,
)
```

这里有两个容错点：

1. 如果 provider 没给 id，就用 `tool-call-{index}` 生成一个
2. 如果 arguments 不是合法 JSON，就放进 `{"_raw_arguments": ...}`，避免直接崩溃

### 8.13 错误和重试

当前源码里已经加入了 retry 逻辑。

如果 HTTP 状态码是临时错误，比如：

```python
408, 409, 425, 429, 或 >= 500
```

并且还没超过最大重试次数，就会：

```python
yield ProviderRetryEvent(...)
```

然后等待一段时间再重试。

如果是非临时错误，比如 400，就不会重试，而是：

```python
yield ProviderErrorEvent(...)
```

测试里分别覆盖了：

- 500 会重试
- 400 不重试
- retry backoff 时如果收到取消信号就停止

## 9. `tests/test_tau_ai.py`：如何反向理解这一层

这份测试很适合学习 Phase 2，因为它从外部行为验证 provider 层。

重点测试包括：

### 9.1 FakeProvider 重放事件

```python
test_fake_provider_replays_scripted_events
```

验证 FakeProvider 会原样产出预设事件，并记录调用参数。

### 9.2 环境变量配置

```python
test_openai_compatible_config_from_env
test_openai_compatible_config_from_env_rejects_invalid_timeout
test_openai_compatible_config_from_env_rejects_invalid_retry_settings
```

验证配置能从环境变量读取，并且非法配置会报错。

### 9.3 请求格式和文本流

```python
test_openai_compatible_provider_formats_request_and_streams_text
```

验证：

- 请求 URL 是 `/chat/completions`
- header 有 bearer token
- payload 里有 system/user messages
- SSE 文本片段会变成 `ProviderTextDeltaEvent`
- 最终拼成完整 `AssistantMessage`

### 9.4 工具调用流

```python
test_openai_compatible_provider_streams_tool_calls
```

验证：

- `AgentTool` 会被转换成 OpenAI function schema
- 分片工具参数会被拼回完整 JSON
- 最终会产出 `ProviderToolCallEvent`
- response end message 里也带着 tool_calls

## 10. Phase 2 里用到的 Python 包和概念

### 10.1 `httpx`

用途：发 HTTP 请求。

这里用：

- `httpx.AsyncClient`：异步 HTTP 客户端
- `client.stream()`：流式请求
- `response.aiter_lines()`：异步读取响应行
- `httpx.MockTransport`：测试里模拟 HTTP 响应

### 10.2 `json.loads` 和 `json.dumps`

```python
from json import JSONDecodeError, dumps, loads
```

- `loads()`：把 JSON 字符串转成 Python 对象
- `dumps()`：把 Python 对象转成 JSON 字符串
- `JSONDecodeError`：JSON 解析失败时抛出的异常类型

工具调用参数需要用 JSON 字符串传给 OpenAI-compatible API，所以会用 `dumps()`。

解析 SSE 里的 JSON chunk 时会用 `loads()`。

### 10.3 `os.environ`

```python
from os import environ
```

`environ` 可以读取环境变量：

```python
api_key = environ.get("OPENAI_API_KEY")
```

### 10.4 `AsyncIterator`

异步迭代器，适合流式数据。

provider 的返回值不是一个完整列表，而是一条一条产出事件：

```python
async for event in provider.stream_response(...):
    ...
```

### 10.5 `Mapping`

表示只需要“像字典一样读取”的对象。

比直接写 `dict` 更灵活。

比如：

```python
headers: Mapping[str, str] | None = None
```

表示 headers 可以是普通字典，也可以是其他映射类型。

### 10.6 `Any`

```python
from typing import Any
```

`Any` 表示任意类型。

在解析外部 API 返回的 JSON 时，静态类型很难完全确定，所以会先用 `Mapping[str, Any]` 接住，再逐步判断：

```python
delta = choice.get("delta")
if not isinstance(delta, Mapping):
    continue
```

### 10.7 `isinstance()`

用于运行时判断对象类型。

例如：

```python
if isinstance(message, UserMessage):
    ...
```

这让 adapter 可以根据不同 Tau 消息类型生成不同 provider payload。

## 11. 小白必须分清的几组概念

### 11.1 ProviderEvent 不是 AgentEvent

`ProviderEvent` 是模型适配层事件。

`AgentEvent` 是 agent loop 对外事件。

Phase 2 只负责 ProviderEvent。

### 11.2 Provider 不等于 Model

`model` 是具体模型名，比如 `gpt-5`。

`provider` 是调用模型 API 的适配器，比如 `OpenAICompatibleProvider`。

一个 provider 可以调用多个 model。

### 11.3 Provider 不执行工具

provider 只翻译工具调用请求。

执行工具属于 agent loop。

### 11.4 Delta 不是最终消息

`ProviderTextDeltaEvent(delta="Hel")` 是流式片段。

`ProviderResponseEndEvent(message=AssistantMessage(content="Hello"))` 是最终完整消息。

### 11.5 FakeProvider 不是 mock 大模型智能

FakeProvider 不会思考。

它只是按测试提前写好的事件列表重放。

它的价值是稳定、可控、无需网络。

## 12. 运行测试

Phase 2 最相关的测试文件是：

```text
tests/test_tau_ai.py
```

可以运行：

```bash
uv run pytest tests/test_tau_ai.py
```

这个测试文件现在也覆盖了后续 provider 增强能力，比如 Anthropic、OpenAI Codex、retry、thinking delta。

如果只按 Phase 2 主线理解，优先看文件前半部分：

- `test_fake_provider_replays_scripted_events`
- `test_openai_compatible_config_from_env`
- `test_openai_compatible_provider_formats_request_and_streams_text`
- `test_openai_compatible_provider_streams_tool_calls`

## 13. 用一句话总结 Phase 2

Phase 2 的价值是：把真实模型 API 的请求、鉴权、流式响应、工具调用格式和错误处理封装在 `tau_ai` provider 层里，对外只暴露统一的 `ModelProvider.stream_response()` 和 `ProviderEvent` 流，让后续 agent loop 不需要知道任何具体 provider 的细节。

## 14. 自测问题

1. 为什么 `tau_ai` 不能直接执行工具？
2. `ProviderTextDeltaEvent` 和 `ProviderResponseEndEvent` 分别解决什么问题？
3. 为什么 OpenAI-compatible 的工具参数需要 `_ToolCallBuilder` 拼接？
4. `FakeProvider` 对测试 agent loop 有什么价值？
5. `ModelProvider` 为什么用 `Protocol` 而不是要求所有 provider 继承同一个父类？

## 15. 我的问题与推荐回答

问题：为什么 Phase 2 要把 OpenAI-compatible、Anthropic、Codex 这些真实模型接入都封装在 `tau_ai` provider 层，而不是让 `tau_agent` 直接调用某一家模型 API？

我的推荐回答：

因为 `tau_agent` 应该是可复用的 agent 大脑，不应该知道任何一家 provider 的请求格式、鉴权方式、流式协议或错误结构。Phase 2 用 `ModelProvider.stream_response()` 作为统一接口，把不同 provider 的细节转换成统一的 `ProviderEvent` 流。这样后面的 agent loop 只需要处理 `ProviderTextDeltaEvent`、`ProviderToolCallDeltaEvent`、`ProviderResponseEndEvent`、`ProviderErrorEvent` 等中立事件，不会被某个模型厂商绑定；测试时也可以用 `FakeProvider` 精确模拟流式输出。
