# Provider Retry Events 学习笔记

对应架构文档：`dev-notes/architecture/provider-retries.md`

主要源码：

- `src/tau_ai/retry.py`
- `src/tau_ai/events.py`
- `src/tau_ai/openai_compatible.py`
- `src/tau_ai/anthropic.py`
- `src/tau_ai/openai_codex.py`
- `src/tau_agent/events.py`
- `src/tau_agent/loop.py`
- `src/tau_coding/rendering/transcript.py`
- `src/tau_coding/tui/adapter.py`
- `tests/test_tau_ai.py`
- `tests/test_agent_loop.py`
- `tests/test_rendering.py`
- `tests/test_tui_adapter.py`

前置阶段：

- Phase 2：`tau_ai` 已经有 provider streaming event
- Phase 3：`tau_agent` 已经把 provider events 映射成 agent events
- Phase 11：print renderer 可以显示 agent events
- Phase 12：TUI adapter 可以把 agent events 变成 transcript state
- Phase 18：provider config 开始保存 `max_retries` 和 `max_retry_delay_seconds`

## 1. 这份文档到底在做什么

`provider-retries.md` 不是编号 phase，但它紧跟 Phase 18。

它补上的是 provider 请求失败时的重试机制。

问题是：

```text
模型服务请求偶尔会因为 429、503、网络抖动等失败。
```

这些失败有些是 transient。

transient 的意思是：

```text
临时的，过一小会儿再试可能就好了。
```

所以 Tau 做了重试。

但关键边界是：

```text
谁决定要不要重试？
```

答案：

```text
tau_ai provider adapter 决定。
```

因为 HTTP status code、transport exception、响应 body 都是在 provider adapter 里可见。

`tau_agent` 不懂 HTTP。

它只把 provider retry progress 转成通用 agent event。

## 2. 事件流的大方向

重试事件流是：

```text
tau_ai provider
  -> ProviderRetryEvent
tau_agent run_agent_loop
  -> RetryEvent
tau_coding renderer/TUI
  -> 显示 “Retrying provider request ...”
```

也就是：

```text
ProviderRetryEvent 是 provider 层事件
RetryEvent 是 agent 层事件
```

这样 `tau_agent` 不需要知道 OpenAI、Anthropic、HTTPX 的细节。

## 3. ProviderRetryEvent

位置：

```text
src/tau_ai/events.py
```

源码：

```python
class ProviderRetryEvent(BaseModel):
    """The provider adapter is retrying a transient request failure."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["retry"] = "retry"
    attempt: int
    max_attempts: int
    delay_seconds: float
    message: str
    data: dict[str, JSONValue] | None = None
```

字段解释：

```text
attempt        下一次要进行第几次请求
max_attempts   最多请求几次
delay_seconds  这次 retry 前等待多久
message        给用户看的说明
data           给诊断用的结构化数据
```

例如：

```text
Retrying provider request 2/3 after HTTP 503.
```

这里 `2/3` 表示：

```text
下一次是第 2 次请求，最多 3 次请求。
```

## 4. 为什么 data 是结构化的

`data` 类型是：

```python
dict[str, JSONValue] | None
```

它可以保存：

```python
{"status_code": 503, "body": "overloaded"}
```

这比只写字符串更适合诊断。

UI 可以只显示 message。

日志或测试可以检查 data。

这就是：

```text
人读 message，程序读 data。
```

## 5. retry.py 是共享 helper

位置：

```text
src/tau_ai/retry.py
```

它有三个核心函数：

```python
retry_delay_seconds(...)
provider_retry_event(...)
wait_for_retry(...)
```

OpenAI-compatible、Anthropic、OpenAI Codex provider 都可以复用这些 helper。

这样重试消息和 backoff 行为保持一致。

## 6. retry_delay_seconds()

源码：

```python
RETRY_BASE_DELAY_SECONDS = 0.25

def retry_delay_seconds(attempt: int, *, max_delay_seconds: float) -> float:
    """Return an exponential retry delay capped by provider config."""
    if max_delay_seconds <= 0:
        return 0.0
    base_delay = min(RETRY_BASE_DELAY_SECONDS, max_delay_seconds)
    return float(min(max_delay_seconds, base_delay * (2**attempt)))
```

这是指数退避。

exponential backoff 的意思是：

```text
每次失败后，等待时间逐渐变长。
```

例如 `max_delay_seconds=10`：

```text
attempt=0 -> 0.25s
attempt=1 -> 0.5s
attempt=2 -> 1.0s
attempt=3 -> 2.0s
```

但不会超过 max delay。

如果 `max_delay_seconds <= 0`，就不等待。

测试里为了跑得快，经常设置：

```python
max_retry_delay_seconds=0
```

## 7. 这里的 attempt 为什么从 0 开始

provider 内部代码：

```python
attempt = 0
```

第一次请求失败时，`attempt` 还是 0。

如果要 retry，下一次请求是第 2 次。

所以 `provider_retry_event()` 里：

```python
next_attempt = attempt + 2
max_attempts = max_retries + 1
```

如果：

```python
max_retries = 2
```

最多请求次数是：

```text
1 次初始请求 + 2 次重试 = 3 次
```

所以：

```python
max_attempts = max_retries + 1
```

## 8. provider_retry_event()

源码：

```python
def provider_retry_event(
    *,
    attempt: int,
    max_retries: int,
    delay_seconds: float,
    reason: str,
    data: dict[str, JSONValue] | None = None,
) -> ProviderRetryEvent:
    """Build a provider-neutral retry progress event."""
    next_attempt = attempt + 2
    max_attempts = max_retries + 1
    delay_suffix = f" in {delay_seconds:g}s" if delay_seconds else ""
    return ProviderRetryEvent(
        attempt=next_attempt,
        max_attempts=max_attempts,
        delay_seconds=delay_seconds,
        message=(
            f"Retrying provider request {next_attempt}/{max_attempts} "
            f"after {reason}{delay_suffix}."
        ),
        data=data,
    )
```

如果 delay 是 0：

```text
Retrying provider request 2/2 after HTTP 500.
```

如果 delay 是 0.25：

```text
Retrying provider request 2/3 after HTTP 503 in 0.25s.
```

`{delay_seconds:g}` 是 Python 格式化。

它会用比较紧凑的数字形式。

例如：

```text
1.0 -> 1
0.5 -> 0.5
```

## 9. wait_for_retry()

源码：

```python
RETRY_POLL_SECONDS = 0.05

async def wait_for_retry(
    delay_seconds: float,
    *,
    signal: CancellationToken | None,
) -> bool:
    """Sleep before a retry while allowing cancellation to interrupt backoff."""
    if delay_seconds <= 0:
        return signal is None or not signal.is_cancelled()

    remaining = delay_seconds
    while remaining > 0:
        if signal is not None and signal.is_cancelled():
            return False
        step = min(RETRY_POLL_SECONDS, remaining)
        await sleep(step)
        remaining -= step
    return signal is None or not signal.is_cancelled()
```

它不是简单：

```python
await sleep(delay_seconds)
```

而是每 0.05 秒检查一次取消信号。

为什么？

如果用户在 TUI 里按 Escape 取消，而 retry backoff 是 5 秒，用户不应该等满 5 秒。

所以它分小步 sleep。

如果发现：

```python
signal.is_cancelled()
```

就返回 `False`。

provider 收到 `False` 后停止 retry。

## 10. OpenAI-compatible provider 如何 retry

位置：

```text
src/tau_ai/openai_compatible.py
```

核心逻辑：

```python
attempt = 0
while True:
    emitted_content = False
    try:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            if response.status_code >= 400:
                body = await response.aread()
                if self._should_retry(attempt, status_code=response.status_code):
                    delay = retry_delay_seconds(...)
                    yield provider_retry_event(...)
                    attempt += 1
                    if not await wait_for_retry(delay, signal=signal):
                        return
                    continue
                yield ProviderErrorEvent(...)
                return
            ...
```

流程：

1. 发请求。
2. 如果 status code >= 400，读取 body。
3. 判断是否应该 retry。
4. 如果应该 retry，先 yield `ProviderRetryEvent`。
5. 等待 backoff，同时允许取消。
6. `continue` 回到 while 开头重新发请求。
7. 如果不应该 retry，yield `ProviderErrorEvent` 并结束。

## 11. _should_retry()

OpenAI-compatible：

```python
def _should_retry(self, attempt: int, *, status_code: int | None = None) -> bool:
    if attempt >= self._config.max_retries:
        return False
    return status_code is None or _is_transient_status(status_code)
```

如果已经达到最大 retry 次数，不再重试。

`status_code is None` 通常表示 transport error，没有 HTTP status。

这种也可以 retry，前提是还没有输出部分内容。

transient status：

```python
def _is_transient_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429} or status_code >= 500
```

包括：

- 408 Request Timeout
- 409 Conflict
- 425 Too Early
- 429 Too Many Requests
- 5xx server errors

## 12. 为什么“已经输出部分内容后”不 retry

在 provider 代码里会跟踪：

```python
emitted_content = False
```

如果 stream 已经输出了一部分 assistant content，然后连接断了，再自动 retry 会有风险：

```text
用户可能看到重复内容；
工具调用可能重复；
上下文状态可能混乱。
```

所以 transport error 的 retry 通常只在：

```text
还没有 emitted content
```

时进行。

这是一条很重要的安全边界。

## 13. run_agent_loop 如何转发 retry

位置：

```text
src/tau_agent/loop.py
```

源码：

```python
elif isinstance(provider_event, ProviderRetryEvent):
    yield RetryEvent(
        attempt=provider_event.attempt,
        max_attempts=provider_event.max_attempts,
        delay_seconds=provider_event.delay_seconds,
        message=provider_event.message,
        data=provider_event.data,
    )
```

这里没有判断 status code。

没有判断 429/503。

没有决定要不要 retry。

它只是把 provider event 转成 agent event。

这就是架构文档说的：

```text
tau_agent does not decide whether an HTTP response is retryable.
```

## 14. RetryEvent

位置：

```text
src/tau_agent/events.py
```

它是 provider-neutral agent event。

renderer/TUI 都消费它。

好处是：

```text
TUI 不需要知道这个 retry 来自 OpenAI 还是 Anthropic。
```

它只显示：

```text
… Retrying provider request 2/3 after HTTP 503.
```

## 15. TranscriptRenderer 如何显示 retry

位置：

```text
src/tau_coding/rendering/transcript.py
```

源码：

```python
if isinstance(event, RetryEvent):
    self._ensure_assistant_newline()
    self._console.print(Text(f"… {event.message}", style="bright_black"))
    return
```

它把 retry 显示成灰色状态行。

测试：

```python
assert "… Retrying provider request 2/3 after HTTP 503." in captured.err
```

注意 `FinalTextRenderer` 会忽略 retry progress。

因为 final text mode 只关心最终答案或最终错误。

## 16. TUI adapter 如何显示 retry

位置：

```text
src/tau_coding/tui/adapter.py
```

它把 `RetryEvent` 变成 status item。

测试里：

```python
assert state.items == [
    ("status", "… Retrying provider request 2/3 after HTTP 503.")
]
```

这说明 retry 是用户可见的轻量进度，而不是沉默等待。

## 17. tests/test_tau_ai.py 里重试测试

典型测试：

```python
async def test_openai_compatible_provider_retries_transient_status() -> None:
```

它用：

```python
httpx.MockTransport(handler)
```

模拟 HTTP。

第一次返回：

```python
httpx.Response(500, text="try again")
```

第二次返回成功 SSE。

然后断言：

```python
assert len(requests) == 2
assert isinstance(events[0], ProviderRetryEvent)
assert events[0].attempt == 2
assert events[0].max_attempts == 2
assert events[0].data == {"status_code": 500, "body": "try again"}
```

这说明：

```text
第一次失败 -> emit retry event -> 第二次成功
```

## 18. cancellation stops retry backoff

测试：

```python
async def test_openai_compatible_provider_cancellation_stops_retry_backoff() -> None:
```

流程：

1. provider 收到 503。
2. emit `ProviderRetryEvent`。
3. 测试里立刻 `signal.cancel()`。
4. `wait_for_retry()` 检测到 cancel。
5. provider 停止，不再发第二次请求。

断言：

```python
assert len(requests) == 1
assert [event.type for event in events] == ["retry"]
```

这验证了 Escape/TUI 取消不会卡在 retry sleep 里。

## 19. non-transient status 不 retry

测试：

```python
test_openai_compatible_provider_does_not_retry_non_transient_status
```

例如 400 Bad Request。

400 一般不是临时故障，而是请求本身有问题。

所以不 retry。

直接返回 provider error。

这避免了无意义的重复请求。

## 20. 和 Phase 18 provider config 的连接

Phase 18 的 provider config 有：

```python
max_retries: int
max_retry_delay_seconds: float
```

这些值会进入 runtime provider：

```python
OpenAICompatibleConfig(
    max_retries=provider.max_retries,
    max_retry_delay_seconds=provider.max_retry_delay_seconds,
)
```

CLI setup 也支持：

```text
--max-retries
--max-retry-delay-seconds
```

所以用户可以配置 retry 行为。

## 21. Python 小白应该掌握的语法点

### 21.1 async sleep

```python
await sleep(step)
```

这是异步 sleep，不会阻塞整个事件循环。

### 21.2 while True + continue

provider retry 用：

```python
while True:
    ...
    if should_retry:
        ...
        continue
```

`continue` 会回到 while 开头，重新发请求。

### 21.3 yield event

provider 是 async generator。

```python
yield provider_retry_event(...)
```

表示把事件流式交给上层。

### 21.4 2**attempt

```python
base_delay * (2**attempt)
```

`**` 是乘方。

`2**0 = 1`

`2**1 = 2`

`2**2 = 4`

这就是指数退避的来源。

## 22. 你读源码时的推荐顺序

建议这样读：

1. `tau_ai/events.py` 的 `ProviderRetryEvent`
2. `tau_ai/retry.py` 的 `retry_delay_seconds()`
3. `tau_ai/retry.py` 的 `provider_retry_event()`
4. `tau_ai/retry.py` 的 `wait_for_retry()`
5. `tau_ai/openai_compatible.py` 里 status code retry 分支
6. `tau_agent/loop.py` 里 `ProviderRetryEvent -> RetryEvent`
7. `tau_coding/rendering/transcript.py` 里 retry 输出
8. `tau_coding/tui/adapter.py` 里 retry 状态 item
9. `tests/test_tau_ai.py` 的 retry 测试
10. `tests/test_agent_loop.py` 的 event mapping 测试

## 23. Provider Retry Events 用一句话总结

Provider retry 的价值是：让 OpenAI-compatible、Anthropic、OpenAI Codex 等 provider adapter 在遇到临时 HTTP/transport 失败时自己判断是否重试，并通过 `ProviderRetryEvent` 把进度报告给上层；`tau_agent` 只把它转成 provider-neutral 的 `RetryEvent`，renderers 和 TUI 再以轻量状态展示，从而既保留 provider-specific 诊断，又不污染可复用 agent loop。

## 24. 我的问题与推荐回答

问题：为什么 Tau 不在 `tau_agent.run_agent_loop()` 里统一判断 429、503 这些状态码并重试，而要放在 `tau_ai` provider adapter 里？

我的推荐回答：

因为 HTTP status code、响应 body、transport exception、是否已经产生部分 stream 内容，这些信息都只在 provider adapter 里完整可见。`tau_agent` 是可复用的 agent loop，它不应该知道 OpenAI、Anthropic 或 HTTPX 的细节。如果把 retry 判断放进 `tau_agent`，就会把 provider-specific 网络语义污染到核心 agent 层。现在的设计是 provider adapter 负责判断和等待重试，发出 `ProviderRetryEvent`；`tau_agent` 只转发为通用 `RetryEvent`，让 UI 能显示进度。
