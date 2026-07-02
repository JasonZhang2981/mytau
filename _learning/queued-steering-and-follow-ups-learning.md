# Queued Steering and Follow-ups 学习笔记

对应架构文档：`dev-notes/architecture/queued-steering-follow-ups.md`

对应源码：

- `src/tau_agent/harness.py`
- `src/tau_agent/loop.py`
- `src/tau_agent/events.py`
- `src/tau_coding/session.py`
- `src/tau_coding/tui/state.py`
- `src/tau_coding/tui/adapter.py`
- `src/tau_coding/tui/app.py`
- `src/tau_coding/tui/config.py`
- `tests/test_agent_loop.py`
- `tests/test_agent_harness.py`
- `tests/test_coding_session.py`
- `tests/test_tui_adapter.py`
- `tests/test_tui_app.py`

## 1. 这一阶段到底在做什么

这一篇不是编号 Phase，但它在架构顺序里紧跟 Phase 20.4。

它给 Tau 增加 Pi-style message queueing。

也就是：

```text
当 agent 正在运行时，用户还可以继续输入一些消息。
这些消息不会打断当前运行，而是进入队列，等合适时机再注入 transcript。
```

具体分两种队列：

- steering
- follow-up

## 2. 为什么需要队列

没有队列时，如果 agent 正在跑，用户又输入一句话，会有两个坏选择：

```text
1. 直接启动第二个 prompt，导致同一个 transcript 被两个运行同时修改
2. 拒绝用户输入，让用户只能等
```

第一个会破坏状态一致性。

第二个体验不好。

Queued Steering and Follow-ups 选择第三条路：

```text
当前 run 继续跑
新输入先排队
等 loop 到安全边界时再注入
```

## 3. steering 和 follow-up 的区别

### 3.1 steering

steering 是“调整当前方向”。

它会在：

```text
当前 assistant turn 和 tool batch 结束后
```

尽快注入。

比如 agent 正在读文件，你突然补一句：

```text
顺便总结 README
```

它应该在工具批次完成后马上作为新的 user message 进入下一次 provider call。

### 3.2 follow-up

follow-up 是“等当前回答结束后再问”。

它只在：

```text
当前 run 本来要停止时
```

注入。

比如 agent 正在回答，你输入：

```text
之后再帮我加测试
```

它不应该马上改变当前回答方向，而是等当前回答自然结束后继续下一轮。

## 4. 队列所有权在 `tau_agent`

架构文档强调：

```text
Queue ownership lives in tau_agent
```

因为队列是 agent brain 的运行时语义。

它不应该属于 Textual，也不应该属于 CLI。

`src/tau_agent/harness.py` 里：

```python
self._steering_queue: deque[AgentMessage] = deque()
self._follow_up_queue: deque[AgentMessage] = deque()
```

这两个 queue 由 `AgentHarness` 持有。

## 5. `deque` 是什么

`deque` 来自 Python 标准库：

```python
from collections import deque
```

它是 double-ended queue。

你可以从两头高效添加和移除元素。

这里主要用：

```python
append()
popleft()
pop()
clear()
```

为什么不用 list？

因为 queue 经常从左边取第一个：

```python
queue.popleft()
```

`deque.popleft()` 比 `list.pop(0)` 更适合队列。

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

这是一个队列快照。

注意它用 tuple，而不是直接暴露内部 deque。

这样外部只能看，不会偷偷修改 harness 内部队列。

## 7. `QueueMode`

源码：

```python
QueueMode = Literal["one_at_a_time", "all"]
```

队列有两种 drain 模式：

- `one_at_a_time`：一次只取一条
- `all`：一次取完

默认：

```python
queue_mode: QueueMode = "one_at_a_time"
```

测试里验证了两种模式。

## 8. `is_running`

`AgentHarness` 有：

```python
@property
def is_running(self) -> bool:
    return self._running
```

它告诉上层：

```text
当前 harness 是否有活跃 prompt/continue run
```

这是 CodingSession 和 TUI 决定“直接运行还是入队”的基础。

## 9. 队列 API

`AgentHarness` 暴露：

```python
steer(content)
follow_up(content)
clear_queues()
pop_latest_follow_up()
queue_update_event()
queued_messages
pending_message_count
has_queued_messages()
```

这套 API 都在 reusable harness 层。

## 10. `steer()`

源码：

```python
def steer(self, content: str) -> QueueUpdateEvent:
    return self.steer_message(UserMessage(content=content))

def steer_message(self, message: AgentMessage) -> QueueUpdateEvent:
    self._steering_queue.append(message)
    return self.queue_update_event()
```

它把字符串包装成 `UserMessage`，放进 steering queue。

然后返回一个 `QueueUpdateEvent`。

## 11. `follow_up()`

源码：

```python
def follow_up(self, content: str) -> QueueUpdateEvent:
    return self.follow_up_message(UserMessage(content=content))

def follow_up_message(self, message: AgentMessage) -> QueueUpdateEvent:
    self._follow_up_queue.append(message)
    return self.queue_update_event()
```

和 steering 类似，只是进入 follow-up queue。

## 12. `QueueUpdateEvent`

`src/tau_agent/events.py`：

```python
class QueueUpdateEvent(BaseModel):
    type: Literal["queue_update"] = "queue_update"
    steering: tuple[str, ...] = ()
    follow_up: tuple[str, ...] = ()
```

这是 portable agent event。

它只暴露文本，不暴露内部 `UserMessage` 对象。

前端用它更新队列显示。

## 13. 为什么入队后返回 event

当用户在 TUI 里按 Enter 入队时，界面需要立刻知道：

```text
现在有几条 queued steering？
现在有几条 queued follow-up？
```

所以 `steer()` / `follow_up()` 返回 `QueueUpdateEvent`。

TUI adapter 收到它后更新状态。

## 14. `clear_queues()`

源码：

```python
def clear_queues(self) -> QueuedMessages:
    snapshot = self.queued_messages
    self._steering_queue.clear()
    self._follow_up_queue.clear()
    return snapshot
```

清空前先拿快照。

所以调用方可以知道刚刚清掉了什么。

## 15. `pop_latest_follow_up()`

源码：

```python
def pop_latest_follow_up(self) -> AgentMessage | None:
    if not self._follow_up_queue:
        return None
    return self._follow_up_queue.pop()
```

它从 follow-up queue 右侧弹出最新一条。

这个是给 TUI 的 Up 键编辑用的。

用户排了几条 follow-up 后，按 Up 可以把最新一条拿回输入框修改。

## 16. 为什么只 pop follow-up

因为 follow-up 更像“之后要说的话”，适合拿回来编辑。

steering 是“正在影响当前方向”的消息，语义上更像马上排进当前运行，不提供同样的编辑入口。

## 17. 防止重叠运行

`AgentHarness.prompt()` 开头：

```python
self._ensure_not_running()
```

如果正在运行：

```python
raise RuntimeError(
    "AgentHarness is already running; use steer() or follow_up() to queue messages."
)
```

这非常关键。

同一个 transcript 不允许两个 active runs 同时修改。

## 18. `run_agent_loop()` 的队列回调

`src/tau_agent/loop.py` 里，`run_agent_loop()` 新增参数：

```python
get_steering_messages: Callable[[], Sequence[AgentMessage]] | None = None
get_follow_up_messages: Callable[[], Sequence[AgentMessage]] | None = None
get_queue_update: Callable[[], QueueUpdateEvent] | None = None
```

注意：

```text
loop 不直接知道 AgentHarness
loop 只知道有几个 callback
```

这保持了 pure loop 的可测试性。

## 19. `_drain_queued_messages()`

源码：

```python
def _drain_queued_messages(messages, get_messages, get_queue_update):
    if get_messages is None:
        return ()
    queued_messages = tuple(get_messages())
    if not queued_messages:
        return ()

    messages.extend(queued_messages)
    events = []
    for message in queued_messages:
        events.append(MessageStartEvent(message_role=message.role))
        events.append(MessageEndEvent(message=message))
    if get_queue_update is not None:
        events.append(get_queue_update())
    return tuple(events)
```

这段是核心。

它做三件事：

```text
1. 从队列回调拿 queued messages
2. 把它们 append 到同一个 transcript messages list
3. 为每条 queued message 生成普通 message_start/message_end event
4. 最后生成 queue_update event
```

所以队列消息一旦注入，就不再特殊。

它就是普通 user message。

## 20. steering 的注入时机

`run_agent_loop()` 在两处 drain steering。

### 20.1 assistant 没有 tool calls 时

assistant 回答结束后：

```python
queue_events = _drain_queued_messages(... get_steering_messages ...)
if queue_events:
    ...
    turn += 1
    continue
```

### 20.2 tool batch 结束后

工具执行完后：

```python
yield TurnEndEvent(turn=turn)
for queue_event in _drain_queued_messages(... get_steering_messages ...):
    yield queue_event
turn += 1
```

这对应文档：

```text
steering messages, injected after the current assistant turn and any tool batch
```

## 21. follow-up 的注入时机

follow-up 只在当前 run 将要停止时 drain。

也就是 assistant 没有 tool calls，并且 steering 队列也为空后：

```python
queue_events = _drain_queued_messages(... get_follow_up_messages ...)
if queue_events:
    ...
    turn += 1
    continue
break
```

所以 follow-up 不会打断当前工具/方向。

它是“自然结束后继续”。

## 22. CodingSession 的边界

`src/tau_coding/session.py` 里：

```python
StreamingBehavior = Literal["steer", "follow_up"]
```

`CodingSession.prompt()` 支持：

```python
session.prompt(text, streaming_behavior="steer")
session.prompt(text, streaming_behavior="follow_up")
```

如果 harness 正在运行：

```python
if self._harness.is_running:
    if streaming_behavior == "steer":
        yield self._harness.steer(expanded_content)
        return
    if streaming_behavior == "follow_up":
        yield self._harness.follow_up(expanded_content)
        return
    raise RuntimeError(...)
```

## 23. queued message 会先 expand prompt

`CodingSession.prompt()` 先做：

```python
expanded_content = self.expand_prompt_text(content)
```

再判断是否入队。

所以如果用户正在运行中输入：

```text
/skill:testing add tests
```

并以 steering/follow-up 入队，队列里保存的是展开后的 skill block。

## 24. 入队时不持久化

测试 `test_prompt_queues_steering_while_session_is_running` 验证：

```text
队列入队后、provider release 前，storage 里只有原始 Hello user message。
Queued steering 还没有被写入 JSONL。
```

为什么？

因为队列消息还没有真正成为 transcript 的一部分。

只有 loop drain 队列、把它 append 到 messages 后，CodingSession 才会持久化它。

这避免未执行的 queued message 污染 durable session history。

## 25. TUI keybindings

默认按键：

```text
Enter      while running -> steering
Alt-Enter  while running -> follow-up
Up         empty prompt while running -> edit latest follow-up
```

`src/tau_coding/tui/config.py` 里：

```python
queue_follow_up: str = "alt+enter"
```

## 26. TUI submit 行为

`src/tau_coding/tui/app.py`：

```python
async def action_submit_prompt(self):
    await self._submit_prompt_from_editor(streaming_behavior="steer")

async def action_submit_follow_up(self):
    await self._submit_prompt_from_editor(streaming_behavior="follow_up")
```

普通 Enter 默认传入 `steer`。

Alt-Enter 传入 `follow_up`。

如果 session 正在运行，`_submit_prompt_from_editor()` 会调用 `_queue_prompt()`。

## 27. `_queue_prompt()`

源码：

```python
async def _queue_prompt(self, text, *, streaming_behavior):
    try:
        async for event in self.session.prompt(text, streaming_behavior=streaming_behavior):
            self.adapter.apply(event)
    except Exception as exc:
        self._notify(f"Could not queue message: {exc}", severity="error")
        return
    self._refresh()
```

这里 session.prompt 只会 yield 一个 `QueueUpdateEvent`。

adapter 应用后，TUI state 更新队列展示。

## 28. TUI adapter

`src/tau_coding/tui/adapter.py`：

```python
if isinstance(event, QueueUpdateEvent):
    self.state.update_queue(steering=event.steering, follow_up=event.follow_up)
    return
```

它只负责把 event 写入 `TuiState`。

## 29. `TuiState`

`src/tau_coding/tui/state.py`：

```python
queued_steering: tuple[str, ...] = ()
queued_follow_up: tuple[str, ...] = ()

def update_queue(...):
    self.queued_steering = steering
    self.queued_follow_up = follow_up

@property
def queued_message_count(self) -> int:
    return len(self.queued_steering) + len(self.queued_follow_up)
```

队列 UI 状态是纯展示状态。

真实队列仍在 AgentHarness。

## 30. 队列展示

`_render_queued_messages()`：

```python
for message in state.queued_steering:
    row = Text("↪ steering · queued: ", ...)
    row.append(_queued_message_preview(message), ...)

for message in state.queued_follow_up:
    row = Text("↳ follow-up · queued: ", ...)
    row.append(_queued_message_preview(message), ...)
```

显示类似：

```text
↪ steering · queued: adjust course
↳ follow-up · queued: after this
```

## 31. 为什么只显示第一行

`_queued_message_preview()`：

```python
lines = message.splitlines()
return lines[0] if lines else ""
```

如果队列消息是多行，只显示第一行。

这是为了队列条保持紧凑，不挤压主 transcript。

## 32. Up 编辑最新 follow-up

`action_edit_queued_follow_up()`：

```python
if not self.state.running:
    return False
if prompt.text.strip():
    return False
message = pop_follow_up()
if not message:
    return False
prompt.text = message
...
```

条件：

- agent 正在运行
- prompt 当前为空
- session 支持 `pop_latest_follow_up_message`
- follow-up queue 非空

成功后，最新 follow-up 回到输入框。

## 33. compaction 会避开队列竞争

TUI 里有：

```python
return self.state.running or is_session_running or is_worker_active or self.state.queued_message_count > 0
```

如果当前有 active run 或 queued messages，TUI 会阻止 `/compact`。

原因是 compaction 会改 active context。

如果同时有 queued message 等待注入，容易造成上下文竞争。

## 34. 测试如何覆盖这一阶段

### 34.1 `tests/test_agent_loop.py`

验证：

- steering 在 tool batch 后注入
- follow-up 只在 run 将停止时注入
- queued message 生成普通 user message events

### 34.2 `tests/test_agent_harness.py`

验证：

- clear queues
- pop latest follow-up
- overlapping prompt 被拒绝
- steering 可替代重叠 prompt
- follow-up 默认一次 drain 一条
- queue mode `all` 一次 drain 所有

### 34.3 `tests/test_coding_session.py`

验证：

- session running 时直接 prompt 会报错
- `streaming_behavior="steer"` 会入队
- 入队时不持久化 queued message
- drain 后 queued message 进入 transcript 并写入 JSONL

### 34.4 `tests/test_tui_adapter.py`

验证 `QueueUpdateEvent` 会更新 TUI state。

### 34.5 `tests/test_tui_app.py`

验证：

- running 时 Enter 入 steering queue
- Alt-Enter 入 follow-up queue
- 队列 UI 显示第一行 preview
- Up 编辑最新 follow-up
- 有 queued message 时阻止 compaction

## 35. 小白必须分清的几组概念

### 35.1 queue 不是 transcript

入队只是暂存。

只有 drain 后 append 到 `messages`，才变成 transcript。

### 35.2 steering 不是 follow-up

steering 尽快改变方向。

follow-up 等当前回答结束后继续。

### 35.3 queue owner 是 AgentHarness

TUI 只负责按键和展示。

CodingSession 只负责 prompt expansion 和持久化边界。

Provider 完全不知道 queue。

### 35.4 overlapping prompt 被拒绝是故意的

同一个 transcript 不能被两个 active agent loop 同时修改。

队列机制就是为了解决这个问题。

### 35.5 QueueUpdateEvent 是 UI 同步事件

它不代表 queued message 已经执行。

它只表示当前队列状态变了。

## 36. 运行测试

Queued Steering and Follow-ups 相关测试：

```bash
uv run pytest tests/test_agent_loop.py tests/test_agent_harness.py tests/test_coding_session.py tests/test_tui_adapter.py tests/test_tui_app.py
```

## 37. 用一句话总结

Queued Steering and Follow-ups 的价值是：让用户在 agent 正在运行时继续输入，并用 steering/follow-up 两种队列在安全时机注入 transcript，同时保持 `tau_agent` 管队列、`tau_coding` 管展开和持久化、Textual 只管按键与展示的架构边界。

## 38. 我的问题与推荐回答

问题：为什么 queued message 入队时不立刻写入 JSONL session，而要等 run_agent_loop 真正 drain 后才持久化？

我的推荐回答：

因为入队只表示“用户希望之后注入这条消息”，它还不是已经进入模型上下文的 transcript。如果立刻写入 JSONL，之后用户又取消、编辑 follow-up，或者 run 在注入前结束异常，session 历史就会记录一条没有真正执行过的消息。当前设计让 AgentHarness 先持有队列，只有 run_agent_loop 在安全边界把 queued message append 到 `messages` 后，CodingSession 才按正常 message persistence 写入 JSONL，这样 durable session history 和真实 transcript 保持一致。
