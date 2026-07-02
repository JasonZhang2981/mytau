# Phase 13 学习笔记：Tau Home, Paths, and `.agents` Resources

对应架构文档：`dev-notes/architecture/phase-13-paths-agents-resources.md`

主要源码：

- `src/tau_coding/paths.py`
- `src/tau_coding/resources.py`
- `src/tau_coding/skills.py`
- `src/tau_coding/prompt_templates.py`
- `src/tau_coding/session.py`
- `tests/test_paths.py`
- `tests/test_resources.py`
- `tests/test_skills.py`
- `tests/test_prompt_templates.py`
- `tests/test_cli.py`
- `tests/test_coding_session.py`

前置阶段：

- Phase 9：Tau 已经能加载 skills 和 prompt templates
- Phase 12：TUI 开始需要默认 session 文件位置
- Phase 13：把 Tau 用户级/项目级路径规则正式抽象出来

## 1. 这一阶段到底在做什么

Phase 13 的主题是文件系统位置。

它回答这些问题：

- Tau 自己的数据放在哪里？
- 用户级 skills/prompts 放在哪里？
- `.agents` 资源放在哪里？
- 项目级资源放在哪里？
- session JSONL 文件应该放项目里，还是用户 home 里？
- 同名资源谁覆盖谁？

核心新增对象是：

```python
TauPaths
```

它位于：

```text
src/tau_coding/paths.py
```

你可以先用一句话理解：

`TauPaths` 是 Tau 的路径地图，它把用户级 `.tau`、用户级 `.agents`、项目级 `.tau/.agents`、sessions、logs 等位置集中定义，避免路径规则散落在 CLI、TUI、session、resource loader 里。

## 2. 为什么需要专门的 paths.py

如果没有 `TauPaths`，代码里可能到处写：

```python
Path.home() / ".tau" / "sessions"
Path.home() / ".agents" / "skills"
cwd / ".agents" / "prompts"
cwd / ".tau" / "skills"
```

这样有几个问题：

- 路径规则容易不一致
- 测试时很难替换 home 目录
- 后续想改位置会牵一堆文件
- session manager、resource loader、provider config 会重复造路径

所以 Phase 13 把这些路径集中到：

```python
TauPaths
```

其他模块只调用它。

## 3. TauPaths 的基础结构

源码：

```python
@dataclass(frozen=True, slots=True)
class TauPaths:
    """Resolved Tau filesystem locations."""

    home: Path = field(default_factory=lambda: Path.home() / ".tau")
    agents_home: Path = field(default_factory=lambda: Path.home() / ".agents")
```

默认：

```text
home        = ~/.tau
agents_home = ~/.agents
```

也就是说 Tau 自己的数据默认放：

```text
~/.tau/
```

通用 agent 资源默认放：

```text
~/.agents/
```

测试可以传自定义路径：

```python
TauPaths(home=tmp_path / ".tau", agents_home=tmp_path / ".agents")
```

这样不会污染真实用户目录。

## 4. Python 知识：Path.home()

`Path.home()` 来自标准库：

```python
from pathlib import Path
```

它返回当前用户 home 目录。

例如在 macOS 上可能是：

```text
/Users/zhangshixin
```

所以：

```python
Path.home() / ".tau"
```

就是：

```text
/Users/zhangshixin/.tau
```

使用 `Path` 的 `/` 操作符拼接路径，比字符串拼接更清晰。

## 5. 用户级 Tau 路径

`TauPaths` 里有：

```python
@property
def sessions_dir(self) -> Path:
    return self.home / "sessions"

@property
def logs_dir(self) -> Path:
    return self.home / "logs"

@property
def agent_calls_log_path(self) -> Path:
    return self.logs_dir / "agent-calls.jsonl"

@property
def user_skills_dir(self) -> Path:
    return self.home / "skills"

@property
def user_prompts_dir(self) -> Path:
    return self.home / "prompts"
```

如果 `home=~/.tau`，那么：

```text
~/.tau/sessions
~/.tau/logs
~/.tau/logs/agent-calls.jsonl
~/.tau/skills
~/.tau/prompts
```

分别用于：

- session 文件
- 诊断日志
- agent call 异常日志
- Tau-native skills
- Tau-native prompt templates

## 6. 用户级 .agents 路径

源码：

```python
@property
def user_agents_skills_dir(self) -> Path:
    return self.agents_home / "skills"

@property
def user_agents_prompts_dir(self) -> Path:
    return self.agents_home / "prompts"
```

如果 `agents_home=~/.agents`：

```text
~/.agents/skills
~/.agents/prompts
```

Phase 13 的重要变化是：

`.agents` 不再只是一个可选外部扩展。

它成为普通 Tau session 默认会加载的资源位置。

## 7. 项目级路径

项目级路径基于 `cwd`。

源码：

```python
def project_tau_dir(self, cwd: Path) -> Path:
    return cwd / ".tau"

def project_agents_dir(self, cwd: Path) -> Path:
    return cwd / ".agents"
```

如果项目目录是：

```text
/repo/my-project
```

那么：

```text
/repo/my-project/.tau
/repo/my-project/.agents
```

再往下：

```python
def project_skills_dir(self, cwd: Path) -> Path:
    return self.project_tau_dir(cwd) / "skills"

def project_prompts_dir(self, cwd: Path) -> Path:
    return self.project_tau_dir(cwd) / "prompts"

def project_agents_skills_dir(self, cwd: Path) -> Path:
    return self.project_agents_dir(cwd) / "skills"

def project_agents_prompts_dir(self, cwd: Path) -> Path:
    return self.project_agents_dir(cwd) / "prompts"
```

对应：

```text
<project>/.tau/skills
<project>/.tau/prompts
<project>/.agents/skills
<project>/.agents/prompts
```

## 8. tests/test_paths.py 的基础验证

测试：

```python
test_tau_paths_user_locations
```

验证用户级路径。

测试：

```python
test_tau_paths_project_locations
```

验证项目级路径。

这些测试看起来简单，但很重要。

因为路径 helper 是底层约定。

一旦路径错了，上层资源加载、session resume、日志、TUI 配置都会受影响。

## 9. session 位置为什么改到用户 home

Phase 12 里早期 TUI default session path 是：

```text
<project>/.tau/sessions/default.jsonl
```

Phase 13 改成：

```text
~/.tau/sessions/<project-hash>/default.jsonl
```

为什么？

因为 session transcript 是用户的运行数据。

它通常不应该写进项目工作树里。

如果写进项目目录：

- 容易被 git status 看到
- 可能不小心提交
- 多项目 session 位置不统一
- 项目目录只读时会失败

放到用户 home：

```text
~/.tau/sessions/
```

更符合应用数据的归属。

同时按项目路径分目录，避免不同项目混在一起。

## 10. project_session_dir()

源码：

```python
def project_session_dir(self, cwd: Path) -> Path:
    resolved = cwd.resolve()
    digest = sha256(str(resolved).encode("utf-8")).hexdigest()[:6]
    slug = _slugify_path(resolved)
    return self.sessions_dir / f"{slug or 'project'}-{digest}"
```

这段做了三件事：

1. 解析 cwd 成真实路径
2. 根据路径算一个 6 位 hash
3. 根据路径生成可读 slug
4. 拼成 session 目录名

结果类似：

```text
~/.tau/sessions/repos-exploration-tau-a1b2c3
```

既可读，又能减少冲突。

## 11. Python 包：hashlib.sha256

源码：

```python
from hashlib import sha256
```

`sha256` 是一种哈希算法。

这里不是为了安全加密，而是为了把项目路径变成稳定短标识。

例如：

```python
digest = sha256(str(resolved).encode("utf-8")).hexdigest()[:6]
```

逐步理解：

```python
str(resolved)
```

把路径转成字符串。

```python
.encode("utf-8")
```

把字符串变成 bytes。

```python
sha256(...).hexdigest()
```

得到十六进制 hash 字符串。

```python
[:6]
```

取前 6 位。

## 12. 为什么 slug 后面还要 hash

只用 slug 可能冲突。

比如两个路径：

```text
/tmp/a-b
/tmp/a_b
```

经过 slugify 后可能变得很像。

加一个 hash 后缀：

```text
tmp-a-b-123abc
tmp-a-b-9f8e01
```

就更安全。

同时 slug 保持人类可读。

## 13. default_session_path()

源码：

```python
def default_session_path(self, cwd: Path) -> Path:
    path = self.project_session_dir(cwd) / "default.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
```

它返回默认 session 文件：

```text
~/.tau/sessions/<project-slug-hash>/default.jsonl
```

并确保父目录存在：

```python
path.parent.mkdir(parents=True, exist_ok=True)
```

## 14. Python 知识：mkdir(parents=True, exist_ok=True)

```python
path.parent.mkdir(parents=True, exist_ok=True)
```

表示创建目录。

参数解释：

### parents=True

如果上级目录不存在，也一起创建。

例如要创建：

```text
~/.tau/sessions/project
```

但 `~/.tau/sessions` 不存在，`parents=True` 会一起创建。

### exist_ok=True

如果目录已经存在，不报错。

这对 default path 很重要。

多次调用：

```python
default_session_path(cwd)
```

不应该因为目录已存在而失败。

## 15. _slugify_path()

源码：

```python
def _slugify_path(path: Path, *, max_length: int = 72) -> str:
    parts = [part for part in path.parts if part not in (path.anchor, "")]
    try:
        relative_to_home = path.relative_to(Path.home())
    except ValueError:
        pass
    else:
        parts = ["home", *relative_to_home.parts]
```

它先把路径拆成 parts。

例如：

```text
/Users/me/repos/tau
```

parts 可能是：

```python
("/", "Users", "me", "repos", "tau")
```

它会去掉 anchor `/`。

如果路径在 home 目录下，就改成：

```text
home-repos-tau
```

避免把用户名直接作为主要前缀。

## 16. Python 知识：try / except / else

这里：

```python
try:
    relative_to_home = path.relative_to(Path.home())
except ValueError:
    pass
else:
    parts = ["home", *relative_to_home.parts]
```

意思是：

- 尝试判断 path 是否在 home 下面
- 如果不在，会抛 `ValueError`
- 抛错就什么都不做
- 没抛错就执行 `else`

`try/except/else` 的 `else` 表示：

```text
try 代码块没有异常时执行
```

## 17. 正则清理 slug

源码：

```python
normalized := re.sub(r"[^a-zA-Z0-9._-]+", "-", part).strip(".-_").lower()
```

这里用了正则表达式：

```python
re.sub(pattern, replacement, text)
```

意思是把不符合规则的字符替换成 `-`。

pattern：

```regex
[^a-zA-Z0-9._-]+
```

表示：

一个或多个不是字母、数字、点、下划线、横线的字符。

所以路径里的空格、中文特殊符号等会被清理成更适合作为目录名的 slug。

## 18. Python 知识：海象运算符 :=

这一段：

```python
if (normalized := re.sub(...).strip(".-_").lower())
```

使用了海象运算符 `:=`。

它可以在表达式里赋值。

等价于更啰嗦的写法：

```python
normalized = re.sub(...).strip(".-_").lower()
if normalized:
    ...
```

这里用在列表推导式里：

```python
slug_parts = [
    normalized
    for part in parts
    if (normalized := ...)
]
```

意思是：

对每个 path part 做规范化，如果结果非空，就加入 slug_parts。

## 19. TauResourcePaths 如何使用 TauPaths

Phase 9 已经讲过 `TauResourcePaths`。

Phase 13 让它和 `TauPaths` 更明确地结合。

`resources.py` 里：

```python
paths: TauPaths | None = None
```

以及：

```python
def _paths(self) -> TauPaths:
    agents_home = self.agents_root or Path.home() / ".agents"
    return self.paths or TauPaths(home=self.root, agents_home=agents_home)
```

这表示：

如果调用方传了 `TauPaths`，就用它。

否则用 `root` 和 `agents_root` 构造一个。

测试里会传：

```python
TauPaths(home=tau_home, agents_home=agents_home)
```

这样 `TauResourcePaths` 算出的项目路径也可控。

## 20. skills_dirs 的优先级

`TauResourcePaths.skills_dirs` 返回：

```text
user Tau skills
user .agents skills
user .agents root
project .tau skills
project .agents skills
project .agents root
```

源码：

```python
dirs = [self.skills_dir]
if self.agents_root is not None:
    dirs.extend([self.agents_root / "skills", self.agents_root])
if self.cwd is not None:
    dirs.extend(
        [
            paths.project_skills_dir(self.cwd),
            paths.project_agents_skills_dir(self.cwd),
            paths.project_agents_dir(self.cwd),
        ]
    )
```

顺序是“低优先级到高优先级”。

后面的同名资源会覆盖前面的。

## 21. prompts_dirs 的优先级

`prompts_dirs` 返回：

```text
user Tau prompts
user .agents prompts
project .tau prompts
project .agents prompts
```

源码：

```python
dirs = [self.prompts_dir]
if self.agents_root is not None:
    dirs.append(self.agents_root / "prompts")
if self.cwd is not None:
    dirs.extend(
        [
            paths.project_prompts_dir(self.cwd),
            paths.project_agents_prompts_dir(self.cwd),
        ]
    )
```

prompt templates 不从 `.agents` 根目录直接加载。

skills 会从 `.agents` 根目录加载 `.md` 文件，但排除 `AGENTS.md`。

## 22. 为什么 AGENTS.md 不当成 skill

`skills.py` 里有：

```python
if path.name.upper() == "AGENTS.MD":
    continue
```

原因是：

`AGENTS.md` 是项目/agent 指令文件，不是一个可调用 skill。

如果把它当 skill：

```text
/skill:AGENTS
```

语义会很奇怪。

项目 instruction discovery 是后续 Phase 19 的内容。

Phase 13 只保证 `.agents` 资源路径进入默认发现范围。

## 23. resource_paths_with_cwd()

`resources.py` 里还有：

```python
def resource_paths_with_cwd(
    paths: TauResourcePaths | None,
    cwd: Path,
) -> TauResourcePaths:
    if paths is None:
        return TauResourcePaths(cwd=cwd)
    if paths.cwd is not None:
        return paths
    return TauResourcePaths(
        root=paths.root,
        cwd=cwd,
        agents_root=paths.agents_root,
        paths=paths.paths,
    )
```

它的作用：

确保 coding session 有 cwd-aware resource paths。

如果没传 paths：

```python
TauResourcePaths(cwd=cwd)
```

如果传了 paths 但没有 cwd，就补上 cwd。

如果传进来的 paths 已经有 cwd，就尊重它。

## 24. CodingSession 集成

`src/tau_coding/session.py` 里：

```python
resource_paths = resource_paths_with_cwd(config.resource_paths, config.cwd)
resources = _load_session_resources(resource_paths, config.context_files)
```

这意味着：

普通 `CodingSession.load()` 会自动看到：

- 用户级 `.tau`
- 用户级 `.agents`
- 当前项目 `.tau`
- 当前项目 `.agents`

所以用户不需要每次手动配置资源路径。

## 25. Phase 13 和 Phase 9 的关系

Phase 9 解决：

```text
Markdown resource 如何加载成 Skill / PromptTemplate？
```

Phase 13 解决：

```text
应该从哪些目录加载这些 Markdown resource？
```

二者关系：

```text
TauPaths
  -> TauResourcePaths.skills_dirs / prompts_dirs
  -> load_skills / load_prompt_templates
  -> CodingSession resources
  -> system prompt / prompt expansion / TUI
```

## 26. tests/test_resources.py 的 Phase 13 重点

测试：

```python
test_resource_paths_include_agents_and_project_directories
```

验证：

```python
paths.skills_dirs == (
    tau_home / "skills",
    agents_home / "skills",
    agents_home,
    cwd / ".tau" / "skills",
    cwd / ".agents" / "skills",
    cwd / ".agents",
)
```

以及：

```python
paths.prompts_dirs == (
    tau_home / "prompts",
    agents_home / "prompts",
    cwd / ".tau" / "prompts",
    cwd / ".agents" / "prompts",
)
```

这就是 Phase 13 的资源发现顺序。

## 27. tests/test_skills.py 的 Phase 13 重点

几个关键测试：

```text
test_load_skills_includes_user_and_project_agents_directories
test_project_agents_skill_overrides_user_agents_skill
test_load_skills_with_diagnostics_reports_overrides
test_agents_md_is_not_loaded_as_a_skill
```

它们验证：

- `.agents/skills` 会被加载
- 项目 `.agents` skill 覆盖用户 `.agents` skill
- 覆盖会产生 diagnostic
- `.agents/AGENTS.md` 不会被误加载为 skill

## 28. tests/test_prompt_templates.py 的 Phase 13 重点

关键测试：

```text
test_load_prompt_templates_includes_agents_directories
test_project_prompt_template_overrides_user_template
test_load_prompt_templates_with_diagnostics_reports_overrides
```

它们验证 prompt templates 也遵守：

```text
用户级 -> 项目级
低优先级 -> 高优先级
同名后者覆盖前者
```

## 29. 初学者容易误解的点

### 误解 1：`.tau` 和 `.agents` 是同一个东西

不是。

`.tau` 是 Tau-native 用户/项目数据和资源位置。

`.agents` 是更通用的 agent 资源位置。

Tau 会同时加载两者。

### 误解 2：session 文件应该放项目 `.tau` 里

Phase 13 后不再这样。

session JSONL 是用户运行数据，默认放：

```text
~/.tau/sessions/<project-slug-hash>/default.jsonl
```

### 误解 3：所有 `.agents/*.md` 都是 skill

不是。

`AGENTS.md` 被排除。

它是项目 instructions，后续由 context discovery 处理。

### 误解 4：同名资源一定报错

同一个目录里同名是问题。

不同优先级目录里同名是 override。

项目资源覆盖用户资源是预期行为。

## 30. Phase 13 用一句话总结

Phase 13 的价值是：用 `TauPaths` 明确 Tau 的用户级和项目级文件系统约定，把 session JSONL 移到用户 home 下按项目隔离的目录，并让 `TauResourcePaths` 默认纳入 `.agents` 和项目级资源目录；这样 skills、prompt templates、session manager、TUI、日志和后续 context discovery 都有了统一可靠的路径基础。

## 31. 我的问题与推荐回答

问题：为什么 Phase 13 要把默认 session 文件从 `<project>/.tau/sessions/default.jsonl` 移到 `~/.tau/sessions/<project-slug-hash>/default.jsonl`？

我的推荐回答：

因为 session JSONL 是用户运行 Tau 时产生的会话数据，不是项目源码的一部分。放在项目目录里容易污染 git working tree，也可能被误提交；放到 `~/.tau/sessions/` 则更符合应用数据归属。为了仍然按项目隔离，`TauPaths.project_session_dir()` 会用项目真实路径生成一个可读 slug，并追加 6 位 sha256 hash，形成类似 `repos-my-project-a1b2c3/default.jsonl` 的路径。这样既集中管理 session，又避免不同项目互相混淆。
