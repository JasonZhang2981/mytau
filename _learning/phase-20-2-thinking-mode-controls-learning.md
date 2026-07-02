# Phase 20.2 学习笔记：Thinking Mode Controls

对应架构文档：`dev-notes/architecture/phase-20-2-thinking-controls.md`

对应源码：

- `src/tau_coding/thinking.py`
- `src/tau_coding/provider_catalog.py`
- `src/tau_coding/provider_config.py`
- `src/tau_coding/provider_runtime.py`
- `src/tau_coding/session.py`
- `src/tau_coding/commands.py`
- `src/tau_coding/tui/config.py`
- `src/tau_coding/tui/app.py`
- `src/tau_coding/tui/widgets.py`
- `src/tau_ai/env.py`
- `src/tau_ai/openai_codex.py`
- `src/tau_ai/anthropic.py`
- `tests/test_thinking.py`
- `tests/test_provider_config.py`
- `tests/test_coding_session.py`
- `tests/test_commands.py`
- `tests/test_tui_app.py`

## 1. 这一阶段到底在做什么

Phase 20.2 把 thinking mode 变成 Tau coding session 的显式设置。

简单说，它回答几个问题：

```text
Tau 支持哪些 thinking 档位？
当前 provider/model 支不支持这些档位？
用户怎么切换？
切换后怎么持久化到 session？
真正请求 provider 时怎么把 thinking 转成 API 参数？
TUI 怎么显示和操作？
```

这不是简单的 UI 开关。

它涉及三层：

```text
tau_coding.thinking          定义 Tau 自己的 thinking 档位
tau_coding.provider_config   判断 provider/model 能不能用
tau_coding.provider_runtime  转成具体 provider runtime config
```

## 2. 什么是 thinking mode

thinking mode 可以理解成：

```text
让模型用多少推理努力来回答
```

不同 provider 叫法不完全一样：

- OpenAI-compatible 可能叫 `reasoning_effort`
- Responses API 形态可能是 `reasoning.effort`
- Anthropic extended thinking 使用 `thinking.budget_tokens`
- Codex subscription transport 又有自己的映射

所以 Tau 不能直接把 UI 选项写死成某个 provider 的字段。

Tau 先定义自己的抽象档位，再由 provider runtime 做映射。

## 3. `tau_coding.thinking`

核心文件：

```text
src/tau_coding/thinking.py
```

这个文件很小，但非常关键。

它定义 Tau 自己认识的 thinking 语言。

## 4. `ThinkingLevel`

源码：

```python
ThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh"]
```

`Literal` 来自 Python 标准库 `typing`。

它表示这个字符串类型只能是列出的几个固定值。

也就是说，合法 thinking level 只有：

```text
off
minimal
low
medium
high
xhigh
```

## 5. `ThinkingParameter`

源码：

```python
ThinkingParameter = Literal["reasoning_effort", "reasoning.effort", "anthropic.thinking"]
```

这个表示 provider 配置里支持的底层参数类型。

三个含义：

- `reasoning_effort`：OpenAI-compatible chat completions 顶层字段
- `reasoning.effort`：Responses API 风格的嵌套 reasoning 字段
- `anthropic.thinking`：Anthropic extended thinking

## 6. `THINKING_LEVELS`

源码：

```python
THINKING_LEVELS: tuple[ThinkingLevel, ...] = (
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)
```

这是 Tau 的标准顺序。

后面的 cycle 会按这个顺序切换。

## 7. 默认 thinking level

源码：

```python
DEFAULT_THINKING_LEVEL: ThinkingLevel = "medium"
```

新 session 默认是 `medium`。

但是注意：

```text
默认偏好是 medium
真正可用档位还要看当前 provider/model 是否声明支持
```

如果当前模型只支持：

```text
low, high
```

Tau 会把当前 thinking level coerced 到可用默认值。

## 8. `normalize_thinking_level()`

源码：

```python
def normalize_thinking_level(value: str | None) -> ThinkingLevel:
    if value is None:
        return DEFAULT_THINKING_LEVEL
    normalized = value.strip().lower()
    if normalized in THINKING_LEVELS:
        return normalized
    allowed = ", ".join(THINKING_LEVELS)
    raise ValueError(f"Unknown thinking mode: {value}. Available modes: {allowed}")
```

这个函数负责把用户输入转成标准值。

例如：

```python
normalize_thinking_level("HIGH") == "high"
normalize_thinking_level(None) == "medium"
```

如果输入未知：

```python
normalize_thinking_level("maximum")
```

会抛出：

```text
ValueError: Unknown thinking mode
```

## 9. 为什么要 normalize

用户输入可能是：

```text
HIGH
 High
high
```

源码内部希望统一成：

```text
high
```

这样后续判断就简单。

## 10. `normalize_thinking_levels()`

源码：

```python
def normalize_thinking_levels(values: Sequence[str]) -> tuple[ThinkingLevel, ...]:
    if isinstance(values, str) or not values:
        ...
    normalized = tuple(normalize_thinking_level(value) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError("Thinking modes must be unique")
    return normalized
```

这个函数用于 provider config。

provider 声明：

```json
"thinking_levels": ["off", "low", "high"]
```

Tau 要验证：

- 必须是列表
- 不能为空
- 每个值必须合法
- 不能重复

## 11. `Sequence`

`Sequence` 来自 `collections.abc`。

它表示“有顺序的一组东西”。

例如：

- list
- tuple

这里不用 `list[str]`，是为了函数既能接受 list，也能接受 tuple。

## 12. `reasoning_effort_for_level()`

源码：

```python
def reasoning_effort_for_level(level: str | None) -> ReasoningEffort:
    normalized = normalize_thinking_level(level)
    if normalized == "off":
        return "none"
    return normalized
```

Tau UI 里叫：

```text
off
```

但 OpenAI-compatible reasoning effort 可能用：

```text
none
```

所以这里映射：

```text
off -> none
minimal -> minimal
low -> low
medium -> medium
high -> high
xhigh -> xhigh
```

## 13. `anthropic_thinking_budget_for_level()`

源码：

```python
def anthropic_thinking_budget_for_level(level: str | None) -> int | None:
    normalized = normalize_thinking_level(level)
    if normalized == "off":
        return None
    return {
        "minimal": 1024,
        "low": 2048,
        "medium": 4096,
        "high": 8192,
        "xhigh": 16384,
    }[normalized]
```

Anthropic extended thinking 不直接用 `high` 这种字符串。

它使用 budget tokens。

所以 Tau 映射为：

```text
off     -> None
minimal -> 1024
low     -> 2048
medium  -> 4096
high    -> 8192
xhigh   -> 16384
```

`None` 表示不发送 thinking payload。

## 14. `next_thinking_level()`

源码：

```python
def next_thinking_level(
    current: str | None,
    *,
    available: tuple[ThinkingLevel, ...] = THINKING_LEVELS,
) -> ThinkingLevel:
    if not available:
        return DEFAULT_THINKING_LEVEL
    try:
        normalized_current = normalize_thinking_level(current)
        index = available.index(normalized_current)
    except ValueError:
        return available[0]
    return available[(index + 1) % len(available)]
```

它负责循环切换。

例如：

```python
next_thinking_level("medium") == "high"
next_thinking_level("xhigh") == "off"
```

如果当前值不在可用列表里：

```python
next_thinking_level("missing", available=("low", "high")) == "low"
```

## 15. provider 不是都支持 thinking

这是 Phase 20.2 的核心边界。

不能因为 Tau UI 有：

```text
off minimal low medium high xhigh
```

就对所有模型都展示这些选项。

有些 provider/model 可能：

- 不支持 reasoning control
- 支持但参数名不同
- 只支持部分档位
- 只有特定模型支持

所以 provider config 增加了 thinking metadata。

## 16. provider config 的 thinking 字段

`OpenAICompatibleProviderConfig`、`AnthropicProviderConfig`、`OpenAICodexProviderConfig` 都有：

```python
thinking_levels: tuple[ThinkingLevel, ...] | None = None
thinking_models: tuple[str, ...] = ()
thinking_default: ThinkingLevel | None = None
thinking_parameter: ThinkingParameter | None = None
```

含义：

- `thinking_levels`：这个 provider 支持哪些档位
- `thinking_models`：只有哪些模型支持
- `thinking_default`：这个 provider/model 的默认档位
- `thinking_parameter`：运行时应该映射到哪种 API 参数

## 17. `provider_thinking_levels()`

源码：

```python
def provider_thinking_levels(provider: ProviderConfig, *, model: str | None = None):
    if provider.thinking_levels is None:
        return ()
    selected_model = model or provider.default_model
    if provider.thinking_models and selected_model not in provider.thinking_models:
        return ()
    return provider.thinking_levels
```

逻辑很清楚：

```text
如果 provider 没声明 thinking_levels -> 不支持
如果声明了 thinking_models，但当前 model 不在里面 -> 不支持
否则返回 thinking_levels
```

返回空 tuple `()` 表示不可用。

## 18. `provider_thinking_unavailable_reason()`

如果不可用，Tau 会给一个原因。

例如：

```text
Provider local does not declare thinking_levels
```

或者：

```text
openai:gpt-4.1 is not declared in thinking_models
```

这对用户体验很重要。

不是简单说：

```text
不能用
```

而是告诉你为什么不能用。

## 19. `provider_default_thinking_level()`

源码逻辑：

```text
1. 先拿可用 levels
2. 如果 provider.thinking_default 在 levels 中，用它
3. 否则如果 medium 可用，用 medium
4. 否则用第一个可用 level
```

这保证切换 provider/model 后，Tau 能选择一个合法档位。

## 20. `_validate_thinking_config()`

`provider_config.py` 里：

```python
def _validate_thinking_config(...):
    if thinking_levels is None:
        if thinking_models or thinking_default is not None or thinking_parameter is not None:
            raise ProviderConfigError(...)
        return
    ...
```

意思是：

```text
如果没声明 thinking_levels，就不能单独声明 thinking_models/default/parameter
```

否则配置会自相矛盾。

然后它继续校验：

- thinking levels 必须合法且已 normalized
- thinking models 不能是空字符串
- thinking default 必须在 levels 里
- thinking parameter 必须是支持的三种之一

## 21. built-in provider catalog

`src/tau_coding/provider_catalog.py` 里内置 provider 会声明 thinking 能力。

例如 OpenAI 的部分模型：

```text
thinking_levels=("off", "low", "medium", "high", "xhigh")
thinking_parameter="reasoning_effort"
```

OpenAI Codex subscription：

```text
thinking_levels=("off", "minimal", "low", "medium", "high", "xhigh")
thinking_parameter="reasoning.effort"
```

Anthropic：

```text
thinking_parameter="anthropic.thinking"
```

注意：

```text
只有声明在 thinking_models 里的模型才暴露 thinking controls
```

## 22. 从 durable config 到 runtime provider

Thinking mode 不能只存在配置里。

真正调用模型时，还要把它传给 provider runtime。

入口在：

```text
src/tau_coding/provider_runtime.py
```

核心函数：

```python
create_model_provider(provider, model=model, thinking_level=thinking_level)
```

它根据 provider 类型创建：

- `OpenAICompatibleProvider`
- `OpenAICodexProvider`
- `AnthropicProvider`

## 23. OpenAI-compatible 映射

`openai_compatible_config_from_provider()` 里：

```python
reasoning_effort = _reasoning_effort_from_provider(
    provider,
    model=model,
    thinking_level=thinking_level,
)
```

如果 provider 的：

```python
thinking_parameter
```

是：

```text
reasoning_effort
reasoning.effort
```

并且当前 model 支持 thinking，才会生成 reasoning effort。

如果当前 model 不支持，返回 `None`。

## 24. Anthropic 映射

`anthropic_config_from_provider()` 里：

```python
thinking_budget_tokens = _anthropic_thinking_budget_from_provider(...)
```

如果 thinking level 是：

```text
high
```

会映射为：

```text
8192
```

然后传给 `AnthropicConfig.thinking_budget_tokens`。

`tau_ai/anthropic.py` 再把它变成 HTTP payload 里的：

```json
{
  "thinking": {
    "type": "enabled",
    "budget_tokens": 8192
  }
}
```

如果是 `off`，就不发送 thinking payload。

## 25. OpenAI Codex subscription 映射

`provider_runtime.py` 里有：

```python
def _codex_reasoning_effort(...):
    ...
    if normalized == "off":
        return None
    if normalized == "minimal":
        return "low"
    return reasoning_effort_for_level(normalized)
```

这里有一个特殊规则：

```text
minimal -> low
```

因为 Codex subscription transport 的底层可接受值和 Tau UI 档位不是完全一一对应。

## 26. Session 持久化

Phase 20.2 不只是运行时设置，也要持久化。

新 session 初始化时，`CodingSession.load()` 会创建：

```python
info = SessionInfoEntry(...)
model = ModelChangeEntry(...)
thinking = ThinkingLevelChangeEntry(
    parent_id=model.id,
    thinking_level=config.thinking_level,
)
```

也就是说，新 session 一开始就有 thinking level entry。

## 27. `ThinkingLevelChangeEntry`

这个 entry 在 Phase 7 已经定义：

```python
class ThinkingLevelChangeEntry(BaseSessionEntry):
    type: Literal["thinking_level_change"] = "thinking_level_change"
    thinking_level: str | None = None
```

`tau_agent.session` 不知道 provider 支不支持 thinking。

它只负责：

```text
保存和 replay 这个状态变化
```

具体的可用性判断属于 `tau_coding`。

## 28. `CodingSession.thinking_level`

源码：

```python
@property
def thinking_level(self) -> ThinkingLevel:
    return self._thinking_level
```

当前 thinking level 存在 `CodingSession` 内部。

它会受到：

- 初始 config
- session replay
- provider/model capability
- 用户切换

共同影响。

## 29. `available_thinking_levels`

源码：

```python
@property
def available_thinking_levels(self) -> tuple[ThinkingLevel, ...]:
    if self._provider_settings is None:
        return THINKING_LEVELS
    provider = self._active_provider_config()
    if provider is None:
        return ()
    return provider_thinking_levels(provider, model=self.model)
```

如果没有 provider settings，就默认返回所有 Tau levels。

如果有 provider settings，就根据当前 provider/model 判断。

## 30. `thinking_unavailable_reason`

源码：

```python
@property
def thinking_unavailable_reason(self) -> str | None:
    if self.available_thinking_levels:
        return None
    provider = self._active_provider_config()
    if provider is None:
        return "Active provider settings are not available"
    return provider_thinking_unavailable_reason(provider, model=self.model)
```

这个属性给 UI 和 `/session` 使用。

## 31. `set_thinking_level()`

源码逻辑：

```text
1. normalize 用户输入
2. 检查当前 provider/model 是否有 available levels
3. 检查目标 level 是否在 available levels 里
4. 更新 runtime provider
5. append ThinkingLevelChangeEntry
6. append LeafEntry
7. replay persisted state
```

它返回用户可读消息：

```text
Thinking mode: high
```

如果不可用，会抛 `ValueError`。

TUI 会捕获这个错误并通知用户。

## 32. `cycle_thinking_level()`

源码：

```python
async def cycle_thinking_level(self) -> str:
    return await self.set_thinking_level(
        next_thinking_level(
            self._thinking_level,
            available=self.available_thinking_levels,
        )
    )
```

它不自己保存 session。

它只是算出下一个 level，然后复用 `set_thinking_level()`。

这是很好的复用。

## 33. provider/model 切换时的同步

当用户切换模型：

```python
def set_model(self, model: str) -> None:
    self._harness.config.model = model
    self._sync_thinking_level_to_active_model()
    self._refresh_runtime_provider()
```

当用户切换 provider：

```python
def set_provider(...):
    thinking_level = _coerced_thinking_level(...)
    ...
    self._thinking_level = thinking_level
```

也就是说，thinking level 不是盲目保留。

它会被校正到目标 provider/model 支持的范围。

## 34. TUI 快捷键

`src/tau_coding/tui/config.py` 里默认：

```python
thinking_cycle: str = "shift+tab"
toggle_thinking: str = "ctrl+t"
```

含义：

- `Shift+Tab`：循环切换 thinking mode
- `Ctrl+T`：显示/隐藏 streamed thinking tokens

注意这两个不是一回事。

## 35. cycle thinking vs toggle thinking tokens

### 35.1 cycle thinking

改变未来请求的 reasoning effort：

```text
medium -> high -> xhigh -> off ...
```

它会影响 provider runtime config。

### 35.2 toggle thinking tokens

只改变 UI 是否显示模型流出来的 thinking delta。

它不改变 provider 请求参数。

源码里：

```python
self.state.toggle_thinking()
```

只是切换 UI state。

## 36. TUI 如何执行 thinking cycle

`src/tau_coding/tui/app.py`：

```python
def action_cycle_thinking(self) -> None:
    self.run_worker(self._cycle_thinking_level(), exclusive=False)
```

然后：

```python
async def _cycle_thinking_level(self) -> None:
    cycler = getattr(self.session, "cycle_thinking_level", None)
    ...
    result = cycler()
    if isawaitable(result):
        await result
    self._refresh()
```

如果 session 没有这个方法，TUI 会提示：

```text
Thinking controls are not available.
```

如果抛错，会提示：

```text
Could not change thinking mode: ...
```

## 37. TUI 显示 thinking level

`src/tau_coding/tui/widgets.py`：

```python
def _thinking_level(session: SessionSummarySource) -> str:
    available = getattr(session, "available_thinking_levels", None)
    if available == ():
        return "unavailable"
    explicit_level = getattr(session, "thinking_level", None)
    if explicit_level:
        return str(explicit_level)
    ...
```

如果当前 provider/model 不支持：

```text
unavailable
```

否则显示当前档位：

```text
medium
high
...
```

## 38. `/session` 如何显示 thinking

`commands.py` 的 `_status_command()` 会调用：

```python
lines.extend(_thinking_status_lines(session))
```

如果可用：

```text
Thinking mode: medium
```

如果不可用：

```text
Thinking mode: unavailable
Thinking unavailable: Provider local does not declare thinking_levels
```

这和 Phase 20.1 的 `/session` 状态输出放在一起。

## 39. `/thinking` 函数存在，但默认没注册

当前源码里有：

```python
def _thinking_command(context: CommandContext) -> CommandResult:
    ...
```

但 `create_default_command_registry()` 没有注册：

```python
SlashCommand(name="thinking", ...)
```

所以默认 slash command 里没有 `/thinking`。

架构文档说 Tau 不注册 standalone `/thinking`，这个和当前 registry 状态一致。

不过 TUI 测试里有 fake session 模拟 `/thinking high` 的行为，这是测试壳的能力，不代表默认 registry 暴露了这个命令。

## 40. thinking stream events

provider 可能会流出 thinking delta。

在 `tau_ai/events.py` 里，这类事件是 provider-neutral 的：

```text
thinking_delta
```

TUI adapter 里：

```python
if isinstance(event, ThinkingDeltaEvent):
    self.state.add_thinking_delta(event.delta)
    return
```

这说明：

```text
provider adapter 负责把 provider-specific thinking stream 变成统一事件
TUI 决定是否显示
```

## 41. 架构边界

Thinking controls 的边界很清楚：

```text
tau_coding.thinking
  定义 Tau thinking 档位

tau_coding.provider_config
  保存 durable provider capability metadata

tau_coding.provider_runtime
  转成 provider-specific runtime config

tau_ai
  发出 provider-specific HTTP payload，解析 thinking stream

tau_agent.session
  只保存 ThinkingLevelChangeEntry，不理解 provider 规则

tau_coding.tui
  显示、快捷键、隐藏或展示 thinking tokens
```

这避免了 `tau_agent` 核心层依赖具体 provider 或 Textual。

## 42. 测试如何覆盖这一阶段

### 42.1 `tests/test_thinking.py`

覆盖：

- thinking level normalize
- unknown mode 报错
- cycle 顺序
- duplicate levels 拒绝
- `off -> none` 映射

### 42.2 `tests/test_provider_config.py`

覆盖：

- built-in providers 声明哪些模型支持 thinking
- unsupported model 返回空 levels
- unavailable reason
- OpenAI-compatible reasoning effort
- Anthropic thinking budget
- JSON 里加载 custom thinking capabilities

### 42.3 `tests/test_coding_session.py`

覆盖：

- 新 session 初始 thinking entry
- thinking level 持久化和 resume
- cycle thinking
- provider/model capability 校验
- 切换 thinking 后刷新 runtime provider

### 42.4 `tests/test_commands.py`

覆盖：

- `/session` 显示 thinking mode
- thinking 不可用时显示 reason
- hotkeys 提示 `Shift+Tab`

### 42.5 `tests/test_tui_app.py`

覆盖：

- 快捷键 cycle thinking
- running 时也能 cycle
- 自定义 keybinding，比如 `f3`
- `Ctrl+T` 显示/隐藏 thinking tokens

## 43. 小白必须分清的几组概念

### 43.1 thinking level 不是 provider 参数

Tau 内部是：

```text
off/minimal/low/medium/high/xhigh
```

provider 参数可能是：

```text
reasoning_effort
reasoning.effort
thinking budget tokens
```

中间需要映射。

### 43.2 thinking 可用性看 provider + model

不能只看 provider。

同一个 provider 下，不同 model 支持情况可能不同。

### 43.3 thinking mode 和 thinking tokens 显示不是一回事

`Shift+Tab` 改请求强度。

`Ctrl+T` 改 UI 是否显示模型流出的 thinking 文本。

### 43.4 session 保存的是选择，不保存推理文本

`ThinkingLevelChangeEntry` 保存的是：

```text
用户选择了哪个 thinking level
```

不是保存模型内部 thinking 内容。

### 43.5 不支持时不要假装支持

如果 provider/model 没声明 metadata，Tau 会显示 unavailable。

这是比盲目发送参数更安全的设计。

## 44. 运行测试

Phase 20.2 相关测试：

```bash
uv run pytest tests/test_thinking.py tests/test_provider_config.py tests/test_coding_session.py tests/test_commands.py tests/test_tui_adapter.py tests/test_tui_config.py tests/test_tui_app.py tests/test_tau_ai.py tests/test_agent_loop.py
```

这些测试覆盖从配置、session、provider runtime 到 TUI 的完整链路。

## 45. 用一句话总结 Phase 20.2

Phase 20.2 的价值是：把 thinking/reasoning effort 从 provider-specific 的混乱参数，提升成 Tau 自己的一套 session-level 控制，并通过 provider capability metadata 安全地决定哪些模型能用、怎么映射、如何持久化、如何在 TUI 中切换和展示。

## 46. 我的问题与推荐回答

问题：为什么 Tau 要先定义自己的 `ThinkingLevel`，而不是在 UI 里直接暴露 OpenAI 的 `reasoning_effort` 或 Anthropic 的 `budget_tokens`？

我的推荐回答：

因为 Tau 是 provider-neutral 的 coding agent。不同 provider 对“推理强度”的字段、取值和支持模型都不一样：OpenAI-compatible 可能用 `reasoning_effort`，Codex subscription 用 `reasoning.effort`，Anthropic 用 thinking token budget。Tau 先定义统一的 `off/minimal/low/medium/high/xhigh`，再由 provider config 声明 capability，由 provider runtime 映射到底层参数。这样 UI、session 持久化和命令层都能使用同一套语言，同时避免对不支持的模型错误发送参数。
