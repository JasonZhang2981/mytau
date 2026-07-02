# Phase 18 学习笔记：Provider Configuration Foundation

对应架构文档：`dev-notes/architecture/phase-18-provider-config-foundation.md`

主要源码：

- `src/tau_coding/provider_config.py`
- `src/tau_coding/provider_runtime.py`
- `src/tau_coding/cli.py`
- `src/tau_coding/session.py`
- `src/tau_coding/commands.py`
- `src/tau_coding/tui/app.py`
- `tests/test_provider_config.py`
- `tests/test_provider_runtime.py`
- `tests/test_cli.py`
- `tests/test_coding_session.py`
- `tests/test_tui_app.py`

前置阶段：

- Phase 2：`tau_ai` 定义了 provider 抽象和 OpenAI-compatible provider
- Phase 6：CLI print mode 可以选择模型
- Phase 8：`CodingSession` 持有 provider 和 model
- Phase 15：`/model`、`/login` 等命令进入 slash command registry
- Phase 18：provider/model 选择从硬编码升级成持久化配置

## 1. 这一阶段到底在做什么

Phase 18 给 Tau 增加 provider configuration foundation。

简单说：

```text
Tau 不再只靠代码里写死的 provider/model；
它开始从 ~/.tau/providers.json 读取 provider 设置。
```

provider 就是模型服务来源。

例如：

- OpenAI
- OpenAI-compatible local server
- Anthropic
- OpenRouter
- HuggingFace
- OpenAI Codex subscription

model 就是具体模型名。

例如：

```text
gpt-5.5
claude-sonnet-4-6
openai/gpt-oss-120b
qwen
```

Phase 18 的核心价值是：

```text
把“使用哪个 provider、哪个 model、base_url、api_key_env、timeout、retry”等配置变成 durable settings。
```

durable 的意思是：

```text
保存到磁盘，下次启动还能用。
```

## 2. 这一阶段仍然属于 tau_coding

provider settings 放在：

```text
src/tau_coding/provider_config.py
```

而不是 `tau_agent`。

原因是：

```text
tau_agent 只需要一个已经构造好的 ModelProvider 和 model name。
```

它不应该知道：

- `~/.tau/providers.json`
- `~/.tau/credentials.json`
- 环境变量
- CLI setup 命令
- TUI login flow
- 默认 provider 选择

所以边界是：

```text
tau_coding 读取配置、选择 provider、创建 runtime provider
tau_agent 只接收 provider 对象并运行 agent loop
```

## 3. 当前代码和 Phase 18 文档的差异

Phase 18 架构文档里写的默认模型是早期值。

当前源码里：

```python
DEFAULT_PROVIDER_NAME = "openai"
DEFAULT_MODEL = "gpt-5.5"
```

测试也验证：

```python
assert "*\topenai\topenai-compatible\tgpt-5.5" in result.stdout
```

当前内置 provider 也比早期文档更丰富：

```text
openai
openai-codex
anthropic
openrouter
huggingface
```

所以学习时以当前源码为准：

```text
Phase 18 建立 provider config 机制；
后续代码继续扩展了内置 provider、thinking controls、OAuth 和 scoped models。
```

## 4. provider_config.py 的 import

文件开头：

```python
from contextlib import suppress
from dataclasses import dataclass, field, replace
from json import dumps, loads
from os import environ
from pathlib import Path
from shutil import copy2
from tempfile import NamedTemporaryFile
from typing import Any, Protocol
```

这里有很多 Python 标准库。

### 4.1 contextlib.suppress

`suppress` 用来忽略指定异常。

例如：

```python
with suppress(OSError):
    copy2(path, backup_path)
```

意思是：

```text
尝试执行 copy；
如果出现 OSError，就忽略。
```

这里用于写备份文件。

备份失败不一定要阻止主配置写入。

### 4.2 dataclasses.replace

`replace()` 用来复制一个 dataclass，并修改部分字段。

例如：

```python
updated_provider = replace(provider, models=models, default_model=model)
```

因为 provider config 是：

```python
@dataclass(frozen=True, slots=True)
```

不能直接改字段。

所以用 `replace()` 生成一个新对象。

### 4.3 json.dumps / json.loads

```python
loads(...)
```

把 JSON 字符串转成 Python 对象。

```python
dumps(...)
```

把 Python 对象转成 JSON 字符串。

这里用于读写：

```text
~/.tau/providers.json
```

### 4.4 os.environ

```python
from os import environ
```

`environ` 是环境变量字典。

例如：

```python
environ.get("OPENAI_API_KEY")
```

读取环境变量。

Tau 不把 API key 直接写进 providers.json。

custom provider 通常通过 `api_key_env` 指定从哪个环境变量读取 key。

### 4.5 shutil.copy2

`copy2()` 用于复制文件，并尽量保留元数据。

这里用于在覆盖 `providers.json` 前写：

```text
providers.json.bak
```

### 4.6 tempfile.NamedTemporaryFile

`NamedTemporaryFile` 用于创建临时文件。

Tau 用它实现 atomic write。

大意是：

1. 先写临时文件。
2. 写完后 replace 到目标文件。

这样比直接覆盖 `providers.json` 更安全。

## 5. ProviderConfigError

源码：

```python
class ProviderConfigError(ValueError):
    """Raised when Tau provider configuration is invalid."""
```

它继承 `ValueError`。

用于表达 provider 配置不合法。

例如：

- provider 不存在
- JSON 结构不对
- timeout 小于等于 0
- max_retries 小于 0
- headers 不是字符串字典
- thinking 配置不合法

使用专门异常的好处是：

```text
调用方可以区分“配置错误”和普通运行错误。
```

## 6. CredentialReader Protocol

源码：

```python
class CredentialReader(Protocol):
    """Credential lookup used while building runtime provider config."""

    def get(self, name: str) -> str | None: ...
```

这是一个协议。

只要对象有：

```python
get(name: str) -> str | None
```

就可以当 credential reader。

测试里可以写 fake：

```python
class FakeCredentials:
    def get(self, name: str) -> str | None:
        return "stored-key" if name == "stored" else None
```

这让测试不需要真的读 `~/.tau/credentials.json`。

## 7. OpenAICompatibleProviderConfig

核心 dataclass：

```python
@dataclass(frozen=True, slots=True)
class OpenAICompatibleProviderConfig:
    """Durable settings for one OpenAI-compatible provider."""

    name: str
    base_url: str = DEFAULT_OPENAI_COMPATIBLE_BASE_URL
    api_key_env: str = "OPENAI_API_KEY"
    credential_name: str | None = None
    models: tuple[str, ...] = (DEFAULT_MODEL,)
    default_model: str = DEFAULT_MODEL
    context_windows: dict[str, int] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES
    max_retry_delay_seconds: float = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS
    ...
```

这是持久化配置。

也就是说它可以写进 JSON。

它不是 runtime provider。

不要把这两个概念混了：

```text
ProviderConfig              配置数据
OpenAICompatibleProvider    真正发 HTTP 请求的运行时对象
```

## 8. OpenAI-compatible 是什么意思

OpenAI-compatible provider 指的是：

```text
接口形状兼容 OpenAI Chat/Responses 风格的服务。
```

例如：

- OpenAI 官方
- 本地 Ollama/OpenAI-compatible server
- OpenRouter
- HuggingFace 某些兼容接口

所以配置里有：

```python
base_url
api_key_env
headers
timeout_seconds
max_retries
```

这些都是 HTTP client 需要的信息。

## 9. credential_name 和 api_key_env

两个字段很重要：

```python
api_key_env: str = "OPENAI_API_KEY"
credential_name: str | None = None
```

`api_key_env` 表示：

```text
如果要从环境变量读 key，读哪个变量。
```

例如：

```text
OPENAI_API_KEY
LOCAL_API_KEY
OPENROUTER_API_KEY
HF_TOKEN
```

`credential_name` 表示：

```text
如果 key 存在 ~/.tau/credentials.json 里，用哪个名字取。
```

Phase 18 文档强调：

```text
API keys are not stored in providers.json.
```

providers.json 存 provider metadata。

credentials.json 存密钥。

环境变量也可以提供密钥。

## 10. __post_init__()

`OpenAICompatibleProviderConfig` 有：

```python
def __post_init__(self) -> None:
    _validate_provider_numbers(...)
    _validate_context_windows(self.context_windows)
    _validate_thinking_config(...)
```

`__post_init__()` 是 dataclass 创建对象后自动调用的方法。

用来做校验。

例如：

```python
OpenAICompatibleProviderConfig(name="local", timeout_seconds=0)
```

会报：

```text
Provider timeout_seconds must be greater than 0
```

测试里也有：

```python
with pytest.raises(ProviderConfigError, match="greater than 0"):
    OpenAICompatibleProviderConfig(name="local", timeout_seconds=0)
```

## 11. to_json()

每个 provider config 都有：

```python
def to_json(self) -> dict[str, Any]:
```

它把 dataclass 转成 JSON-compatible dict。

例如 tuple 要转 list：

```python
"models": list(self.models)
```

dict 要复制：

```python
"headers": dict(self.headers)
```

为什么叫 JSON-compatible？

因为 JSON 支持：

- object/dict
- array/list
- string
- number
- boolean
- null

但不认识 Python 的 `Path`、tuple、dataclass。

所以保存前要转成普通 dict/list/string/number。

## 12. AnthropicProviderConfig 和 OpenAICodexProviderConfig

当前代码还有：

```python
AnthropicProviderConfig
OpenAICodexProviderConfig
```

它们和 OpenAI-compatible 很像：

- 都有 `name`
- 都有 `base_url`
- 都有 `api_key_env`
- 都有 `credential_name`
- 都有 `models`
- 都有 `default_model`
- 都有 timeout/retry
- 都有 thinking 相关配置

差异在于运行时 provider 构造不同。

Anthropic 用：

```python
AnthropicProvider
```

OpenAI Codex 用：

```python
OpenAICodexProvider
```

这些是在后续扩展里加丰富的，但仍然复用 Phase 18 的持久化配置思路。

## 13. type ProviderConfig = ...

源码：

```python
type ProviderConfig = (
    OpenAICompatibleProviderConfig | AnthropicProviderConfig | OpenAICodexProviderConfig
)
```

这是 Python 3.12+ 的 type alias 语法。

意思是：

```text
ProviderConfig 可以是这三种 provider config 之一。
```

后面很多函数都写：

```python
provider: ProviderConfig
```

表示它可以处理多种 provider 类型。

## 14. ScopedModelConfig

源码：

```python
@dataclass(frozen=True, slots=True)
class ScopedModelConfig:
    """A provider/model pair enabled for quick model cycling."""

    provider: str
    model: str
```

它表示 TUI 快速切换模型时的 favorite。

JSON 里类似：

```json
{
  "scoped_models": [
    {"provider": "openai", "model": "gpt-5.5"},
    {"provider": "local", "model": "qwen"}
  ]
}
```

这个概念是后续对 Pi scoped models 的对齐。

## 15. ProviderSettings

源码：

```python
@dataclass(frozen=True, slots=True)
class ProviderSettings:
    """Tau provider settings loaded from Tau home."""

    default_provider: str = DEFAULT_PROVIDER_NAME
    providers: tuple[ProviderConfig, ...] = field(
        default_factory=lambda: builtin_provider_configs()
    )
    scoped_models: tuple[ScopedModelConfig, ...] = ()
```

这是整个 `providers.json` 的内存模型。

它包含：

```text
default_provider  默认使用哪个 provider
providers         所有 provider 配置
scoped_models     TUI 快速切换收藏模型
```

如果没有 `providers.json`，Tau 会返回：

```python
ProviderSettings()
```

也就是默认内置 provider 集合。

## 16. get_provider()

源码：

```python
def get_provider(self, name: str | None = None) -> ProviderConfig:
    """Return a configured provider by name."""
    target = name or self.default_provider
    for provider in self.providers:
        if provider.name == target:
            return provider
    raise ProviderConfigError(f"Unknown provider: {target}")
```

如果没有传 name，就取 default provider。

如果找不到，就抛 `ProviderConfigError`。

测试：

```python
with pytest.raises(ProviderConfigError, match="Unknown provider"):
    resolve_provider_selection(ProviderSettings(), provider_name="missing")
```

## 17. ProviderSelection

源码：

```python
@dataclass(frozen=True, slots=True)
class ProviderSelection:
    """Resolved provider/model selection for a Tau run."""

    provider: ProviderConfig
    model: str
```

它表示一次运行最终选定的 provider 和 model。

为什么不只返回 provider？

因为 model 可能来自：

- CLI `--model`
- provider.default_model
- resumed session record

所以 resolution 后要明确记录：

```text
provider 是谁
model 是谁
```

## 18. provider_settings_path()

源码：

```python
def provider_settings_path(paths: TauPaths | None = None) -> Path:
    """Return the durable provider settings path."""
    return (paths or TauPaths()).home / "providers.json"
```

默认位置：

```text
~/.tau/providers.json
```

测试中会传：

```python
TauPaths(home=tmp_path / ".tau")
```

这样不会污染真实用户 home。

## 19. load_provider_settings()

源码：

```python
def load_provider_settings(paths: TauPaths | None = None) -> ProviderSettings:
    """Load durable provider settings, falling back to env-compatible defaults."""
    path = provider_settings_path(paths)
    if not path.exists():
        return ProviderSettings()
    raw = loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ProviderConfigError("Provider settings must be a JSON object")
    return _with_builtin_catalog_models(provider_settings_from_json(raw), paths=paths)
```

逻辑：

1. 找到 providers.json。
2. 如果不存在，返回默认 ProviderSettings。
3. 如果存在，读取 JSON。
4. JSON 顶层必须是 dict。
5. 解析成 ProviderSettings。
6. 合并当前内置 provider catalog。

为什么要合并内置 catalog？

因为 Tau 版本升级后，内置 provider 可能新增模型或 context window。

用户旧文件不应该阻止内置 catalog 更新。

## 20. save_provider_settings()

源码：

```python
def save_provider_settings(settings: ProviderSettings, paths: TauPaths | None = None) -> Path:
    """Write durable provider settings and return the path."""
    path = provider_settings_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with suppress(OSError):
            copy2(path, path.with_suffix(path.suffix + ".bak"))
    _atomic_write_text(path, dumps(settings.to_json(), indent=2, sort_keys=True) + "\n")
    return path
```

逐步看：

### 20.1 创建目录

```python
path.parent.mkdir(parents=True, exist_ok=True)
```

如果 `~/.tau` 不存在，就创建。

`parents=True` 表示父目录也一起创建。

`exist_ok=True` 表示目录已存在也不报错。

### 20.2 写备份

```python
if path.exists():
    with suppress(OSError):
        copy2(path, path.with_suffix(path.suffix + ".bak"))
```

如果原文件存在，先复制成：

```text
providers.json.bak
```

测试验证：

```python
backup = path.with_suffix(path.suffix + ".bak")
assert backup.exists()
```

### 20.3 JSON 格式

```python
dumps(settings.to_json(), indent=2, sort_keys=True) + "\n"
```

`indent=2` 让 JSON 更易读。

`sort_keys=True` 让 key 顺序稳定，方便 diff。

末尾加换行是文本文件好习惯。

### 20.4 atomic write

真正写文件用：

```python
_atomic_write_text(...)
```

## 21. _atomic_write_text()

源码：

```python
def _atomic_write_text(path: Path, text: str) -> None:
    """Write text through a sibling temp file and atomically replace the target."""
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            dir=path.parent,
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(text)
            temp_file.flush()
        temp_path.replace(path)
    except Exception:
        if temp_path is not None:
            with suppress(OSError):
                temp_path.unlink()
        raise
```

为什么不直接：

```python
path.write_text(text)
```

因为直接写可能中途失败，留下半个 JSON 文件。

atomic write 的思路是：

```text
先写临时文件；
写完整后一次性替换目标文件。
```

如果中途失败，就删除临时文件并重新抛异常。

## 22. provider_settings_from_json()

源码：

```python
def provider_settings_from_json(data: dict[str, Any]) -> ProviderSettings:
    """Parse provider settings from JSON-compatible data."""
    default_provider = _string(data.get("default_provider"), "default_provider")
    providers_data = data.get("providers")
    if not isinstance(providers_data, list) or not providers_data:
        raise ProviderConfigError("Provider settings must include at least one provider")
    providers = tuple(_provider_from_json(item) for item in providers_data)
    names = [provider.name for provider in providers]
    if len(set(names)) != len(names):
        raise ProviderConfigError("Provider names must be unique")
    scoped_models = _scoped_models_from_json(data.get("scoped_models"))
    return ProviderSettings(...)
```

这里是 JSON 解析入口。

关键校验：

- `default_provider` 必须是非空字符串。
- `providers` 必须是非空列表。
- provider names 必须唯一。
- scoped_models 单独解析并去重。

## 23. _provider_from_json()

这个函数把单个 provider JSON 转成具体 dataclass。

先判断类型：

```python
provider_type = _string(data.get("type"), "providers[].type")
if provider_type not in {"openai-compatible", "anthropic", "openai-codex"}:
    raise ProviderConfigError(f"Unsupported provider type: {provider_type}")
```

然后读取字段：

```python
name = _string(...)
base_url = _string(...).rstrip("/")
api_key_env = _string(...)
credential_name = _optional_string(...)
models = _string_tuple(...)
default_model = _string(...)
```

如果 default_model 不在 models 里：

```python
if default_model not in models:
    models = (*models, default_model)
```

这是宽容处理。

用户如果忘了把 default_model 写进 models，Tau 会自动补进去。

最后按 provider_type 返回不同 config 类型。

## 24. resolve_provider_selection()

源码：

```python
def resolve_provider_selection(
    settings: ProviderSettings,
    *,
    provider_name: str | None = None,
    model: str | None = None,
) -> ProviderSelection:
    """Resolve the provider and model for a run."""
    provider = settings.get_provider(provider_name)
    selected_model = model or provider.default_model
    if not selected_model:
        raise ProviderConfigError(f"Provider {provider.name} does not define a default model")
    return ProviderSelection(provider=provider, model=selected_model)
```

这个函数决定一次运行用哪个 provider/model。

规则：

```text
provider_name 有传，就用它；
否则用 settings.default_provider。

model 有传，就用它；
否则用 provider.default_model。
```

测试：

```python
selection = resolve_provider_selection(settings)
assert selection.provider.name == "local"
assert selection.model == "qwen"
```

## 25. openai_compatible_config_from_provider()

ProviderConfig 是持久化配置。

真正调用模型还需要 tau_ai 的 runtime config。

源码：

```python
def openai_compatible_config_from_provider(
    provider: OpenAICompatibleProviderConfig,
    *,
    credential_reader: CredentialReader | None = None,
    model: str | None = None,
    thinking_level: ThinkingLevel | None = None,
) -> OpenAICompatibleConfig:
```

它返回：

```python
OpenAICompatibleConfig
```

也就是 `tau_ai` provider 需要的配置。

核心：

```python
api_key = _api_key_from_provider(provider, credential_reader=credential_reader)
base_url = provider.base_url
if provider.name == DEFAULT_PROVIDER_NAME and provider.api_key_env == "OPENAI_API_KEY":
    base_url = environ.get("OPENAI_BASE_URL", provider.base_url)
...
return OpenAICompatibleConfig(
    api_key=api_key,
    base_url=base_url.rstrip("/"),
    headers=provider.headers,
    timeout_seconds=provider.timeout_seconds,
    max_retries=provider.max_retries,
    max_retry_delay_seconds=provider.max_retry_delay_seconds,
    ...
)
```

这里把 durable settings 转成 runtime settings。

## 26. _api_key_from_provider()

源码：

```python
def _api_key_from_provider(
    provider: ProviderConfig,
    *,
    credential_reader: CredentialReader | None,
) -> str:
    if provider.credential_name and credential_reader is not None:
        credential = credential_reader.get(provider.credential_name)
        if credential:
            return credential

    api_key = environ.get(provider.api_key_env)
    if api_key:
        return api_key
    credential_hint = f" or run /login {provider.name}" if provider.credential_name else ""
    raise RuntimeError(f"Missing provider API key. Set {provider.api_key_env}{credential_hint}.")
```

查找顺序：

1. 如果有 `credential_name` 且 credential reader 里有 key，优先用存储凭据。
2. 否则查环境变量 `api_key_env`。
3. 都没有就报错。

这解释了为什么 providers.json 不保存 API key。

它只保存：

```text
去哪读 key
```

不是保存 key 本身。

## 27. provider_has_usable_credentials()

源码：

```python
def provider_has_usable_credentials(
    provider: ProviderConfig,
    *,
    credential_reader: CredentialReader | None = None,
) -> bool:
    ...
    return bool(environ.get(provider.api_key_env))
```

这个函数用于判断 provider 是否当前可用。

它会检查：

- stored credentials
- OAuth credentials
- 环境变量

TUI 启动和 model picker 会用类似信息决定哪些 provider/model 可选。

## 28. create_model_provider()

位置：

```text
src/tau_coding/provider_runtime.py
```

源码：

```python
def create_model_provider(
    provider: ProviderConfig,
    *,
    credential_store: FileCredentialStore | None = None,
    model: str | None = None,
    thinking_level: ThinkingLevel | None = None,
) -> ClosableModelProvider:
```

它把 durable provider config 变成真正的 runtime provider。

分支：

```python
if isinstance(provider, AnthropicProviderConfig):
    return AnthropicProvider(...)

if isinstance(provider, OpenAICodexProviderConfig):
    return OpenAICodexProvider(...)

return OpenAICompatibleProvider(...)
```

这一步是 `tau_coding` 和 `tau_ai` 的桥。

`tau_coding` 管配置。

`tau_ai` 管具体 provider streaming。

## 29. CLI providers 命令

测试：

```python
result = CliRunner().invoke(app, ["providers"])
```

输出包含：

```text
*   openai          openai-compatible   gpt-5.5
    openai-codex    openai-codex        gpt-5.5
    anthropic       anthropic           claude-sonnet-4-6
```

`*` 表示默认 provider。

这个命令让用户能看到当前 provider settings。

## 30. CLI setup 命令

Phase 18 加了轻量 setup 流程。

示例：

```text
tau --provider local \
  --base-url http://localhost:11434/v1 \
  --api-key-env LOCAL_API_KEY \
  --timeout-seconds 120 \
  --max-retries 2 \
  --max-retry-delay-seconds 0.5 \
  --model qwen \
  setup
```

测试验证写入：

```python
assert settings.default_provider == "local"
assert provider.base_url == "http://localhost:11434/v1"
assert provider.api_key_env == "LOCAL_API_KEY"
assert provider.default_model == "qwen"
assert provider.timeout_seconds == 120
assert provider.max_retries == 2
assert provider.max_retry_delay_seconds == 0.5
```

注意 setup 保存 provider metadata。

custom provider 的 key 仍然来自环境变量。

## 31. /model 命令如何使用 provider settings

Phase 15 讲过 `/model`。

现在它会先：

```python
refresh_error = _refresh_provider_settings(context.session)
```

也就是刷新 provider settings。

然后：

```python
available_models = set(context.session.available_models)
if available_models and model not in available_models:
    ...
context.session.set_model(model)
```

这保证用户刚更新 providers.json 或 login 后，model 命令看到的是最新配置。

## 32. TUI 启动如何选择 provider/model

`run_tui_app()` 里：

```python
provider_settings = load_provider_settings()
...
selection = _resolve_tui_startup_selection(
    provider_settings,
    record=record,
    provider_name=provider_name,
    model=model,
    explicit_resume=session_id is not None,
)
```

然后：

```python
provider = create_model_provider(
    selection.provider,
    model=selection.model,
    thinking_level=DEFAULT_THINKING_LEVEL,
)
```

如果缺少 key：

```python
provider = LoginRequiredProvider(startup_message)
runtime_provider_config = None
```

也就是说 TUI 可以先打开，再提示用户 `/login`。

这比启动时直接崩掉更友好。

## 33. 为什么 settings 写入前要重新 load

源码里有：

```python
def _load_provider_settings_for_write(...):
    if provider_settings_path(paths).exists():
        return load_provider_settings(paths)
    if fallback_settings is not None:
        return fallback_settings
    return load_provider_settings(paths)
```

这个函数用于：

- `save_default_provider_model`
- `toggle_saved_scoped_model`
- `upsert_saved_provider`

目的：

```text
写入前尽量读取磁盘上的最新 providers.json。
```

这样可以减少覆盖别人刚写入的配置。

测试里也有“preserves newer provider file changes”的场景。

## 34. validation helper

文件底部有很多 `_string()`、`_positive_float()` 等 helper。

例如：

```python
def _positive_float(value: object, field_name: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ProviderConfigError(...)
    converted = float(value)
    if converted <= 0:
        raise ProviderConfigError(...)
    return converted
```

为什么特别排除 bool？

因为 Python 里：

```python
isinstance(True, int)
```

结果是 True。

但配置里的 timeout 不应该接受 `true`。

所以代码写：

```python
or isinstance(value, bool)
```

来拒绝 bool。

这是 Python 里很容易忽略的细节。

## 35. Phase 18 的测试重点

主要测试：

```text
tests/test_provider_config.py
tests/test_provider_runtime.py
tests/test_cli.py
tests/test_commands.py
tests/test_coding_session.py
tests/test_tui_app.py
```

覆盖内容包括：

- 没有 providers.json 时使用内置默认 provider settings
- save/load round trip
- 覆盖写入时生成 `.bak`
- JSON 解析和字段校验
- default provider/model resolution
- API key 从 stored credentials 或 env 读取
- runtime provider config 转换
- timeout/retry 传给 tau_ai provider
- CLI `providers` 输出
- CLI `setup` 写入 provider settings
- `/model` 和 TUI model picker 读取最新 provider settings
- `/login` 后刷新 provider settings
- scoped models 去重和持久化

## 36. Python 小白应该掌握的语法点

### 36.1 frozen dataclass + replace

```python
updated_provider = replace(provider, default_model=model)
```

因为 frozen dataclass 不能直接改字段，所以用 `replace()` 创建新对象。

### 36.2 JSON loads/dumps

```python
raw = loads(path.read_text(encoding="utf-8"))
text = dumps(settings.to_json(), indent=2, sort_keys=True)
```

读 JSON 和写 JSON 是配置系统常见操作。

### 36.3 isinstance(value, int | float)

这是 Python 新写法，表示：

```text
value 是 int 或 float
```

### 36.4 dict.fromkeys 去重

```python
return tuple(dict.fromkeys(values))
```

它可以在保持顺序的同时去重。

例如：

```python
("a", "b", "a") -> ("a", "b")
```

### 36.5 with suppress(OSError)

```python
with suppress(OSError):
    temp_path.unlink()
```

表示如果删除临时文件失败，也不再抛出这个 OSError。

## 37. 你读源码时的推荐顺序

建议这样读：

1. `ProviderConfigError`
2. `OpenAICompatibleProviderConfig`
3. `ProviderSettings`
4. `ProviderSettings.get_provider()`
5. `provider_settings_path()`
6. `load_provider_settings()`
7. `save_provider_settings()`
8. `_atomic_write_text()`
9. `provider_settings_from_json()`
10. `_provider_from_json()`
11. `resolve_provider_selection()`
12. `_api_key_from_provider()`
13. `openai_compatible_config_from_provider()`
14. `provider_runtime.create_model_provider()`
15. CLI `providers/setup`
16. session/TUI 里的 provider selection

这样读会先掌握数据模型，再看文件读写，最后看 runtime 和 UI 怎么用。

## 38. Phase 18 用一句话总结

Phase 18 的价值是：在 `tau_coding` 中建立持久化 provider settings 模型，把 provider 名称、base URL、模型列表、默认模型、credential 来源、timeout、retry、context window 和 scoped models 等配置保存到 `~/.tau/providers.json`，再在 CLI/TUI/session 启动时解析成 `ProviderSelection` 和 runtime `ModelProvider`，同时保持 `tau_agent` 只依赖已经准备好的 provider 对象，不关心本地配置文件和凭据来源。

## 39. 我的问题与推荐回答

问题：为什么 Tau 要把 provider 配置分成 `ProviderConfig`、`ProviderSettings`、`ProviderSelection` 和 runtime `ModelProvider`，而不是只用一个大对象？

我的推荐回答：

因为它们处在不同阶段。`ProviderConfig` 描述单个 provider 的持久化元数据，适合写进 `providers.json`；`ProviderSettings` 描述整个配置文件，包括默认 provider 和 scoped models；`ProviderSelection` 是一次启动或一次 session 最终解析出的 provider/model 组合；runtime `ModelProvider` 才是真正会发请求的对象。分开以后，配置读写、默认选择、凭据解析和模型调用不会混在一起，`tau_agent` 也可以继续只接收 runtime provider，而不依赖 Tau 的本地配置系统。
