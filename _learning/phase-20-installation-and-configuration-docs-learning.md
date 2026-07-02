# Phase 20 学习笔记：Installation and Configuration Docs

对应架构文档：`dev-notes/architecture/phase-20-installation-docs.md`

当前源码与文档重点：

- `pyproject.toml`
- `README.md`
- `src/tau_coding/cli.py`
- `src/tau_coding/paths.py`
- `src/tau_coding/provider_config.py`
- `website/src/content/docs/quickstart.md`
- `website/src/content/docs/reference/cli.md`
- `website/src/content/docs/reference/configuration.md`
- `website/src/content/docs/guides/providers-and-models.md`
- `website/astro.config.mjs`
- `website/package.json`
- `tests/test_cli.py`

## 1. 这一阶段到底在做什么

Phase 20 不主要增加 agent 的推理能力。

它解决的是另一个问题：

```text
Tau 已经能跑了，但用户怎么安装？
安装后命令叫什么？
第一次怎么配置模型？
配置文件放在哪里？
会话、技能、prompt template 放在哪里？
这些规则应该在哪里被文档说清楚？
```

所以 Phase 20 是一次 packaging 和 user-facing docs 的补齐。

从学习角度看，这一阶段很重要，因为它把一个“源码项目”变成一个“普通用户能安装和使用的命令行工具”。

## 2. 阶段文档和当前源码的差异

架构文档写到：

```text
docs/installation.md
docs/configuration.md
docs/getting-started.md
docs/index.md
docs/providers.md
mkdocs.yml
```

但是当前仓库状态已经变化：

```text
docs/
└── assets/tau-header.svg

website/src/content/docs/
├── quickstart.md
├── reference/cli.md
├── reference/configuration.md
├── guides/providers-and-models.md
...
```

也就是说，Phase 20 当时的意图是：

```text
补安装文档和配置文档
```

当前实现形态是：

```text
README + Astro/Starlight 网站文档
```

所以我们学习时不要死记 `docs/installation.md` 这个旧路径。

应该抓住本质：

```text
Phase 20 让 Tau 的安装入口、CLI 入口、配置文件位置、provider 设置、session 路径变成清楚的用户契约。
```

## 3. Python 项目的安装入口：`pyproject.toml`

先看 `pyproject.toml`。

它是现代 Python 项目的核心配置文件。

很多 Python 新手会把它理解成：

```text
Python 项目的 package.json
```

虽然不完全一样，但可以帮助你快速建立感觉。

它告诉构建工具：

- 这个项目叫什么
- 当前版本是多少
- 需要什么 Python 版本
- 依赖哪些第三方包
- 怎么把源码打包成 wheel
- 安装后生成什么命令

## 4. `[build-system]`：项目用什么工具打包

源码：

```toml
[build-system]
requires = ["hatchling>=1.26"]
build-backend = "hatchling.build"
```

这里的意思是：

```text
构建这个 Python 包时，需要 hatchling
真正执行构建逻辑的是 hatchling.build
```

### 4.1 什么是 hatchling

`hatchling` 是 Python 的打包构建后端。

你可以先把它理解成：

```text
负责把 src/ 里的 Python 源码打成可安装包的工具
```

当你运行：

```bash
uv build
```

或者发布到 PyPI 时，构建系统会根据这里的配置来打包。

## 5. `[project]`：包的基本信息

源码：

```toml
[project]
name = "tau-ai"
version = "0.1.0"
description = "A Python implementation of a minimalist Pi-style coding-agent harness."
readme = "README.md"
license = "MIT"
requires-python = ">=3.14"
```

这里有几个关键点。

### 5.1 包名和命令名可以不一样

包名是：

```text
tau-ai
```

但安装后命令是：

```text
tau
```

这两个不是一回事。

包名用于安装：

```bash
uv tool install tau-ai
```

命令名用于运行：

```bash
tau
```

### 5.2 `requires-python = ">=3.14"`

这表示 Tau 要求 Python 3.14 或更高版本。

如果你的环境 Python 版本太低，包管理器应该拒绝安装或重新选择合适解释器。

## 6. `dependencies`：运行 Tau 需要哪些包

源码：

```toml
dependencies = [
    "anyio>=4.0",
    "httpx>=0.27",
    "pydantic>=2.0",
    "rich>=13.0",
    "textual>=1.0",
    "typer>=0.12",
]
```

这些是 Tau 运行时依赖。

### 6.1 `anyio`

`anyio` 是异步并发库。

你可以把它理解成：

```text
让 async/await 代码更容易在命令行程序里运行
```

在 `src/tau_coding/cli.py` 里能看到：

```python
import anyio
```

以及：

```python
anyio.run(run_openai_tui, ...)
anyio.run(run_openai_print_mode, ...)
```

普通 Python 程序入口是同步函数。

但 Tau 的 agent、provider streaming、tool call 很多都是 async 的。

所以 CLI 入口需要一个东西把同步世界接到异步世界：

```text
Typer 命令函数
  -> anyio.run(...)
      -> async Tau runtime
```

### 6.2 `httpx`

`httpx` 是 HTTP 客户端。

Tau 用它请求 OpenAI-compatible API、Anthropic API 等模型服务。

Phase 20 不改 provider 逻辑，但安装文档必须告诉用户 provider 怎么配置。

### 6.3 `pydantic`

`pydantic` 用来做类型模型和数据校验。

前面阶段里它已经大量出现，例如：

- message schema
- event schema
- tool schema
- session entry JSONL

配置文件读出来也是普通 JSON。

Tau 需要把 JSON 转成可靠的 Python 对象，并在字段不合法时给出错误。

### 6.4 `rich`

`rich` 用于终端美化输出。

例如 print mode 的渲染、错误输出、工具调用显示等。

### 6.5 `textual`

`textual` 是 TUI 框架。

Tau 的交互式界面用 Textual。

但注意架构边界：

```text
Textual 属于 tau_coding/tui
不应该进入 tau_agent 核心层
```

Phase 20 的文档要帮助用户知道：

```bash
tau
```

默认会打开 Textual TUI。

### 6.6 `typer`

`typer` 是命令行框架。

Tau 用它声明：

- 命令名
- 参数
- flag
- help 文本
- `--version`

`src/tau_coding/cli.py` 里：

```python
import typer

app = typer.Typer(
    name="tau",
    help="Tau coding-agent harness.",
    add_completion=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
```

你可以理解为：

```text
app 是整个 tau CLI 应用对象
```

## 7. `[project.scripts]`：为什么安装后能运行 `tau`

这是 Phase 20 最关键的一小段。

源码：

```toml
[project.scripts]
tau = "tau_coding.cli:app"
```

它的意思是：

```text
安装这个包时，生成一个叫 tau 的命令
这个命令入口指向 tau_coding.cli 模块里的 app 对象
```

拆开看：

```text
tau_coding.cli:app
```

含义是：

- `tau_coding`：Python package
- `cli`：`src/tau_coding/cli.py`
- `app`：文件里的 Typer 应用对象

所以用户运行：

```bash
tau --version
```

本质上会进入：

```python
src/tau_coding/cli.py
```

里面的：

```python
app = typer.Typer(...)
```

这就是“安装文档”和“源码入口”的连接点。

## 8. `uv tool install tau-ai` 到底做了什么

README 和 Quickstart 都推荐：

```bash
uv tool install tau-ai
```

你可以把它理解成：

```text
从 PyPI 安装 tau-ai 这个 Python 包
给它创建独立工具环境
把 tau 命令暴露到 PATH
```

这和开发模式下的：

```bash
uv run tau
```

不一样。

### 8.1 普通用户安装

普通用户一般用：

```bash
uv tool install tau-ai
tau --version
```

这个路径不要求用户克隆源码。

### 8.2 开发者运行

开发者在源码仓库里用：

```bash
uv sync --dev
uv run tau --version
```

这里的 `uv run tau` 是从当前项目环境里运行命令。

对于我们学习源码，通常用开发者方式。

## 9. CLI 入口：`src/tau_coding/cli.py`

Phase 20 要解释安装命令，必须看 `cli.py`。

这里定义了 Tau 的外层命令行为。

## 10. `Typer` 应用对象

源码：

```python
app = typer.Typer(
    name="tau",
    help="Tau coding-agent harness.",
    add_completion=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
```

### 10.1 `name="tau"`

命令名叫 `tau`。

### 10.2 `help=...`

当用户运行：

```bash
tau --help
```

Typer 会显示帮助信息。

### 10.3 `add_completion=False`

关闭自动 shell completion。

这也对应 Phase 20 文档里说的：

```text
currently disabled shell completion
```

### 10.4 `context_settings`

源码：

```python
context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
```

这表示 Typer 对未知参数更宽松。

Tau 这样做，是因为它有一些“伪子命令”：

```bash
tau sessions
tau export ...
tau providers
tau setup
```

当前实现不是用多个 `@app.command()` 定义，而是在 callback 里手动解析 positional args。

## 11. `@app.callback(invoke_without_command=True)`

源码：

```python
@app.callback(invoke_without_command=True)
def main(...):
    ...
```

这表示：

```text
即使用户没有输入子命令，也执行 main
```

所以：

```bash
tau
```

也会进入 `main()`。

在 `main()` 里再判断用户到底想做什么。

## 12. `Annotated` 是什么

`main()` 里有很多这样的写法：

```python
prompt_option: Annotated[
    str | None,
    typer.Option("--prompt", "-p", help="Prompt to run in non-interactive print mode."),
] = None
```

`Annotated` 来自 Python 标准库 `typing`。

它的作用是：

```text
给类型额外附加元数据
```

这里的基础类型是：

```python
str | None
```

附加给 Typer 的 CLI 信息是：

```python
typer.Option("--prompt", "-p", help="...")
```

所以 Typer 既知道：

```text
这是一个可选字符串
```

也知道：

```text
它对应 CLI 参数 --prompt 或 -p
```

## 13. `Path` 是什么

`cli.py` 和 `paths.py` 都大量使用：

```python
from pathlib import Path
```

`Path` 是 Python 标准库里的路径对象。

比字符串路径更好用。

例如：

```python
cwd or Path.cwd()
```

表示：

```text
如果用户传了 --cwd 就用用户传的
否则用当前工作目录
```

再比如：

```python
Path(session_ref).expanduser()
```

表示把：

```text
~/xxx
```

展开成真实用户目录。

## 14. `tau --version`

`main()` 里：

```python
if version:
    typer.echo(f"tau {__version__}")
    raise typer.Exit()
```

当用户运行：

```bash
tau --version
```

它会打印版本并退出。

`typer.echo()` 类似 `print()`，但更适合命令行工具。

`raise typer.Exit()` 表示告诉 Typer：

```text
当前命令正常结束
```

## 15. `tau` 默认打开 TUI

如果用户没有传 `-p/--prompt`，也没有输入 `sessions/export/providers/setup` 这些命令，代码会走到：

```python
anyio.run(
    run_openai_tui,
    model,
    cwd or Path.cwd(),
    resume,
    new_session,
    provider,
    auto_compact_threshold,
    initial_prompt,
)
```

这对应文档里的：

```bash
tau
```

默认打开交互式 TUI。

注意这里函数名叫 `run_openai_tui`，但当前它不只是 OpenAI。

它会把参数继续交给：

```python
run_tui_app(...)
```

后续 provider 选择在 TUI/session 层完成。

## 16. `tau -p "..."` 是 print mode

如果用户传了：

```bash
tau -p "summarize the architecture"
```

代码会走到：

```python
ok = anyio.run(run_openai_print_mode, prompt, model, cwd or Path.cwd(), output, provider)
```

print mode 是一次性运行：

```text
输入一个 prompt
模型流式响应
输出到 stdout/stderr
结束
```

它适合：

- 脚本
- CI
- 快速问答
- 管道处理

## 17. `tau sessions`

源码中：

```python
if prompt_option is None and command == "sessions" and len(positional_args) == 1:
    render_session_list(SessionManager().list_sessions())
    raise typer.Exit()
```

意思是：

```text
如果用户输入 tau sessions，就列出 session index
```

对应文档：

```bash
tau sessions
```

## 18. `tau providers`

源码中：

```python
if prompt_option is None and command == "providers" and len(positional_args) == 1:
    providers_command()
    raise typer.Exit()
```

`providers_command()` 又会调用：

```python
render_provider_settings(load_provider_settings(), credential_reader=FileCredentialStore())
```

也就是：

```text
读取 provider 配置
读取凭据状态
打印每个 provider 的状态
```

这对应文档里的：

```bash
tau providers
```

用户可以看到当前默认 provider、模型、认证来源。

## 19. `tau setup`

源码中：

```python
if prompt_option is None and command == "setup" and len(positional_args) == 1:
    setup_command(...)
    raise typer.Exit()
```

文档给的例子：

```bash
tau --provider local \
  --base-url http://localhost:11434/v1 \
  --api-key-env LOCAL_API_KEY \
  --model qwen \
  setup
```

这个命令会创建或更新 OpenAI-compatible provider 配置。

## 20. `setup_command()` 怎么写配置

源码：

```python
settings = load_provider_settings()
provider = OpenAICompatibleProviderConfig(...)
updated = upsert_openai_compatible_provider(settings, provider, set_default=set_default)
path = save_provider_settings(updated)
```

分成四步：

```text
1. 读取旧配置
2. 创建新的 provider 配置对象
3. 合并到 settings
4. 写回 providers.json
```

如果环境变量没有设置：

```python
if provider.api_key_env not in environ:
    typer.echo(f"Set {provider.api_key_env} before running Tau with this provider.", err=True)
```

它不会失败，只会提示用户：

```text
你还需要设置 API key 环境变量
```

## 21. 配置路径：`TauPaths`

`src/tau_coding/paths.py` 定义了 Tau 的路径约定。

核心类：

```python
@dataclass(frozen=True, slots=True)
class TauPaths:
    home: Path = field(default_factory=lambda: Path.home() / ".tau")
    agents_home: Path = field(default_factory=lambda: Path.home() / ".agents")
```

默认：

```text
Tau home     = ~/.tau
Agents home  = ~/.agents
```

### 21.1 `dataclass`

`dataclass` 是 Python 标准库功能。

它适合写“主要用来存数据的类”。

普通类可能要自己写：

```python
__init__
__repr__
__eq__
```

`@dataclass` 会帮你生成。

### 21.2 `frozen=True`

表示对象创建后不希望再改字段。

例如：

```python
paths = TauPaths()
```

`paths.home` 理论上不应该被重新赋值。

路径配置对象更像一个稳定快照。

### 21.3 `slots=True`

表示优化对象内存布局，也减少随意新增属性。

对新手来说，可以先理解为：

```text
让这个 dataclass 更轻量、更严格
```

### 21.4 `field(default_factory=...)`

源码：

```python
home: Path = field(default_factory=lambda: Path.home() / ".tau")
```

为什么不用：

```python
home: Path = Path.home() / ".tau"
```

因为 `default_factory` 会在创建对象时计算默认值。

路径依赖当前用户目录，适合动态计算。

## 22. `~/.tau/` 里有什么

当前公开文档 `reference/configuration.md` 写到：

```text
~/.tau/
├── providers.json
├── credentials.json
├── settings.json
├── tui.json
├── sessions/
├── skills/
├── prompts/
├── AGENTS.md
└── logs/
```

这和源码对应：

- `TauPaths.sessions_dir`
- `TauPaths.logs_dir`
- `TauPaths.user_skills_dir`
- `TauPaths.user_prompts_dir`
- `provider_settings_path()`
- `credentials_path()`
- `shell_settings_path()`

Phase 20 的价值之一，就是把这些“隐藏在源码里的约定”写成用户能看的文档。

## 23. `providers.json` 的路径

`provider_config.py` 里：

```python
def provider_settings_path(paths: TauPaths | None = None) -> Path:
    return (paths or TauPaths()).home / "providers.json"
```

如果不传 `paths`：

```python
TauPaths().home
```

默认是：

```text
~/.tau
```

所以 provider 配置文件是：

```text
~/.tau/providers.json
```

## 24. `load_provider_settings()`

源码：

```python
def load_provider_settings(paths: TauPaths | None = None) -> ProviderSettings:
    path = provider_settings_path(paths)
    if not path.exists():
        return ProviderSettings()
    raw = loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ProviderConfigError("Provider settings must be a JSON object")
    return _with_builtin_catalog_models(provider_settings_from_json(raw), paths=paths)
```

一步一步看：

### 24.1 找到配置路径

```python
path = provider_settings_path(paths)
```

### 24.2 文件不存在就返回默认配置

```python
if not path.exists():
    return ProviderSettings()
```

也就是说，第一次运行 Tau 时，即使没有 `providers.json`，Tau 也有内置 provider catalog。

### 24.3 读取 JSON

```python
raw = loads(path.read_text(encoding="utf-8"))
```

这里有两个标准库知识点：

- `Path.read_text()` 读取文本文件
- `json.loads()` 把 JSON 字符串转成 Python 数据

### 24.4 校验顶层必须是 object

```python
if not isinstance(raw, dict):
    raise ProviderConfigError(...)
```

JSON 顶层必须类似：

```json
{
  "default_provider": "openai",
  "providers": []
}
```

不能是：

```json
[]
```

## 25. `save_provider_settings()`

源码：

```python
def save_provider_settings(settings: ProviderSettings, paths: TauPaths | None = None) -> Path:
    path = provider_settings_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with suppress(OSError):
            copy2(path, path.with_suffix(path.suffix + ".bak"))
    _atomic_write_text(path, dumps(settings.to_json(), indent=2, sort_keys=True) + "\n")
    return path
```

这段非常值得学习。

### 25.1 创建目录

```python
path.parent.mkdir(parents=True, exist_ok=True)
```

如果 `~/.tau` 不存在，就创建。

- `parents=True`：父目录也一起创建
- `exist_ok=True`：目录已存在也不报错

### 25.2 写入前备份

```python
if path.exists():
    with suppress(OSError):
        copy2(path, path.with_suffix(path.suffix + ".bak"))
```

如果旧文件存在，先复制成：

```text
providers.json.bak
```

`copy2` 来自标准库 `shutil`。

它复制文件内容，也尽量保留元数据。

`suppress(OSError)` 来自 `contextlib`。

它表示：

```text
如果备份失败，不让整个保存流程崩掉
```

### 25.3 原子写入

```python
_atomic_write_text(...)
```

虽然这段函数在后面定义，但从名字就能知道：

```text
不要直接半截写坏目标文件
先写临时文件，再替换
```

配置文件保存很适合用原子写入。

## 26. `ProviderSettings`

源码：

```python
@dataclass(frozen=True, slots=True)
class ProviderSettings:
    default_provider: str = DEFAULT_PROVIDER_NAME
    providers: tuple[ProviderConfig, ...] = field(
        default_factory=lambda: builtin_provider_configs()
    )
    scoped_models: tuple[ScopedModelConfig, ...] = ()
```

它代表整个 `providers.json`。

主要字段：

- `default_provider`：默认 provider 名字
- `providers`：所有 provider 配置
- `scoped_models`：用户收藏的快捷切换模型

这里用了 `tuple` 而不是 `list`。

这和 `frozen=True` 配合，表示配置对象更偏不可变快照。

要修改时通常返回一个新对象，而不是原地改。

## 27. `OpenAICompatibleProviderConfig`

源码里这个 dataclass 表示一个 OpenAI-compatible provider。

字段包括：

- `name`
- `base_url`
- `api_key_env`
- `credential_name`
- `models`
- `default_model`
- `context_windows`
- `headers`
- `timeout_seconds`
- `max_retries`
- `max_retry_delay_seconds`
- `thinking_levels`
- `thinking_models`
- `thinking_default`
- `thinking_parameter`

文档里的 JSON 示例：

```json
{
  "name": "local",
  "type": "openai-compatible",
  "base_url": "http://localhost:11434/v1",
  "api_key_env": "LOCAL_API_KEY",
  "models": ["qwen", "llama"],
  "default_model": "qwen"
}
```

就是这个 dataclass 的持久化形态。

## 28. `to_json()` 方法

每个 provider config 都有：

```python
def to_json(self) -> dict[str, Any]:
    ...
```

这个方法负责把 Python 对象转成 JSON 友好的 dict。

为什么需要它？

因为 Python 里有些类型不能直接写 JSON。

例如：

```python
("gpt-5.5", "gpt-5.4")
```

这是 tuple。

JSON 没有 tuple，只有 array。

所以代码会写：

```python
"models": list(self.models)
```

把 tuple 转成 list。

## 29. `ProviderConfig` union

源码：

```python
type ProviderConfig = (
    OpenAICompatibleProviderConfig | AnthropicProviderConfig | OpenAICodexProviderConfig
)
```

这是 Python 3.12+ 的 type alias 语法。

意思是：

```text
ProviderConfig 可以是三种 provider config 之一
```

这让函数可以写：

```python
def provider_kind(provider: ProviderConfig) -> ProviderKind:
    ...
```

也就是：

```text
这个函数接收任意一种 provider config
```

## 30. README 在 Phase 20 里的作用

README 当前已经包含：

- Tau 是什么
- 三层架构：`tau_ai`、`tau_agent`、`tau_coding`
- 安装方式：`uv tool install tau-ai`
- 开发方式：`uv sync --dev`
- 运行方式：`tau`、`tau -p`
- provider 初始配置：`/login`
- 文档站链接

README 是用户打开仓库最先看到的入口。

所以 Phase 20 不是只写深层参考文档，也要让 README 给出最短路径：

```text
安装 -> 运行 -> 登录 provider -> 开始使用
```

## 31. 当前网站文档结构

当前项目不用 MkDocs，而是：

```text
website/
├── package.json
├── astro.config.mjs
└── src/content/docs/
```

`website/package.json` 里：

```json
{
  "scripts": {
    "dev": "astro dev",
    "build": "astro build",
    "preview": "astro preview"
  },
  "dependencies": {
    "@astrojs/starlight": "^0.36.0",
    "astro": "^5.14.0",
    "sharp": "^0.34.0"
  }
}
```

这里不是 Python 包，而是前端文档站。

### 31.1 Astro

Astro 是静态网站框架。

当前 Tau 用它生成文档网站。

### 31.2 Starlight

Starlight 是 Astro 的文档站主题/框架。

它适合做类似：

```text
左侧导航 + 文档内容 + 搜索
```

的网站。

### 31.3 `sharp`

`sharp` 是图片处理库。

通常用于构建时优化图片。

## 32. `astro.config.mjs`

这个文件配置网站。

里面的：

```js
starlight({
  title: "Tau",
  sidebar: [...]
})
```

定义文档站标题和侧边栏。

Phase 20 的安装/配置文档在当前网站里主要对应：

- `quickstart.md`
- `reference/cli.md`
- `reference/configuration.md`
- `guides/providers-and-models.md`

## 33. Quickstart 文档说什么

`website/src/content/docs/quickstart.md` 是新用户路径。

结构是：

```text
1. Install Tau
2. Connect a model
3. Start a session
4. Come back later
One-shot mode
Where to go next
```

这正好对应用户第一次使用 Tau 的流程。

## 34. CLI reference 说什么

`website/src/content/docs/reference/cli.md` 是命令参考。

它列出：

- `tau`
- `tau "<prompt>"`
- `tau sessions`
- `tau export <ref>`
- `tau providers`
- `tau setup`

以及 flags：

- `-p/--prompt`
- `-m/--model`
- `--provider`
- `--cwd`
- `-o/--output`
- `--resume`
- `--new-session`
- `--auto-compact-threshold`
- `--version`

这和 `src/tau_coding/cli.py` 的 `main()` 参数对应。

## 35. Configuration reference 说什么

`website/src/content/docs/reference/configuration.md` 说明：

- `~/.tau/` 文件布局
- `providers.json` 结构
- `credentials.json` 和环境变量的关系
- `settings.json` shell prefix
- `tui.json` 主题和快捷键
- session 存储路径
- skills/prompts/project context 资源发现
- context accounting

它是 Phase 20 “配置文档”的当前版本。

## 36. Providers guide 说什么

`website/src/content/docs/guides/providers-and-models.md` 说明：

- provider 是模型服务
- model 是具体模型
- `/login` 保存凭据
- `/logout` 删除凭据
- `/model` 切换模型
- `tau setup` 添加本地或自定义 OpenAI-compatible provider
- credentials 优先于 env var

它把源码里的 provider config 行为翻译成用户操作。

## 37. 测试如何覆盖 Phase 20

架构文档说这个阶段可以用：

```bash
uv run tau --version
uv build
uv run --group docs mkdocs build --strict
```

但当前仓库已经不是 MkDocs。

当前更贴近源码的验证包括：

```bash
uv run tau --version
uv build
cd website && bun run build
uv run pytest tests/test_cli.py
```

其中 `tests/test_cli.py` 覆盖了很多 Phase 20 相关行为。

例如：

```python
def test_providers_command_lists_default_provider(...):
    ...
```

验证：

```bash
tau providers
```

能列出默认 provider。

再比如：

```python
def test_setup_command_writes_provider_settings(...):
    ...
```

验证：

```bash
tau --provider local ... setup
```

会写入 provider settings。

## 38. `monkeypatch` 是什么

测试里经常看到：

```python
monkeypatch.setenv("HOME", str(tmp_path))
```

`monkeypatch` 是 pytest 提供的测试工具。

这里用来临时修改环境变量。

为什么要改 `HOME`？

因为真实代码默认写：

```text
~/.tau/providers.json
```

测试不能真的写你的用户目录。

所以测试把 `HOME` 改成临时目录：

```text
tmp_path
```

这样代码以为自己在写：

```text
~/.tau/providers.json
```

实际写到测试临时目录里。

## 39. `CliRunner` 是什么

测试里有：

```python
result = CliRunner().invoke(app, ["providers"])
```

`CliRunner` 来自 Typer 底层的 Click 测试工具。

它可以在测试里模拟命令行调用。

不用真的打开终端运行：

```bash
tau providers
```

而是在 Python 测试进程里调用 CLI app。

## 40. Phase 20 的架构边界

这阶段不应该修改：

- `tau_agent` agent loop
- `tau_agent` tool 协议
- `tau_ai` provider streaming 协议

它主要落在：

```text
tau_coding
README
website docs
pyproject packaging metadata
```

也就是说：

```text
核心 agent 能力不变
用户安装和配置的入口更清楚
```

这是一个非常典型的工程阶段。

不是所有重要阶段都必须增加新算法。

有些阶段是在补“用户能不能真正用起来”的最后一公里。

## 41. 小白必须分清的几组概念

### 41.1 包名不是命令名

安装包：

```text
tau-ai
```

运行命令：

```text
tau
```

中间靠：

```toml
[project.scripts]
tau = "tau_coding.cli:app"
```

连接。

### 41.2 开发运行不是安装运行

开发运行：

```bash
uv run tau
```

安装后运行：

```bash
tau
```

前者使用当前 checkout 的项目环境。

后者使用工具安装后的环境。

### 41.3 配置文件不是凭据文件

Provider 元数据在：

```text
~/.tau/providers.json
```

API key / OAuth token 在：

```text
~/.tau/credentials.json
```

这样可以避免把敏感凭据混进普通 provider 配置。

### 41.4 `tau setup` 不是 `/login`

`tau setup` 是 CLI 命令，主要创建 OpenAI-compatible provider 配置。

`/login` 是 TUI 内部 slash command，用于保存 built-in provider 的凭据。

### 41.5 `README` 和网站文档不是重复

README 负责最快上手。

网站文档负责完整解释。

Phase 20 需要二者都清楚。

## 42. 运行验证

Phase 20 相关验证建议：

```bash
uv run tau --version
uv build
uv run pytest tests/test_cli.py
```

如果要验证当前网站：

```bash
cd website
bun run build
```

注意：架构文档里的 `mkdocs build --strict` 是旧文档系统的验证方式，当前仓库已经迁移到 Astro/Starlight。

## 43. 用一句话总结 Phase 20

Phase 20 的价值是：把 Tau 从“源码里能运行的 Python 项目”推进成“用户可以通过 `uv tool install tau-ai` 安装、通过 `tau` 命令启动、通过清晰文档理解 provider/session/skills/config 文件位置的工具”。

## 44. 我的问题与推荐回答

问题：为什么 Phase 20 看起来主要是文档和 packaging，却仍然是架构路线里的重要阶段？

我的推荐回答：

因为一个 coding agent 不只是内部 agent loop 能跑就够了，还必须让用户知道如何安装、如何启动、如何配置 provider、配置文件写在哪里、session 保存在哪里，以及出现问题时该看哪个命令或文档。Phase 20 把 `pyproject.toml` 的 `tau` console script、`tau_coding.cli` 的 Typer 入口、`~/.tau` 的路径约定、`providers.json` 的读写逻辑和公开文档连接起来，让 Tau 具备作为真实命令行工具被安装和使用的基本形态。
