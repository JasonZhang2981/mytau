# Phase 4 学习笔记：AgentHarness

对应架构文档：`dev-notes/architecture/phase-4-agent-harness.md`

对应源码：

- `src/tau_agent/harness.py`
- `tests/test_agent_harness.py`
- `src/tau_agent/__init__.py`

前置阶段：

- Phase 1：定义消息、工具、事件等基础类型
- Phase 2：定义 provider 层和 provider event
- Phase 3：定义 `run_agent_loop()`，把 provider、messages、tools 串起来

## 1. 这一阶段到底在做什么

Phase 4 新增 `AgentHarness`。

Phase 3 的 `run_agent_loop()` 是一个偏“函数式”的循环：

```text
调用者传入 messages
loop 读取 messages
loop 追加 AssistantMessage / ToolResultMessage
loop 产出 AgentEvent
```

但是它自己不长期拥有 transcript。

Phase 4 的 `AgentHarness` 开始承担“可复用 agent 大脑”的状态管理：

- 保存当前 transcript
- 保存 provider/model/system/tools/max_turns 配置
- 调用 `run_agent_loop()`
- 对外提供 `prompt()` 和 `continue_()`
- 支持事件 listener
- 支持取消
- 支持 queued steering/follow-up 消息
- 在中断 tool call 后修复 transcript

一句话总结：`AgentHarness` 是建立在纯 agent loop 之上的状态层。

## 2. AgentHarness 仍然不是什么

`AgentHarness` 很重要，但它还不是完整 coding agent app。

它不应该知道：

- session 文件保存在哪里
- cwd 是哪个项目目录
- slash command 怎么解析
- Rich 怎么渲染
- Textual 怎么显示
- 内置 read/write/edit/bash 工具怎么创建
- 项目 instructions 或 skills 怎么加载

这些属于后面的 `tau_coding`。

Phase 4 的边界是：

```text
AgentHarness:
  transcript / loop / cancel / queue / listener

CodingSession:
  cwd / tools / resources / commands / persistence

TUI:
  rendering / keyboard / widgets
```

## 3. 当前源码比原始 Phase 4 多了什么

架构文档描述的是 Phase 4 原始主线：

- `AgentHarnessConfig`
- `AgentHarness`
- `SimpleCancellationToken`
- `EventListener`
- `prompt()`
- `continue_()`
- transcript snapshot
- subscribe listener
- cancel

当前源码里还包含后续增强：

- `QueuedMessages`
- `steer()`
- `follow_up()`
- `clear_queues()`
- `pop_latest_follow_up()`
- `queue_mode`
- `_append_interrupted_tool_results()`

学习时可以分两层看：

```text
Phase 4 主线：
  harness 拥有 transcript，并调用 run_agent_loop

当前源码增强：
  harness 还管理运行中/运行后的用户队列和中断修复
```

## 4. `harness.py` 的导入怎么看

源码开头：

```python
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Literal
```

这些都是 Python 标准库。

### 4.1 `deque`

`deque` 是 double-ended queue，双端队列。

它适合做队列，因为从左边弹出比 list 更自然：

```python
queue.popleft()
```

这里用于保存 queued steering 和 follow-up 消息。

### 4.2 `AsyncIterator`

异步迭代器。

`prompt()` 和 `continue_()` 最终都会返回：

```python
AsyncIterator[AgentEvent]
```

调用方用：

```python
async for event in harness.prompt("Hi"):
    ...
```

### 4.3 `Awaitable`

表示可以被 `await` 的对象。

事件 listener 可以是同步函数，也可以是 async 函数。

所以类型写成：

```python
EventListener = Callable[[AgentEvent], Awaitable[None] | None]
```

意思是：

```text
listener 接收一个 AgentEvent，可能直接返回 None，也可能返回一个可 await 的对象。
```

### 4.4 `Callable`

表示“可调用对象”，通常就是函数。

比如 listener、unsubscribe callback 都是 Callable。

### 4.5 `Sequence`

表示有顺序的一组元素，比如 list 或 tuple。

构造 harness 时：

```python
messages: Sequence[AgentMessage] = ()
```

表示可以传 list，也可以传 tuple。

### 4.6 `suppress`

来自：

```python
from contextlib import suppress
```

它可以忽略指定异常。

源码里用于 unsubscribe：

```python
with suppress(ValueError):
    self._listeners.remove(listener)
```

如果 listener 已经不在列表里，`remove()` 会抛 `ValueError`。

这里选择忽略这个错误，让 unsubscribe 可以安全重复调用。

### 4.7 `dataclass` 和 `field`

`dataclass` 自动生成初始化方法。

`field(default_factory=list)` 用于创建独立的默认 list。

```python
tools: list[AgentTool] = field(default_factory=list)
```

不要写成：

```python
tools: list[AgentTool] = []
```

因为可变默认值可能在多个 config 实例之间共享。

### 4.8 `isawaitable`

来自：

```python
from inspect import isawaitable
```

它用于判断 listener 的返回值是否需要 `await`。

源码：

```python
result = listener(event)
if isawaitable(result):
    await result
```

这样 harness 同时支持同步 listener 和异步 listener。

### 4.9 `Literal`

用于限定字符串只能是某几个值。

```python
QueueMode = Literal["one_at_a_time", "all"]
```

表示 queue mode 只能是：

- `"one_at_a_time"`
- `"all"`

## 5. `EventListener` 和 `QueueMode`

源码：

```python
EventListener = Callable[[AgentEvent], Awaitable[None] | None]
QueueMode = Literal["one_at_a_time", "all"]
```

### 5.1 EventListener

listener 是事件观察者。

当 harness 运行时，每个事件除了被 `yield` 给主调用者，还会通知 listener。

这适合做：

- 日志
- 指标统计
- session persistence hook
- UI bridge

### 5.2 QueueMode

queue mode 控制 queued messages 怎么被取出。

- `"one_at_a_time"`：每次只取一个 queued message，默认值
- `"all"`：一次取出所有 queued messages

这是后续增强，不是原始 Phase 4 最核心内容。

## 6. `QueuedMessages`

源码：

```python
@dataclass(frozen=True, slots=True)
class QueuedMessages:
    steering: tuple[AgentMessage, ...] = ()
    follow_up: tuple[AgentMessage, ...] = ()

    @property
    def count(self) -> int:
        return len(self.steering) + len(self.follow_up)
```

它是队列快照。

注意它用的是 tuple，不是 list。

这和 `harness.messages` 的设计一样：对外给快照，避免外部直接改内部状态。

### 6.1 `@property`

`count` 是属性方法。

调用时像字段：

```python
queued.count
```

而不是：

```python
queued.count()
```

## 7. `AgentHarnessConfig`

源码：

```python
@dataclass(slots=True)
class AgentHarnessConfig:
    provider: ModelProvider
    model: str
    system: str
    tools: list[AgentTool] = field(default_factory=list)
    max_turns: int | None = None
    queue_mode: QueueMode = "one_at_a_time"
```

这是 harness 的稳定配置。

字段解释：

- `provider`：模型 provider，比如 FakeProvider 或 OpenAICompatibleProvider
- `model`：模型名
- `system`：系统提示词
- `tools`：可用工具列表
- `max_turns`：最多允许多少轮模型调用
- `queue_mode`：队列消息排空方式

### 7.1 为什么有 config 对象

如果每次调用 `prompt()` 都要传 provider/model/system/tools，会很乱。

所以 harness 初始化时固定这些配置：

```python
harness = AgentHarness(
    AgentHarnessConfig(
        provider=provider,
        model="fake",
        system="You are Tau.",
        tools=[tool],
    )
)
```

之后每次：

```python
async for event in harness.prompt("Hi"):
    ...
```

harness 会自动使用 config 里的 provider/model/system/tools。

## 8. `SimpleCancellationToken`

源码：

```python
class SimpleCancellationToken:
    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled
```

这是一个最小取消令牌。

逻辑很简单：

- 初始 `_cancelled = False`
- 调用 `cancel()` 后变成 True
- loop/provider/tool 可以通过 `is_cancelled()` 检查是否应该停止

Phase 3 的 `run_agent_loop()` 已经支持 signal。

Phase 4 的 harness 负责创建和持有这个 signal。

## 9. `AgentHarness.__init__()`

源码：

```python
def __init__(
    self,
    config: AgentHarnessConfig,
    *,
    messages: Sequence[AgentMessage] = (),
) -> None:
    self._config = config
    self._messages = list(messages)
    self._listeners: list[EventListener] = []
    self._current_signal: SimpleCancellationToken | None = None
    self._running = False
    self._steering_queue: deque[AgentMessage] = deque()
    self._follow_up_queue: deque[AgentMessage] = deque()
```

初始化时保存：

- config
- transcript
- listener 列表
- 当前取消 signal
- 当前是否运行中
- steering 队列
- follow-up 队列

### 9.1 为什么 `self._messages = list(messages)`

构造参数允许传 `Sequence`。

内部统一转成 list，因为 harness 后面要追加消息。

如果外部传 tuple，内部也能正常 append。

### 9.2 下划线字段是什么意思

像 `_messages`、`_listeners`、`_running` 这种单下划线是 Python 约定：

```text
这是内部实现细节，不建议外部直接访问。
```

它不是强制 private，但表示“请通过公开方法访问”。

## 10. transcript 快照：`messages`

源码：

```python
@property
def messages(self) -> tuple[AgentMessage, ...]:
    return tuple(self._messages)
```

对外返回 tuple 快照。

为什么不直接返回 list？

如果直接返回内部 list，外部就能这样改：

```python
harness.messages.append(...)
```

这会绕过 harness 的控制。

返回 tuple 可以避免外部误改。

测试里验证：

```python
snapshot = harness.messages
harness.append_message(AssistantMessage(content="Hi"))

assert snapshot == (UserMessage(content="Hello"),)
```

旧 snapshot 不会跟着变。

## 11. `append_message()` 和 `replace_messages()`

源码：

```python
def append_message(self, message: AgentMessage) -> None:
    self._messages.append(message)

def replace_messages(self, messages: Sequence[AgentMessage]) -> None:
    self._messages = list(messages)
```

这两个方法用于受控地恢复或重建 transcript。

比如后续 session storage 读出历史消息后，可以：

```python
harness.append_message(existing_message)
```

或者上下文压缩后：

```python
harness.replace_messages(compacted_messages)
```

## 12. 事件订阅：`subscribe()`

源码：

```python
def subscribe(self, listener: EventListener) -> Callable[[], None]:
    self._listeners.append(listener)

    def unsubscribe() -> None:
        with suppress(ValueError):
            self._listeners.remove(listener)

    return unsubscribe
```

调用：

```python
unsubscribe = harness.subscribe(listener)
```

之后 harness 每产生一个事件，都会通知 listener。

不想听了就：

```python
unsubscribe()
```

### 12.1 为什么返回 unsubscribe 函数

这是常见订阅模式：

```text
subscribe 时拿到一个取消订阅函数
以后调用这个函数就取消订阅
```

比让调用方自己操作内部 `_listeners` 安全。

## 13. 取消：`cancel()`

源码：

```python
def cancel(self) -> None:
    if self._current_signal is not None:
        self._current_signal.cancel()
```

harness 当前运行时会创建一个 `SimpleCancellationToken`。

`cancel()` 就是把这个 token 标记为 cancelled。

真正停止发生在 Phase 3 的 loop/provider/tool 检查 signal 时。

这是一种协作式取消：

```text
harness 只是请求取消
loop/provider/tool 看到 signal 后停下来
```

## 14. 队列方法：`steer()` 和 `follow_up()`

源码：

```python
def steer(self, content: str) -> QueueUpdateEvent:
    return self.steer_message(UserMessage(content=content))

def follow_up(self, content: str) -> QueueUpdateEvent:
    return self.follow_up_message(UserMessage(content=content))
```

### 14.1 steering 是什么

steering 是运行中插入的方向调整。

比如 agent 正在做任务，你说：

```text
先别改代码，先解释一下
```

这类消息可以进入 steering queue。

### 14.2 follow-up 是什么

follow-up 是当前 run 本来要停时继续追加的问题。

比如模型回答完第一问后，你排队一个：

```text
再总结一下
```

### 14.3 为什么返回 QueueUpdateEvent

这让 UI 可以立刻更新 pending queue 状态。

```python
queue_event = harness.steer("Queued instead")
assert queue_event.steering == ("Queued instead",)
```

## 15. `queue_update_event()`

源码：

```python
def queue_update_event(self) -> QueueUpdateEvent:
    return QueueUpdateEvent(
        steering=tuple(message.content for message in self._steering_queue),
        follow_up=tuple(message.content for message in self._follow_up_queue),
    )
```

这里用生成器表达式：

```python
message.content for message in self._steering_queue
```

把队列里的消息对象转换成内容字符串。

最终事件只带内容快照：

```python
QueueUpdateEvent(
    steering=("Adjust",),
    follow_up=("Later",),
)
```

## 16. `prompt()`：追加用户消息并运行 loop

源码：

```python
def prompt(self, content: str) -> AsyncIterator[AgentEvent]:
    self._ensure_not_running()
    self._append_interrupted_tool_results()
    self._running = True
    message = UserMessage(content=content)
    self._messages.append(message)
    return self._run(prompt_message=message)
```

这就是最常用入口。

它做了几件事：

1. 确认当前没有正在运行的 prompt
2. 修复上一次中断留下的未完成 tool call
3. 设置 `_running = True`
4. 创建 `UserMessage`
5. 追加到 transcript
6. 调用内部 `_run()`

### 16.1 prompt 和 run_agent_loop 的区别

`run_agent_loop()` 不会自己创建用户消息。

它只接收已有 `messages`。

`harness.prompt("Hi")` 会先把 `"Hi"` 变成：

```python
UserMessage(content="Hi")
```

然后再启动 loop。

## 17. `continue_()`：不追加用户消息，继续运行

源码：

```python
def continue_(self) -> AsyncIterator[AgentEvent]:
    self._ensure_not_running()
    self._append_interrupted_tool_results()
    self._running = True
    return self._run()
```

它和 `prompt()` 的区别是：

- `prompt()` 会追加新的 `UserMessage`
- `continue_()` 不追加消息

适用场景：

- 恢复已有 session 后继续
- 被上层 wrapper 控制何时继续
- 已经有消息在 transcript 里，只需要让模型继续生成

测试里：

```python
existing = UserMessage(content="Previous prompt")
harness = AgentHarness(..., messages=[existing])

await harness.continue_()
```

provider 看到的 transcript 是：

```python
[existing]
```

## 18. `_run()`：harness 和 loop 的连接点

源码核心：

```python
async def _run(self, *, prompt_message: UserMessage | None = None) -> AsyncIterator[AgentEvent]:
    signal = SimpleCancellationToken()
    self._current_signal = signal
    pending_prompt_event = prompt_message
    try:
        async for event in run_agent_loop(...):
            await self._notify(event)
            yield event
            ...
    finally:
        ...
```

`_run()` 做几件关键事情：

- 创建本次运行的取消 token
- 保存为 `_current_signal`
- 调用 `run_agent_loop()`
- 每收到一个 event，先通知 listener，再 yield 给主调用者
- 运行结束后清理 `_current_signal` 和 `_running`

## 19. 为什么 prompt 的用户消息事件在 `_run()` 里补发

Phase 3 的 `run_agent_loop()` 会把 provider 产生的 assistant 消息转成事件。

但 `prompt()` 里新追加的 user message 是 harness 自己加的，不是 provider 产生的。

为了让 UI/监听器也能看到用户消息进入 transcript，harness 在 turn 开始后补发：

```python
if pending_prompt_event is not None and event.type == "turn_start":
    start = MessageStartEvent(message_role="user")
    end = MessageEndEvent(message=pending_prompt_event)
    ...
```

测试里事件顺序是：

```text
agent_start
turn_start
message_start   # user
message_end     # user
message_start   # assistant
message_end     # assistant
turn_end
agent_end
```

这就是为什么 `prompt()` 比直接 `run_agent_loop()` 多了 user message 事件。

## 20. `_notify()`：通知 listener

源码：

```python
async def _notify(self, event: AgentEvent) -> None:
    for listener in list(self._listeners):
        result = listener(event)
        if isawaitable(result):
            await result
```

注意：

```python
for listener in list(self._listeners):
```

这里复制了一份 listener 列表。

这样 listener 执行过程中即使 unsubscribe，也不容易影响当前遍历。

### 20.1 同步 listener

```python
def listener(event):
    print(event.type)
```

返回 None，不需要 await。

### 20.2 异步 listener

```python
async def listener(event):
    await save_event(event)
```

返回 awaitable，需要 await。

`isawaitable()` 就是为了同时支持这两种。

## 21. `_ensure_not_running()`

源码：

```python
def _ensure_not_running(self) -> None:
    if self._running:
        raise RuntimeError(
            "AgentHarness is already running; use steer() or follow_up() to queue messages."
        )
```

harness 不允许两个 prompt 同时跑。

如果已经在运行中，又调用：

```python
harness.prompt("Overlapping")
```

会抛 `RuntimeError`。

为什么？

因为两个 loop 同时修改同一个 transcript 会非常危险。

正确方式是：

- 用 `steer()` 插入运行中的调整
- 用 `follow_up()` 排队后续问题

## 22. 队列排空：`_drain_queue()`

源码：

```python
def _drain_queue(self, queue: deque[AgentMessage]) -> tuple[AgentMessage, ...]:
    if not queue:
        return ()
    if self._config.queue_mode == "all":
        messages = tuple(queue)
        queue.clear()
        return messages
    return (queue.popleft(),)
```

两种模式：

### 22.1 默认：one_at_a_time

每次只取一条消息。

```python
return (queue.popleft(),)
```

如果 follow-up 队列里有两条：

```text
Second prompt
Third prompt
```

会分两轮模型调用处理。

### 22.2 all

一次取出所有消息：

```python
messages = tuple(queue)
queue.clear()
return messages
```

然后下一次 provider 调用会同时看到这些 user messages。

## 23. 中断 tool call 后的 transcript 修复

当前源码有一个很重要的工程补丁：

```python
def _append_interrupted_tool_results(self) -> None:
    ...
```

背景：

OpenAI-compatible provider 要求：

```text
assistant message 里如果有 tool_calls
后面必须跟对应的 tool result message
```

如果 UI 在工具执行中途强行关闭 stream，可能留下这种半截 transcript：

```python
[
    UserMessage(content="Read README.md"),
    AssistantMessage(content="I'll read it.", tool_calls=[ToolCall(id="call-1", ...)]),
]
```

这里缺少 `ToolResultMessage(tool_call_id="call-1")`。

下一次再发给 provider，provider 可能拒绝。

所以 harness 在下一次 `prompt()` 或 `continue_()` 前会修复：

```python
ToolResultMessage(
    tool_call_id="call-1",
    name="read",
    content="Tool call interrupted by user",
    ok=False,
    error="Tool call interrupted by user",
)
```

这样 transcript 恢复完整。

## 24. `_latest_open_tool_call_assistant_index()`

源码：

```python
def _latest_open_tool_call_assistant_index(messages: Sequence[AgentMessage]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, UserMessage):
            return None
        if isinstance(message, AssistantMessage):
            if message.tool_calls:
                return index
            return None
    return None
```

它从 transcript 尾部往前找最近一条 assistant message。

如果最近遇到的是 `UserMessage`，说明没有打开的 tool call。

如果遇到 `AssistantMessage`：

- 有 `tool_calls`：返回这条 assistant message 的位置
- 没有 `tool_calls`：返回 None

### 24.1 `range(len(messages) - 1, -1, -1)`

这是倒序遍历。

如果 messages 长度是 5，它会产生：

```text
4, 3, 2, 1, 0
```

用于从最后一条消息往前找。

## 25. `tests/test_agent_harness.py` 怎么读

这份测试是 Phase 4 最好的学习入口。

建议按下面顺序看。

### 25.1 prompt 主流程

```python
test_prompt_appends_user_message_and_assistant_response
```

验证：

- `prompt("Hi")` 会追加 `UserMessage`
- harness 会运行 loop
- 最终 transcript 有 user 和 assistant
- 事件里会补发 user message start/end

### 25.2 continue 主流程

```python
test_continue_runs_without_adding_user_message
```

验证：

- `continue_()` 不新增 user message
- provider 收到已有 transcript

### 25.3 transcript 快照

```python
test_messages_property_returns_immutable_snapshot
```

验证 `harness.messages` 返回 tuple 快照，外部不会误改内部 list。

### 25.4 listener

```python
test_subscribed_listeners_receive_events_and_can_unsubscribe
```

验证：

- listener 会收到事件
- unsubscribe 后不再收到事件

### 25.5 cancel

```python
test_cancel_requests_cancellation_for_current_run
```

验证：

- 收到第一个 message delta 后调用 `harness.cancel()`
- loop 产出取消错误
- transcript 只保留 user message，没有半截 assistant message

### 25.6 中断 tool call 修复

```python
test_cancelled_tool_run_repairs_transcript_before_next_prompt
```

验证：

- 工具执行开始时关闭 stream
- harness 会补一个 interrupted tool result
- 下一次 prompt 时 provider 收到修复后的 transcript

### 25.7 防止重叠运行

```python
test_harness_rejects_overlapping_prompt_runs
```

验证运行中不能再 `prompt()`，应该用 `steer()` 或 `follow_up()` 排队。

### 25.8 队列模式

```python
test_harness_drains_follow_up_messages_one_at_a_time_by_default
test_harness_can_drain_all_queued_messages_together
```

验证：

- 默认一次处理一个 follow-up
- `queue_mode="all"` 时一次处理所有 queued messages

## 26. Phase 4 的典型流程

### 26.1 prompt 流程

```text
harness.prompt("Hi")
        ↓
_ensure_not_running()
        ↓
_append_interrupted_tool_results()
        ↓
append UserMessage("Hi")
        ↓
_run(prompt_message=UserMessage("Hi"))
        ↓
run_agent_loop(...)
        ↓
yield AgentEvent
        ↓
notify listeners
        ↓
transcript grows
```

### 26.2 continue 流程

```text
harness.continue_()
        ↓
_ensure_not_running()
        ↓
_append_interrupted_tool_results()
        ↓
_run()
        ↓
run_agent_loop(...)
```

### 26.3 cancel 流程

```text
harness.cancel()
        ↓
current SimpleCancellationToken.cancel()
        ↓
run_agent_loop / provider / tool sees is_cancelled()
        ↓
emit recoverable error
        ↓
cleanup _current_signal and _running
```

## 27. 小白必须分清的几组概念

### 27.1 `run_agent_loop()` 不是 `AgentHarness`

`run_agent_loop()` 是循环函数。

`AgentHarness` 是状态对象。

loop 负责推进一轮轮 provider/tool 流程。

harness 负责持有 transcript、config、listeners、cancel token、queues。

### 27.2 `prompt()` 不是 `continue_()`

`prompt()` 会先追加新的 `UserMessage`。

`continue_()` 不追加用户消息，只基于已有 transcript 继续。

### 27.3 `messages` property 不是内部 list

`harness.messages` 返回 tuple 快照。

内部真正可变的是：

```python
self._messages
```

### 27.4 listener 不是主消费者

主消费者仍然是：

```python
async for event in harness.prompt(...):
    ...
```

listener 是旁路观察者。

### 27.5 cancel 是请求，不是强杀

`harness.cancel()` 只是设置 signal。

真正停止要等 loop/provider/tool 检查 signal。

## 28. Phase 4 里用到的 Python 语法和包

### 28.1 `deque`

适合队列。

```python
queue.append(message)
queue.popleft()
```

### 28.2 `dataclass` + `field(default_factory=list)`

用于配置对象。

```python
tools: list[AgentTool] = field(default_factory=list)
```

避免可变默认值共享。

### 28.3 `@property`

把方法变成属性访问：

```python
harness.messages
harness.is_running
harness.pending_message_count
```

### 28.4 闭包函数

`subscribe()` 里定义了内部函数：

```python
def unsubscribe() -> None:
    ...
```

这个函数记住了外层的 `listener`，所以之后能移除对应 listener。

### 28.5 `with suppress(ValueError)`

忽略指定异常。

用于让 unsubscribe 更安全。

### 28.6 `try ... finally`

`_run()` 用 finally 做清理：

```python
finally:
    if self._current_signal is signal:
        self._current_signal = None
    self._running = False
```

无论正常结束、报错、取消、stream 被关闭，都尽量恢复 harness 状态。

### 28.7 `isawaitable()`

判断 listener 返回值是否需要 await。

这让 listener 可以同步，也可以异步。

## 29. 运行测试

Phase 4 最相关测试：

```text
tests/test_agent_harness.py
```

运行：

```bash
uv run pytest tests/test_agent_harness.py
```

这组测试覆盖：

- prompt 追加 user message
- continue 不追加 user message
- messages 快照不可变
- replace messages
- clear queued messages
- pop latest follow-up
- listener subscribe/unsubscribe
- cancel 当前运行
- 中断 tool call 后修复 transcript
- 防止 overlapping prompt
- steering/follow-up 队列
- queue_mode
- tools 传给 loop/provider

## 30. 用一句话总结 Phase 4

Phase 4 的价值是：在纯 `run_agent_loop()` 之上增加一个可复用的状态型 agent brain，让调用者可以通过 `prompt()`、`continue_()`、`cancel()`、`subscribe()` 和 transcript snapshot 来使用 agent，而不用自己管理消息列表、取消 token 和事件观察者。

## 31. 我的问题与推荐回答

问题：为什么 `AgentHarness` 可以拥有 transcript，但仍然不应该知道 session 文件、项目 cwd、Rich/Textual 渲染或 slash command？

我的推荐回答：

因为 `AgentHarness` 的职责是 reusable agent brain：它管理 agent 运行所需的通用状态，比如 transcript、provider config、tools、取消和事件监听。session 文件路径、cwd、slash command、资源加载、UI 渲染都是 coding-agent 应用层问题。如果把这些放进 harness，`tau_agent` 就会和具体产品形态耦合，后续 CLI、TUI、测试、其他非 coding 场景都难以复用同一个 agent brain。
