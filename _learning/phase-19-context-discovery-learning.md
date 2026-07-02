# Phase 19 学习笔记：Project Context Discovery and Reload

对应架构文档：`dev-notes/architecture/phase-19-context-discovery.md`

主要源码：

- `src/tau_coding/context.py`
- `src/tau_coding/system_prompt.py`
- `src/tau_coding/session.py`
- `src/tau_coding/commands.py`
- `tests/test_context.py`
- `tests/test_system_prompt.py`
- `tests/test_coding_session.py`
- `tests/test_commands.py`

前置阶段：

- Phase 10：`ProjectContextFile` 可以被格式化进 system prompt
- Phase 13：`TauPaths` 和 `TauResourcePaths` 定义了用户/项目资源路径
- Phase 16：资源发现支持 diagnostics
- Phase 18：`/reload` 明确不刷新 provider config
- Phase 19：Tau 自动发现 AGENTS.md 这类项目上下文文件

## 1. 这一阶段到底在做什么

Phase 19 让 Tau 自动发现项目说明文件。

主要文件名是：

```text
AGENTS.md
```

这些文件会被放进 system prompt，让模型知道：

- 用户全局规则
- 项目规则
- 当前子目录规则
- `.tau` 和 `.agents` 里的项目说明

一句话：

Phase 19 让 Tau 在启动 session 时自动收集“这个项目希望 agent 遵守什么规则”。

## 2. 为什么这属于 tau_coding

context discovery 依赖：

- 本地文件系统
- 用户 home
- 当前 cwd
- `.tau`
- `.agents`
- 项目根目录判断
- AGENTS.md 文件读取

这些都是 coding-agent app 行为。

所以它在：

```text
src/tau_coding/context.py
```

而不是 `tau_agent`。

`tau_agent` 最终只收到一整段已经构造好的 system prompt 字符串。

## 3. 当前代码和 Phase 19 文档的差异

Phase 19 架构文档里提到：

```text
/context
/status
/resources
```

但当前默认 command registry 已经过 Pi 对齐，不注册这些命令。

当前公开相关信息的主要路径是：

```text
/session   显示 Context files 数量
/reload    重载 resources/context 并显示变化摘要
```

源码里 `_context_command()`、`_resources_command()` 这些 helper 还存在，但没有进入当前默认注册表。

所以学习时要记住：

```text
Phase 19 的核心是 context discovery + reload；
命令可见性以当前 create_default_command_registry() 为准。
```

## 4. context.py 很小，但很关键

完整实现集中在：

```text
src/tau_coding/context.py
```

开头：

```python
from pathlib import Path

from tau_coding.resources import ResourceDiagnostic, TauResourcePaths
from tau_coding.system_prompt import ProjectContextFile
```

这里说明它连接三件事：

```text
Path                 本地文件路径
TauResourcePaths      资源路径配置
ProjectContextFile    system prompt 里的上下文文件对象
ResourceDiagnostic    非致命读取诊断
```

## 5. PROJECT_MARKERS

源码：

```python
PROJECT_MARKERS = (".git", "pyproject.toml", "uv.lock", "setup.py", "package.json")
```

这些文件/目录用于判断项目根目录。

例如当前 cwd 是：

```text
/repo/src/package/module
```

Tau 会往上找：

```text
/repo/src/package/module
/repo/src/package
/repo/src
/repo
```

哪个目录包含这些 marker 之一，就认为它是 project root。

常见 marker：

- `.git`：Git repo
- `pyproject.toml`：Python 项目
- `uv.lock`：uv 管理的 Python 项目
- `setup.py`：传统 Python 包
- `package.json`：Node/前端项目

## 6. discover_project_context()

源码：

```python
def discover_project_context(
    paths: TauResourcePaths | None = None,
) -> tuple[ProjectContextFile, ...]:
    """Discover project instruction files for system prompt context."""
    context_files, _diagnostics = discover_project_context_with_diagnostics(paths)
    return context_files
```

这是简单版 API。

它只返回 context files，不返回 diagnostics。

如果调用方不关心读取问题，只想拿文件，就用这个。

测试 `tests/test_context.py` 用的就是它。

## 7. discover_project_context_with_diagnostics()

源码：

```python
def discover_project_context_with_diagnostics(
    paths: TauResourcePaths | None = None,
) -> tuple[tuple[ProjectContextFile, ...], tuple[ResourceDiagnostic, ...]]:
    """Discover project instruction files and return non-fatal diagnostics."""
    resource_paths = paths or TauResourcePaths()
    context_files: list[ProjectContextFile] = []
    diagnostics: list[ResourceDiagnostic] = []
    for path in _context_file_candidates(resource_paths):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            diagnostics.append(
                ResourceDiagnostic(
                    kind="context",
                    path=path,
                    message=f"could not read context file: {exc}",
                )
            )
            continue
        context_files.append(ProjectContextFile(path=str(path), content=content))
    return tuple(context_files), tuple(diagnostics)
```

这个是宽容版 API。

如果某个 AGENTS.md 读不了，不让整个 session 启动失败。

它会添加：

```python
ResourceDiagnostic(kind="context", ...)
```

然后继续处理其它文件。

这延续了 Phase 16 的设计：

```text
本地资源有问题 -> diagnostic
能加载的继续加载
```

## 8. 为什么返回 tuple

返回类型：

```python
tuple[tuple[ProjectContextFile, ...], tuple[ResourceDiagnostic, ...]]
```

外层 tuple 有两个元素：

```text
第一个：context files
第二个：diagnostics
```

里面也用 tuple，是因为发现结果加载完后不应该随便改。

调用方式：

```python
context_files, diagnostics = discover_project_context_with_diagnostics(paths)
```

这是 Python 常见的解包。

## 9. _context_file_candidates()

源码：

```python
def _context_file_candidates(paths: TauResourcePaths) -> tuple[Path, ...]:
    candidates: list[Path] = [paths.root / "AGENTS.md"]
    if paths.agents_root is not None:
        candidates.append(paths.agents_root / "AGENTS.md")

    if paths.cwd is not None:
        cwd = paths.cwd.expanduser().resolve()
        project_root = _find_project_root(cwd)
        candidates.extend(_ancestor_agents_files(project_root, cwd))
        tau_paths = paths._paths()
        candidates.extend(
            [
                tau_paths.project_tau_dir(cwd) / "AGENTS.md",
                tau_paths.project_agents_dir(cwd) / "AGENTS.md",
            ]
        )

    existing = [path for path in candidates if path.is_file()]
    return tuple(_dedupe_resolved_paths(existing))
```

这是候选文件生成器。

顺序很重要。

## 10. 当前发现顺序

根据代码，发现顺序是：

1. 用户 Tau context：`~/.tau/AGENTS.md`
2. 用户 agents context：`~/.agents/AGENTS.md`
3. project root 的 `AGENTS.md`
4. project root 到 cwd 之间每一层的 `AGENTS.md`
5. cwd 对应项目 `.tau/AGENTS.md`
6. cwd 对应项目 `.agents/AGENTS.md`

测试里构造了：

```text
home/.tau/AGENTS.md
home/.agents/AGENTS.md
project/AGENTS.md
project/pkg/AGENTS.md
project/pkg/.tau/AGENTS.md
project/pkg/.agents/AGENTS.md
```

期望顺序就是：

```text
User Tau instructions
User agents instructions
Project instructions
Nested instructions
Project Tau instructions
Project agents instructions
```

## 11. _find_project_root()

源码：

```python
def _find_project_root(cwd: Path) -> Path:
    for path in (cwd, *cwd.parents):
        if any((path / marker).exists() for marker in PROJECT_MARKERS):
            return path
    return cwd
```

它从当前 cwd 开始往上找。

这里用了：

```python
(cwd, *cwd.parents)
```

`cwd.parents` 是父目录序列。

`*cwd.parents` 是 unpack，把所有父目录展开。

`any(...)` 表示只要任意 marker 存在，就返回 True。

如果一路找不到 marker，就把 cwd 自己当 project root。

## 12. _ancestor_agents_files()

源码：

```python
def _ancestor_agents_files(project_root: Path, cwd: Path) -> list[Path]:
    try:
        relative = cwd.relative_to(project_root)
    except ValueError:
        return [cwd / "AGENTS.md"]

    paths = [project_root / "AGENTS.md"]
    current = project_root
    for part in relative.parts:
        current = current / part
        paths.append(current / "AGENTS.md")
    return paths
```

假设：

```text
project_root = /repo
cwd = /repo/packages/api
```

`relative` 是：

```text
packages/api
```

`relative.parts` 是：

```python
("packages", "api")
```

生成的路径是：

```text
/repo/AGENTS.md
/repo/packages/AGENTS.md
/repo/packages/api/AGENTS.md
```

这样越靠近当前目录的说明也能被发现。

## 13. _dedupe_resolved_paths()

源码：

```python
def _dedupe_resolved_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    deduped: list[Path] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped
```

它去重。

这里用了：

```python
path.expanduser().resolve()
```

`expanduser()` 展开 `~`。

`resolve()` 解析成真实绝对路径。

这样如果两个候选路径最终指向同一个文件，只保留一次。

## 14. ProjectContextFile

位置：

```text
src/tau_coding/system_prompt.py
```

源码：

```python
@dataclass(frozen=True, slots=True)
class ProjectContextFile:
    """A project instruction file included in the system prompt."""

    path: str
    content: str
```

它只保存：

```text
path     文件路径
content  文件内容
```

为什么 path 是 str，不是 Path？

因为它最终要格式化进 system prompt。

字符串更直接。

## 15. format_project_context()

源码：

```python
def format_project_context(context_files: Sequence[ProjectContextFile]) -> str:
    """Format project context files using Pi's XML-like wrapper."""
    if not context_files:
        return ""

    lines = [
        "\n\n<project_context>",
        "",
        "Project-specific instructions and guidelines:",
        "",
    ]
    for context_file in context_files:
        lines.append(f'<project_instructions path="{escape(context_file.path)}">')
        lines.append(context_file.content)
        lines.append("</project_instructions>")
        lines.append("")
    lines.append("</project_context>")
    return "\n".join(lines)
```

它把多个 context files 变成 XML-like prompt section。

类似：

```xml
<project_context>

Project-specific instructions and guidelines:

<project_instructions path="/repo/AGENTS.md">
Follow project rules.
</project_instructions>

</project_context>
```

## 16. 为什么 path 要 escape

源码：

```python
escape(context_file.path)
```

来自：

```python
from xml.sax.saxutils import escape
```

如果路径里有特殊字符：

```text
&
<
>
```

直接放进 XML-like 标签会破坏结构。

`escape()` 会把它们转义。

## 17. CodingSession.load() 如何接入 context discovery

`CodingSession.load()` 里：

```python
resource_paths = resource_paths_with_cwd(config.resource_paths, config.cwd)
resources = _load_session_resources(resource_paths, config.context_files)
```

`_load_session_resources()` 会调用：

```python
discovered_context, context_diagnostics = discover_project_context_with_diagnostics(
    resource_paths
)
```

然后：

```python
context_files=_merge_context_files(explicit_context_files, discovered_context)
```

最后 build system prompt：

```python
BuildSystemPromptOptions(
    cwd=config.cwd,
    tools=tools,
    skills=resources.skills,
    context_files=resources.context_files,
)
```

所以 context discovery 在 session 启动时自动发生。

## 18. _merge_context_files()

源码：

```python
def _merge_context_files(
    explicit: tuple[ProjectContextFile, ...],
    discovered: tuple[ProjectContextFile, ...],
) -> tuple[ProjectContextFile, ...]:
    merged: list[ProjectContextFile] = []
    seen: set[str] = set()
    for context_file in (*explicit, *discovered):
        if context_file.path in seen:
            continue
        seen.add(context_file.path)
        merged.append(context_file)
    return tuple(merged)
```

它合并两类 context：

```text
explicit_context_files  调用方显式传入
discovered_context      自动发现
```

显式传入的排在前面。

如果路径重复，只保留第一次。

这里的：

```python
(*explicit, *discovered)
```

是 tuple unpack。

意思是把两个 tuple 串起来遍历。

## 19. reload() 如何刷新 context

`CodingSession.reload()` 会重新调用：

```python
resources = _load_session_resources(self._resource_paths, self._config.context_files)
```

然后比较前后签名：

```python
before_context_files = _context_file_signatures(self._context_files)
after_context_files = _context_file_signatures(resources.context_files)
```

如果 system prompt 的输入变了，就重建：

```python
rebuilt_system_prompt = build_system_prompt(...)
system_prompt_rebuilt = True
```

最后更新：

```python
self._context_files = resources.context_files
self._resource_diagnostics = resources.diagnostics
```

## 20. /reload 不修改 transcript

测试：

```python
entries_before = await storage.read_all()
result = session.handle_command("/reload")
entries_after = await storage.read_all()
assert entries_after == entries_before
```

这很重要。

`/reload` 改的是未来 turn 的环境：

- skills
- prompt templates
- context files
- diagnostics
- generated system prompt

它不应该往 session transcript 里写历史消息。

## 21. /reload 不刷新 provider config

`commands.py` 的 reload summary 里明确：

```text
Provider config:
- Not refreshed by /reload; use /login or /model for provider/model settings.
```

这是 Phase 18 和 Phase 19 的边界。

```text
/reload 负责本地 coding resources 和 project context
/model、/login 负责 provider/model 配置
```

## 22. 当前命令可见性

当前默认公开的相关命令：

```text
/session
/reload
```

`/session` 显示：

```python
f"Context files: {len(session.context_files)}"
```

`/reload` 显示：

```text
Project context files: 1 total (changed, +1)
Next-turn system prompt: rebuilt
```

源码中 `_context_command()` 可列出 active context files，但当前没有注册为默认命令。

## 23. tests/test_context.py 的核心测试

测试创建目录：

```text
home/.tau/AGENTS.md
home/.agents/AGENTS.md
project/pyproject.toml
project/AGENTS.md
project/pkg/AGENTS.md
project/pkg/.tau/AGENTS.md
project/pkg/.agents/AGENTS.md
```

然后 cwd 是：

```text
project/pkg
```

期望发现顺序：

```python
[
    tau_home / "AGENTS.md",
    agents_home / "AGENTS.md",
    project / "AGENTS.md",
    nested / "AGENTS.md",
    nested / ".tau" / "AGENTS.md",
    nested / ".agents" / "AGENTS.md",
]
```

这就是 Phase 19 的主要行为证明。

## 24. tests/test_coding_session.py 的集成测试

`test_session_builds_system_prompt_when_system_is_omitted` 验证：

1. cwd 下有 `AGENTS.md`
2. resource root 下有 skill
3. `CodingSession.load()` 自动发现 context
4. provider 收到的 system prompt 里包含：

```text
Follow project rules.
<available_skills>
<name>testing</name>
```

还验证：

```python
assert [Path(context_file.path).name for context_file in session.context_files] == ["AGENTS.md"]
```

说明 session 保存了 active context files。

## 25. Python 小白应该掌握的语法点

### 25.1 Path.parents

```python
cwd.parents
```

返回当前路径的所有父目录。

### 25.2 any()

```python
any((path / marker).exists() for marker in PROJECT_MARKERS)
```

只要有一个 marker 存在，就返回 True。

### 25.3 try/except ValueError

```python
try:
    relative = cwd.relative_to(project_root)
except ValueError:
    return [cwd / "AGENTS.md"]
```

如果 cwd 不在 project_root 下面，`relative_to()` 会抛 `ValueError`。

### 25.4 list comprehension

```python
existing = [path for path in candidates if path.is_file()]
```

保留真正存在且是文件的候选路径。

### 25.5 set 去重

```python
seen: set[Path] = set()
```

用来记录已经见过的 resolved path。

## 26. 你读源码时的推荐顺序

建议这样读：

1. `context.py` 的 `PROJECT_MARKERS`
2. `discover_project_context()`
3. `discover_project_context_with_diagnostics()`
4. `_context_file_candidates()`
5. `_find_project_root()`
6. `_ancestor_agents_files()`
7. `_dedupe_resolved_paths()`
8. `system_prompt.py` 的 `ProjectContextFile`
9. `format_project_context()`
10. `session.py` 的 `_load_session_resources()`
11. `session.py` 的 `_merge_context_files()`
12. `CodingSession.reload()`
13. `commands.py` 的 `_reload_command()`

## 27. Phase 19 用一句话总结

Phase 19 的价值是：在 `tau_coding` 中加入项目上下文发现机制，自动按用户级、项目根、当前目录层级、项目 `.tau` 和 `.agents` 的顺序读取 `AGENTS.md`，把它们转成 `ProjectContextFile` 并注入 system prompt，同时让 `/reload` 可以刷新这些上下文和相关 diagnostics，而不污染 `tau_agent` 或已持久化的 transcript。

## 28. 我的问题与推荐回答

问题：为什么 Tau 要在 session 启动时自动发现多个层级的 `AGENTS.md`，而不是只读取当前目录下一个文件？

我的推荐回答：

因为 coding agent 的规则通常有层级：用户可能有全局规则，项目根目录可能有仓库级规则，当前子目录可能有更具体的模块规则，`.tau` 和 `.agents` 里还可能有 Tau/Pi 风格的资源说明。只读当前目录会漏掉上层约束，只读项目根又会漏掉子目录细节。Phase 19 按固定顺序收集这些文件，并用 `ProjectContextFile` 注入 system prompt，既保留全局规则，也让离当前 cwd 最近的项目说明能被模型看到。
