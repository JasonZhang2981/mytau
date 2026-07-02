# Pre-extension Hardening Summary 学习笔记

对应架构文档：`dev-notes/architecture/pre-extension-hardening.md`

对应源码范围：

- `src/tau_ai/`
- `src/tau_agent/events.py`
- `src/tau_agent/loop.py`
- `src/tau_agent/harness.py`
- `src/tau_agent/session/`
- `src/tau_coding/context_window.py`
- `src/tau_coding/provider_config.py`
- `src/tau_coding/provider_runtime.py`
- `src/tau_coding/credentials.py`
- `src/tau_coding/session.py`
- `src/tau_coding/session_export.py`
- `src/tau_coding/skills.py`
- `src/tau_coding/system_prompt.py`
- `src/tau_coding/tui/`

对应测试：

- `tests/test_agent_harness.py`
- `tests/test_agent_loop.py`
- `tests/test_coding_session.py`
- `tests/test_context_window.py`
- `tests/test_provider_config.py`
- `tests/test_rendering.py`
- `tests/test_session_export.py`
- `tests/test_skills.py`
- `tests/test_tau_ai.py`
- `tests/test_tui_adapter.py`
- `tests/test_tui_app.py`
- `tests/test_tui_config.py`

## 1. 这一篇到底在做什么

`Pre-extension Hardening Summary` 不是一个普通功能阶段。

它是 Phase 21 extensions 之前的一次阶段性总结。

意思是：

```text
在继续做扩展系统之前，先把已有 agent/provider/session/TUI 能力加固到更可靠的状态。
```

Phase 21 被明确延后：

```text
Phase 21 remains intentionally deferred.
```

所以这篇不是讲“扩展系统已经完成”，而是讲：

```text
进入扩展系统之前，Tau 的基础运行时已经补齐了哪些生产化能力。
```

## 2. 为什么要有 hardening 阶段

项目做功能时，很容易只往前堆：

- 新 provider
- 新 TUI
- 新 session
- 新 command
- 新 skill

但如果基础层还不稳，继续加扩展只会让复杂度失控。

所以 hardening 阶段的价值是：

```text
不是扩大功能面，而是收紧边界、补齐测试、统一事件、明确失败行为。
```

这对 coding agent 很重要。

因为 agent runtime 有很多并发和状态边界：

- provider streaming 可能失败
- tool call 可能中断
- TUI 用户可能一边运行一边输入
- session 可能 resume/branch/compact
- provider credentials 可能来自不同地方
- skills 可能来自用户目录或项目目录

## 3. 这篇总结了哪几类加固

架构文档分成四块：

```text
1. Agent And Provider Runtime
2. Context, Skills, And Sessions
3. TUI Behavior
4. Architecture Boundary
```

我们按这个顺序学习。

## 4. Agent And Provider Runtime

这一块说 Tau 现在有三类 provider-neutral progress events：

- `RetryEvent`
- `ThinkingDeltaEvent`
- `QueueUpdateEvent`

它们都定义在：

```text
src/tau_agent/events.py
```

## 5. 什么是 provider-neutral event

provider-neutral 的意思是：

```text
事件不暴露具体 provider 的内部格式。
```

比如 OpenAI、Anthropic、Codex subscription 的 HTTP payload 都不一样。

但 Tau 前端不应该关心这些差异。

前端只应该看到统一事件：

```text
retry
thinking_delta
queue_update
message_delta
message_end
tool_execution_start
...
```

这样 TUI、print renderer、JSON renderer、未来自定义前端都能复用同一套事件协议。

## 6. `RetryEvent`

`RetryEvent` 表示 provider 正在重试。

它让前端可以显示：

```text
Retrying provider request 2/3 after HTTP 503.
```

但不要求前端理解：

- httpx exception
- status code 分类
- provider-specific error body
- backoff 算法

这些属于 `tau_ai` provider adapter。

## 7. retry helper

retry 相关逻辑在：

```text
src/tau_ai/retry.py
```

它负责：

- 计算 retry delay
- 生成 provider retry event
- 等待下一次 retry

然后 OpenAI-compatible、Anthropic、OpenAI Codex provider 分别接入。

## 8. 为什么 retry 事件重要

如果没有 retry event，用户只会看到：

```text
卡住了
```

或者最终失败。

有 retry event 后，用户可以看到：

```text
不是没反应，是 provider 临时失败，Tau 正在重试。
```

这就是 production hardening。

## 9. `ThinkingDeltaEvent`

`ThinkingDeltaEvent` 表示 provider 流出了 reasoning/thinking 文本片段。

它不会作为 durable assistant message 保存。

原因是：

```text
thinking token 是显示层/调试层信息，不是普通 assistant answer。
```

TUI 默认隐藏 thinking tokens。

用户可以用：

```text
Ctrl+T
```

显示或隐藏。

## 10. `QueueUpdateEvent`

`QueueUpdateEvent` 表示当前 queued steering/follow-up 状态。

它用于：

```text
TUI 在 prompt 上方显示还有哪些 queued messages。
```

它不表示消息已经执行。

Queued message 只有被 `run_agent_loop()` drain 并注入 transcript 后，才成为 durable session message。

## 11. Credentials 加固

架构文档说：

```text
stored Tau credentials from ~/.tau/credentials.json take precedence over environment-variable fallbacks
```

对应代码在：

- `src/tau_coding/credentials.py`
- `src/tau_coding/provider_config.py`
- `src/tau_coding/provider_runtime.py`

优先级是：

```text
1. ~/.tau/credentials.json 里的 stored credential
2. provider.api_key_env 指向的环境变量
```

## 12. 为什么 credentials 不放 providers.json

`providers.json` 保存 provider 元数据，例如：

- name
- base_url
- models
- default_model
- timeout
- retry policy

`credentials.json` 保存敏感凭据，例如：

- API key
- OAuth token

分开有两个好处：

```text
配置可以更容易查看和备份
敏感凭据可以独立保护权限
```

## 13. Context, Skills, And Sessions

这一块总结了 Phase 20.1、20.3、20.4 的成果。

包括：

- structured context accounting
- skill index and manual skill invocation
- session export

## 14. `ContextUsageEstimate`

`src/tau_coding/context_window.py` 定义：

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

它把原来的“一个估算数字”升级为：

```text
总数 + system/messages/tools 分项
```

这让 `/session` 和 TUI 更容易解释上下文为什么变大。

## 15. 事件驱动的 TUI refresh

架构文档说：

```text
The TUI refreshes from the event stream
```

意思是：

```text
TUI 不自己猜 transcript 什么时候变了
而是根据 AgentEvent 更新 TuiState
```

重要链路：

```text
CodingSession emits AgentEvent values
        ↓
TuiEventAdapter updates TuiState
        ↓
Textual widgets render transcript, status, and controls
```

这是 Tau TUI 的核心架构边界。

## 16. Skill 加固

skills 有两条路径：

```text
自动路径：system prompt 列出 skill name/description/location，模型用 read 工具读取
手动路径：/skill:<name> [request] 展开完整 skill markdown
```

这两条路径共同解决：

```text
模型如何可靠获得技能说明？
```

自动路径避免把所有 skill 全文塞进 system prompt。

手动路径让用户可以强制使用某个 skill。

## 17. Session export 加固

`tau export` 和 `/export` 可以导出：

- HTML
- JSONL

HTML 是 self-contained。

它保留：

- session tree
- active leaf
- active path
- storage-order entry details
- messages
- tool calls
- tool results
- compactions
- labels
- model changes
- thinking changes
- custom entries

这让 session 不再只能在 TUI 里看。

## 18. TUI Behavior

架构文档列了一批 TUI hardening：

- responsive sidebar
- context-size refresh
- transcript text selection
- message selection
- selected-message copy
- inline tool result expansion
- animated activity status
- thinking mode cycling
- thinking-token display toggle
- queued steering
- queued follow-ups

这些都属于：

```text
让 TUI 从“能用”变成“可持续使用”
```

## 19. responsive sidebar

TUI sidebar 显示：

- provider
- model
- thinking mode
- tools
- skills
- prompt templates
- context files

这让用户不用执行命令也能知道当前 session 状态。

## 20. transcript text selection

Textual TUI 支持可见 transcript 文本选择。

这对 coding agent 很重要，因为用户经常想复制：

- 命令输出
- 错误信息
- assistant 解释
- tool result

## 21. `Ctrl-C` copy

选中消息后复制，不应该和普通终端中断逻辑混乱。

所以 TUI 有自己的 selected-message copy 行为。

这类细节属于前端 hardening。

## 22. `Ctrl-O` 展开 tool result

默认 transcript 不一定显示完整 tool result。

用户用：

```text
Ctrl-O
```

可以展开/隐藏工具结果。

这在 read 大文件、bash 输出很长时很有用。

## 23. animated activity status

agent 正在运行时，TUI 会显示活动状态。

这解决的是用户心理预期：

```text
现在是真的还在跑，还是卡死了？
```

## 24. thinking controls

TUI 支持：

```text
Shift-Tab  cycle thinking mode
Ctrl-T     toggle thinking token display
```

这两个不同：

- Shift-Tab 改 provider request 的 reasoning effort
- Ctrl-T 只改 UI 是否显示 streamed thinking deltas

## 25. queued steering/follow-ups

TUI 支持：

```text
Enter while running      -> steering
Alt-Enter while running  -> follow-up
```

并且 queued prompt 不会立刻写入 JSONL。

只有被 `AgentHarness` 注入 active run 后，才成为 durable message。

## 26. Architecture Boundary

这篇最重要的部分其实是边界。

架构文档总结：

```text
tau_ai      provider-specific retry, token, and stream parsing
tau_agent   portable messages, events, loop coordination, harness state, queues, tools, sessions
tau_coding  provider config, credentials, resources, commands, persistence workflows, docs, Textual UI policy
```

这是整套项目的分层规则。

## 27. `tau_ai` 应该拥有什么

`tau_ai` 负责和模型服务打交道。

包括：

- OpenAI-compatible streaming
- Anthropic streaming
- Codex subscription streaming
- retry
- provider-specific thinking/reasoning parsing
- 把 provider stream 转成 provider-neutral events

它不应该知道：

- TUI
- slash commands
- session files
- skills

## 28. `tau_agent` 应该拥有什么

`tau_agent` 是 reusable agent brain。

它负责：

- messages
- events
- tools protocol
- agent loop
- harness transcript state
- queued steering/follow-up semantics
- append-only session primitives

它不应该知道：

- Textual
- Rich rendering
- Typer
- `~/.tau`
- `.agents`
- provider credentials file
- project resources

## 29. `tau_coding` 应该拥有什么

`tau_coding` 是 coding app。

它负责：

- CLI
- TUI
- provider configuration
- credentials
- resources
- skills
- prompt templates
- session manager
- persistence workflows
- docs-facing behavior

它是把 reusable agent brain 变成真实 coding agent app 的地方。

## 30. 为什么要反复强调边界

因为后面的 Phase 21 extensions 如果要做，一定会诱惑我们把东西乱塞：

- extension 想控制 UI
- extension 想操作 provider
- extension 想读 project resources
- extension 想改 agent loop

如果没有边界，扩展系统会让核心失控。

所以 pre-extension hardening 先把规则立好。

## 31. 测试范围

架构文档列出的 focused tests：

```text
tests/test_agent_harness.py
tests/test_agent_loop.py
tests/test_coding_session.py
tests/test_context_window.py
tests/test_provider_config.py
tests/test_rendering.py
tests/test_session_export.py
tests/test_skills.py
tests/test_tau_ai.py
tests/test_tui_adapter.py
tests/test_tui_app.py
tests/test_tui_config.py
```

这些测试覆盖的是一组横切行为。

不是单文件单功能。

## 32. full gate

架构文档写到：

```bash
uv run pytest
uv run ruff check .
uv run mypy
```

这是发布前 gate。

### 32.1 `pytest`

运行测试。

验证行为没有坏。

### 32.2 `ruff check`

Ruff 是 Python linter。

它检查：

- import 顺序
- 常见 bug pattern
- 风格问题
- 简化建议

### 32.3 `mypy`

Mypy 是静态类型检查器。

它不运行代码，而是根据类型标注检查类型是否一致。

## 33. 小白必须分清的几组概念

### 33.1 hardening 不是新功能堆叠

它更像：

```text
把已有功能的失败路径、边界、测试和用户反馈补齐
```

### 33.2 provider-neutral 不等于没有 provider-specific

底层 provider adapter 当然有 provider-specific 逻辑。

但它们要输出统一事件，让上层不用理解 provider 差异。

### 33.3 TUI 是事件消费者

TUI 不应该直接操纵 agent loop。

它消费 `AgentEvent`，更新 `TuiState`，再渲染 widgets。

### 33.4 session history 和 UI display 不一样

session history 要保存真实 durable 状态。

UI display 可以 compact、隐藏、折叠。

例如 skill invocation 和 tool result 都有这种差别。

### 33.5 Phase 21 被延后是架构选择

先 harden 基础，再做 extension。

这是为了避免在不稳定地基上扩展复杂系统。

## 34. 运行测试

Pre-extension Hardening 对应 focused tests：

```bash
uv run pytest tests/test_agent_harness.py tests/test_agent_loop.py tests/test_coding_session.py tests/test_context_window.py tests/test_provider_config.py tests/test_rendering.py tests/test_session_export.py tests/test_skills.py tests/test_tau_ai.py tests/test_tui_adapter.py tests/test_tui_app.py tests/test_tui_config.py
```

如果要跑 full gate：

```bash
uv run pytest
uv run ruff check .
uv run mypy
```

## 35. 用一句话总结

Pre-extension Hardening 的价值是：在继续做扩展系统之前，把 provider retry/thinking/queue events、context accounting、skills、session export、TUI 状态刷新和 package boundary 全部收紧成一套可测试、可解释、边界清楚的 Tau runtime 基础。

## 36. 我的问题与推荐回答

问题：为什么 Tau 要在 Phase 21 extensions 之前专门做 Pre-extension Hardening，而不是直接开始做扩展系统？

我的推荐回答：

因为扩展系统会放大现有架构的所有不稳定点。如果 provider retry、thinking events、queued prompts、context accounting、session export、TUI refresh、credentials 和 package boundary 还不清楚，扩展一接入就会把问题扩散到更多入口。Pre-extension Hardening 先把这些基础行为做成 provider-neutral events、明确持久化边界、补齐测试，并再次确认 `tau_ai`、`tau_agent`、`tau_coding` 的职责分离，这样后续扩展系统才不会把核心 agent runtime 搅乱。
