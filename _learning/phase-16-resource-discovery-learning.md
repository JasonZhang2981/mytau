# Phase 16 学习笔记：Robust Resource Discovery

对应架构文档：`dev-notes/architecture/phase-16-resource-discovery.md`

主要源码：

- `src/tau_coding/resources.py`
- `src/tau_coding/skills.py`
- `src/tau_coding/prompt_templates.py`
- `src/tau_coding/context.py`
- `src/tau_coding/session.py`
- `src/tau_coding/commands.py`
- `tests/test_resources.py`
- `tests/test_skills.py`
- `tests/test_prompt_templates.py`
- `tests/test_coding_session.py`
- `tests/test_commands.py`

前置阶段：

- Phase 9：Tau 开始加载 skills 和 prompt templates
- Phase 10：skills/context files 进入 system prompt
- Phase 13：Tau 定义了用户目录、项目目录、`.tau`、`.agents` 的路径规则
- Phase 15：命令系统可以显示 session/resource 相关信息
- Phase 16：资源发现从“严格失败”升级成“宽容加载 + 诊断信息”

## 1. 这一阶段到底在做什么

Phase 16 解决的是一个真实用户环境里很常见的问题：

```text
用户的资源目录可能不完美。
```

例如：

- 有两个 skill 叫同一个名字
- 某个 markdown 文件读不了
- 用户级 skill 被项目级 skill 覆盖
- prompt template 同名覆盖
- AGENTS.md 读取失败

早期实现如果遇到错误，可能直接抛异常：

```python
raise ResourceError(...)
```

这样 CLI/TUI 可能直接起不来。

Phase 16 的目标是：

```text
能加载的资源继续加载；
有问题的资源变成 ResourceDiagnostic；
让用户在 session 里看到诊断，而不是让整个应用崩掉。
```

一句话理解：

Phase 16 让 Tau 的资源发现从“脆弱的严格加载”变成“适合真实目录的宽容加载”。

## 2. 什么是资源 resource

在 Tau 里，这一阶段主要说的 resource 包括：

```text
skills
prompt templates
project context files
```

分别对应：

```text
skills            可通过 /skill:<name> 展开的技能文档
prompt templates  可通过 /name args 展开的提示词模板
context files      AGENTS.md 等项目说明文件
```

它们都属于 `tau_coding`。

原因是：

```text
资源发现依赖本地文件系统、用户 home、项目 cwd、.tau、.agents
```

这些不是通用 `tau_agent` harness 应该知道的东西。

## 3. ResourceDiagnostic：非致命诊断

Phase 16 最核心的新类型是：

```python
ResourceDiagnostic
```

位置：

```text
src/tau_coding/resources.py
```

源码：

```python
@dataclass(frozen=True, slots=True)
class ResourceDiagnostic:
    """A non-fatal resource discovery problem or precedence note."""

    kind: str
    message: str
    path: Path | None = None
    name: str | None = None
    severity: str = "warning"
```

字段解释：

```text
kind      资源类型，例如 skill、prompt、context
message   人能看懂的问题说明
path      相关文件路径，可能没有
name      资源名字，可能没有
severity  严重程度，默认 warning，也可能是 error
```

注意它叫 diagnostic，不叫 error。

这说明它不一定要让程序停止。

例如：

```text
Project skill overrides user skill
```

这不是失败，只是一个值得告诉用户的覆盖说明。

## 4. dataclass 再复习

`ResourceDiagnostic` 使用：

```python
@dataclass(frozen=True, slots=True)
```

这表示：

- 这是一个主要保存数据的类。
- 创建后字段不希望被修改。
- 不允许随便添加新属性。

你可以这样创建：

```python
ResourceDiagnostic(
    kind="skill",
    name="review",
    path=Path("review.md"),
    message="overrides lower-precedence resource",
)
```

因为 `severity` 有默认值：

```python
severity: str = "warning"
```

所以不传 severity 时默认就是 `"warning"`。

## 5. ResourceDiagnostic.format()

源码：

```python
def format(self) -> str:
    """Return a concise human-readable diagnostic line."""
    parts = [self.severity, self.kind]
    if self.name is not None:
        parts.append(self.name)
    label = " ".join(parts)
    if self.path is None:
        return f"{label}: {self.message}"
    return f"{label}: {self.message} ({self.path})"
```

这个方法把诊断对象变成一行文本。

如果：

```python
severity = "warning"
kind = "skill"
name = "review"
message = "overrides lower-precedence resource at /old/review.md"
path = Path("/new/review.md")
```

输出类似：

```text
warning skill review: overrides lower-precedence resource at /old/review.md (/new/review.md)
```

这里用到了：

```python
" ".join(parts)
```

意思是用空格把列表里的字符串拼起来。

## 6. TauResourcePaths：资源目录从哪里来

`TauResourcePaths` 也在：

```text
src/tau_coding/resources.py
```

源码：

```python
@dataclass(frozen=True, slots=True)
class TauResourcePaths:
    root: Path = field(default_factory=lambda: Path.home() / ".tau")
    cwd: Path | None = None
    agents_root: Path | None = field(default_factory=lambda: Path.home() / ".agents")
    paths: TauPaths | None = None
```

它负责告诉资源加载器：

```text
去哪些目录找 skills 和 prompts
```

### 6.1 field(default_factory=...)

这里有一个 Python 小知识：

```python
field(default_factory=lambda: Path.home() / ".tau")
```

`default_factory` 表示“每次创建对象时，调用这个函数生成默认值”。

为什么不用：

```python
root: Path = Path.home() / ".tau"
```

因为 default_factory 更适合动态默认值。

虽然 `Path` 不是可变对象，这里不用也不一定出事，但这种写法更统一、更安全。

### 6.2 Path.home()

```python
Path.home()
```

返回当前用户的 home 目录。

例如在这台机器可能是：

```text
/Users/zhangshixin
```

所以默认 Tau resource root 是：

```text
~/.tau
```

默认 agents root 是：

```text
~/.agents
```

## 7. skills_dir 和 prompts_dir

源码：

```python
@property
def skills_dir(self) -> Path:
    """Return the primary Tau skills directory."""
    return self.root / "skills"

@property
def prompts_dir(self) -> Path:
    """Return the primary Tau prompt templates directory."""
    return self.root / "prompts"
```

如果：

```python
root = Path("/home/me/.tau")
```

那么：

```text
skills_dir  = /home/me/.tau/skills
prompts_dir = /home/me/.tau/prompts
```

`Path / "skills"` 是 pathlib 的语法。

它表示拼路径。

比字符串拼接更安全：

```python
self.root / "skills"
```

优于：

```python
str(self.root) + "/skills"
```

## 8. skills_dirs：技能目录优先级

源码：

```python
@property
def skills_dirs(self) -> tuple[Path, ...]:
    """Return skill directories in increasing precedence order."""
    paths = self._paths()
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
    return tuple(_dedupe_paths(dirs))
```

这里的关键词是：

```text
in increasing precedence order
```

意思是：

```text
越靠后，优先级越高。
```

技能目录顺序是：

1. 用户 Tau skills：`~/.tau/skills`
2. 用户 `.agents/skills`：`~/.agents/skills`
3. 用户 `.agents` 根目录：`~/.agents`
4. 项目 Tau skills：`<cwd>/.tau/skills`
5. 项目 `.agents/skills`：`<cwd>/.agents/skills`
6. 项目 `.agents` 根目录：`<cwd>/.agents`

测试里确认：

```python
assert paths.skills_dirs == (
    tau_home / "skills",
    agents_home / "skills",
    agents_home,
    cwd / ".tau" / "skills",
    cwd / ".agents" / "skills",
    cwd / ".agents",
)
```

为什么 `.agents` 根目录也算 skills 目录？

因为历史上有些 agent skill/resource 可能直接放在 `.agents` 下面，比如：

```text
.agents/review.md
```

Tau 为了兼容这个布局，也会扫描根目录。

## 9. prompts_dirs：提示词模板目录优先级

源码：

```python
@property
def prompts_dirs(self) -> tuple[Path, ...]:
    """Return prompt template directories in increasing precedence order."""
    paths = self._paths()
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
    return tuple(_dedupe_paths(dirs))
```

prompt templates 的顺序更简单：

1. 用户 Tau prompts：`~/.tau/prompts`
2. 用户 `.agents/prompts`
3. 项目 Tau prompts：`<cwd>/.tau/prompts`
4. 项目 `.agents/prompts`

同样，越靠后优先级越高。

## 10. _dedupe_paths()

源码：

```python
def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    deduped: list[Path] = []
    for path in paths:
        resolved = path.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped
```

这个函数去重。

例如有些配置可能让：

```text
root = ~/.tau
agents_root = ~/.tau
```

导致目录重复。

`seen` 是一个 set，用来记录已经出现过的路径。

`continue` 表示跳过本轮循环后面的代码。

也就是说，如果路径已经见过，就不再加入结果。

注意这里用的是：

```python
path.expanduser()
```

它会展开 `~`。

但它没有调用 `.resolve()`。

所以它主要处理用户 home 展开，而不是完全解析软链接。

## 11. resource_paths_with_cwd()

源码：

```python
def resource_paths_with_cwd(
    paths: TauResourcePaths | None,
    cwd: Path,
) -> TauResourcePaths:
    """Return resource paths with a cwd available for project-local discovery."""
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

这个函数保证 resource paths 有 cwd。

为什么需要 cwd？

因为项目级资源目录要从 cwd 推出来：

```text
<cwd>/.tau/skills
<cwd>/.agents/skills
<cwd>/AGENTS.md
```

如果调用方没有传 paths，就创建：

```python
TauResourcePaths(cwd=cwd)
```

如果调用方传了 paths 且已经有 cwd，就原样返回。

如果传了 paths 但没有 cwd，就复制 root、agents_root、paths，再补上 cwd。

## 12. parse_markdown_resource()

资源文件是 markdown，但可能带 frontmatter。

例如：

```markdown
---
description: Write tests
---
# Testing
Use pytest.
```

`parse_markdown_resource()` 负责拆成：

```python
metadata = {"description": "Write tests"}
body = "# Testing\nUse pytest."
```

源码：

```python
def parse_markdown_resource(text: str) -> tuple[dict[str, str], str]:
    """Parse minimal YAML-like frontmatter from a markdown resource.

    Only simple `key: value` pairs are supported. This keeps resource parsing
    dependency-free and avoids evaluating arbitrary code.
    """
```

注意注释里的关键词：

```text
minimal
dependency-free
avoids evaluating arbitrary code
```

也就是说，Tau 没引入完整 YAML 解析器。

它只支持简单的：

```text
key: value
```

这对小项目更轻，也更安全。

## 13. parse_markdown_resource() 如何处理换行

源码：

```python
normalized = text.replace("\r\n", "\n").replace("\r", "\n")
```

不同系统的换行可能不同：

```text
Linux/macOS: \n
Windows:     \r\n
老 Mac:      \r
```

这里统一成：

```text
\n
```

测试里验证：

```python
test_parse_frontmatter_normalizes_crlf_line_endings
```

这对 markdown 解析很重要。

## 14. parse_markdown_resource() 如何识别 frontmatter

源码：

```python
if not normalized.startswith("---\n"):
    return {}, normalized
```

如果文本不是以：

```text
---
```

开头，就认为没有 frontmatter。

然后：

```python
end = normalized.find("\n---", 4)
if end == -1:
    return {}, normalized
```

查找结束标记。

如果没找到，也当作没有 frontmatter。

这是一种宽容解析。

不完整 frontmatter 不会直接炸掉。

## 15. parse_markdown_resource() 如何解析 key/value

源码：

```python
for line in raw_frontmatter.splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    key, separator, value = stripped.partition(":")
    if not separator:
        continue
    metadata[key.strip()] = value.strip().strip("\"'")
```

逐步看：

```python
splitlines()
```

按行拆开。

```python
line.strip()
```

去掉首尾空白。

```python
if not stripped
```

空行跳过。

```python
stripped.startswith("#")
```

注释行跳过。

```python
partition(":")
```

按第一个冒号拆成 key 和 value。

最后：

```python
value.strip().strip("\"'")
```

去掉 value 两边空白和单双引号。

## 16. derive_description()

源码：

```python
def derive_description(content: str) -> str | None:
    """Derive a short description from markdown content."""
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
        return stripped
    return None
```

如果 frontmatter 里没有 description，就从正文里推导。

规则：

1. 找第一行非空内容。
2. 如果它是 markdown 标题，就去掉 `#`。
3. 否则直接用这一行。

例如：

```markdown
# Title
Body
```

description 是：

```text
Title
```

如果：

```markdown
First paragraph
More
```

description 是：

```text
First paragraph
```

## 17. load_skills()：严格加载

`src/tau_coding/skills.py` 里仍然保留了旧的严格加载器：

```python
def load_skills(paths: TauResourcePaths | None = None) -> list[Skill]:
```

它的逻辑：

```python
resource_paths = paths or TauResourcePaths()
skills_by_name: dict[str, Skill] = {}

for skills_dir in resource_paths.skills_dirs:
    for skill in _load_skills_from_dir(skills_dir):
        skills_by_name[skill.name] = skill

return sorted(skills_by_name.values(), key=lambda skill: skill.name)
```

这里依次扫描目录。

如果后面高优先级目录里出现同名 skill：

```python
skills_by_name[skill.name] = skill
```

会覆盖前面的低优先级 skill。

但是 `_load_skills_from_dir()` 是严格的。

如果同一个目录内出现 duplicate，它会抛 `ResourceError`。

测试：

```python
with pytest.raises(ResourceError, match="Duplicate skill name"):
    load_skills(...)
```

## 18. load_skills_with_diagnostics()：宽容加载

Phase 16 新增的关键函数：

```python
def load_skills_with_diagnostics(
    paths: TauResourcePaths | None = None,
) -> tuple[list[Skill], list[ResourceDiagnostic]]:
```

返回值是一个 tuple：

```text
第一个元素：成功加载的 skills
第二个元素：诊断列表 diagnostics
```

源码核心：

```python
skills_by_name: dict[str, Skill] = {}
diagnostics: list[ResourceDiagnostic] = []

for skills_dir in resource_paths.skills_dirs:
    skills, directory_diagnostics = _load_skills_from_dir_with_diagnostics(skills_dir)
    diagnostics.extend(directory_diagnostics)
    for skill in skills:
        previous = skills_by_name.get(skill.name)
        if previous is not None:
            diagnostics.append(
                ResourceDiagnostic(
                    kind="skill",
                    name=skill.name,
                    path=skill.path,
                    message=f"overrides lower-precedence resource at {previous.path}",
                )
            )
        skills_by_name[skill.name] = skill
```

这里有两个 diagnostics 来源：

1. 单个目录内部的问题，比如 duplicate、读取失败。
2. 跨目录覆盖，比如项目 skill 覆盖用户 skill。

## 19. override 是怎么处理的

假设有两个文件：

```text
~/.tau/skills/review.md
project/.tau/skills/review.md
```

扫描顺序是用户目录先，项目目录后。

第一次：

```python
skills_by_name["review"] = user_review
```

第二次：

```python
previous = skills_by_name.get("review")
```

发现已经有了。

于是添加 diagnostic：

```python
ResourceDiagnostic(
    kind="skill",
    name="review",
    path=project_review.path,
    message=f"overrides lower-precedence resource at {user_review.path}",
)
```

然后覆盖：

```python
skills_by_name["review"] = project_review
```

最终加载的是项目级 skill，同时用户能看到覆盖诊断。

测试验证：

```python
assert skills[0].path == cwd / ".tau" / "skills" / "review.md"
assert "overrides lower-precedence resource" in diagnostics[0].message
```

## 20. _load_skills_from_dir_with_diagnostics()

源码核心：

```python
if not skills_dir.exists() or not skills_dir.is_dir():
    return [], []
```

目录不存在不是错误。

因为很多用户一开始没有创建：

```text
~/.tau/skills
```

所以不存在就返回空列表。

接着：

```python
for path in sorted(skills_dir.iterdir(), key=lambda item: item.name):
```

按文件名排序，保证 deterministic。

deterministic 的意思是：

```text
同样的目录内容，每次加载顺序都一样。
```

这对测试和用户预期都很重要。

## 21. skill 支持两种形态

源码：

```python
if path.is_dir():
    skill_path = path / "SKILL.md"
    name = path.name
    if not skill_path.exists():
        continue
elif path.is_file() and path.suffix.lower() == ".md":
    if path.name.upper() == "AGENTS.MD":
        continue
    skill_path = path
else:
    continue
```

Tau 支持：

### 21.1 目录形态

```text
skills/review/SKILL.md
```

skill name 是目录名：

```text
review
```

### 21.2 单文件形态

```text
skills/review.md
```

skill name 是文件名 stem：

```text
review
```

### 21.3 跳过 AGENTS.md

```python
if path.name.upper() == "AGENTS.MD":
    continue
```

因为 `AGENTS.md` 是项目/agent 指令文件，不应该被当成 skill。

测试验证：

```python
test_agents_md_is_not_loaded_as_a_skill
```

## 22. 同目录 duplicate 怎么处理

假设目录里同时有：

```text
skills/dup/SKILL.md
skills/dup.md
```

它们的名字都叫：

```text
dup
```

宽容加载器会：

1. 保留排序后先遇到的那个。
2. 对后遇到的 duplicate 添加 diagnostic。
3. 继续加载其它资源。

源码：

```python
if name in seen:
    diagnostics.append(
        ResourceDiagnostic(
            kind="skill",
            name=name,
            path=skill_path,
            message=f"Duplicate skill name ignored in {skills_dir}",
        )
    )
    continue
seen.add(name)
```

测试验证：

```python
assert [skill.name for skill in skills] == ["dup"]
assert len(diagnostics) == 1
assert "Duplicate skill name" in diagnostics[0].message
```

## 23. 读取失败怎么处理

源码：

```python
try:
    skills.append(_load_skill(name, skill_path))
except (OSError, UnicodeDecodeError) as exc:
    diagnostics.append(
        ResourceDiagnostic(
            kind="skill",
            name=name,
            path=skill_path,
            message=f"could not read skill: {exc}",
            severity="error",
        )
    )
```

这里捕获两类异常：

```text
OSError             文件系统错误，例如权限问题、文件消失
UnicodeDecodeError  文件不是合法 utf-8
```

发生这些错误时，不让整个加载过程失败。

而是记录一个 severity 为 `"error"` 的 diagnostic。

这就是 Phase 16 “robust”的意思。

## 24. _load_skill()

源码：

```python
def _load_skill(name: str, path: Path) -> Skill:
    raw = path.read_text(encoding="utf-8")
    metadata, content = parse_markdown_resource(raw)
    description = metadata.get("description") or derive_description(content)
    return Skill(name=name, path=path, content=content, description=description)
```

逐步看：

1. 用 UTF-8 读取 markdown。
2. 解析 frontmatter。
3. 优先用 metadata 里的 `description`。
4. 没有 description 就从正文推导。
5. 返回 `Skill` dataclass。

这里的：

```python
metadata.get("description") or derive_description(content)
```

意思是：

```text
如果 metadata 里有 description 且不是空字符串，就用它；
否则调用 derive_description(content)
```

## 25. prompt template 的宽容加载

`src/tau_coding/prompt_templates.py` 里有对应函数：

```python
def load_prompt_templates_with_diagnostics(
    paths: TauResourcePaths | None = None,
) -> tuple[list[PromptTemplate], list[ResourceDiagnostic]]:
```

它和 skills 很像：

- 按 `prompts_dirs` 顺序扫描
- 同名高优先级覆盖低优先级
- 覆盖会产生 diagnostic
- 同目录 duplicate 会产生 diagnostic
- 读取失败会产生 severity `"error"` diagnostic

主要差异是 prompt templates 只扫描：

```python
prompts_dir.glob("*.md")
```

也就是 prompts 目录下的 markdown 文件。

不像 skill 那样支持目录形态 `name/SKILL.md`。

## 26. PromptTemplate 的加载

源码：

```python
def _load_prompt_template(name: str, path: Path) -> PromptTemplate:
    raw = path.read_text(encoding="utf-8")
    metadata, content = parse_markdown_resource(raw)
    description = metadata.get("description") or derive_description(content)
    return PromptTemplate(name=name, path=path, content=content, description=description)
```

这和 `_load_skill()` 非常相似。

说明 Tau 对 markdown resource 的处理保持统一：

```text
read_text -> parse frontmatter -> derive description -> dataclass
```

## 27. strict loader 仍然存在的意义

你会看到两类函数同时存在：

```python
load_skills()
load_skills_with_diagnostics()
```

以及：

```python
load_prompt_templates()
load_prompt_templates_with_diagnostics()
```

为什么不直接删掉 strict loader？

因为不同调用方需求不同。

```text
交互式 TUI/Session：希望尽量启动，适合 with_diagnostics
脚本/测试/严格校验：希望发现问题立刻失败，适合 strict loader
```

Phase 16 不是废弃严格模式，而是给 session 增加宽容模式。

## 28. SessionResources：session 统一拿到资源和诊断

`src/tau_coding/session.py` 里有：

```python
@dataclass(frozen=True, slots=True)
class SessionResources:
    """Tau-owned resources loaded around a coding session."""

    skills: tuple[Skill, ...]
    prompt_templates: tuple[PromptTemplate, ...]
    context_files: tuple[ProjectContextFile, ...]
    diagnostics: tuple[ResourceDiagnostic, ...]
```

这是一个内部聚合对象。

它把 session 启动需要的资源打包：

```text
skills
prompt_templates
context_files
diagnostics
```

注意这里全部是 tuple。

tuple 比 list 更适合表达：

```text
加载完成后这一组结果不应该被随便改。
```

## 29. _load_session_resources()

源码：

```python
def _load_session_resources(
    resource_paths: TauResourcePaths,
    explicit_context_files: tuple[ProjectContextFile, ...],
) -> SessionResources:
    loaded_skills, skill_diagnostics = load_skills_with_diagnostics(resource_paths)
    loaded_prompt_templates, prompt_diagnostics = load_prompt_templates_with_diagnostics(
        resource_paths
    )
    discovered_context, context_diagnostics = discover_project_context_with_diagnostics(
        resource_paths
    )
    return SessionResources(
        skills=tuple(loaded_skills),
        prompt_templates=tuple(loaded_prompt_templates),
        context_files=_merge_context_files(explicit_context_files, discovered_context),
        diagnostics=tuple([*skill_diagnostics, *prompt_diagnostics, *context_diagnostics]),
    )
```

这里是 Phase 16 集成到 session 的关键。

它调用的都是带 diagnostics 的 loader：

```python
load_skills_with_diagnostics(...)
load_prompt_templates_with_diagnostics(...)
discover_project_context_with_diagnostics(...)
```

然后把所有 diagnostics 合并：

```python
tuple([*skill_diagnostics, *prompt_diagnostics, *context_diagnostics])
```

这里的 `*` 是 unpack。

例如：

```python
[*[1, 2], *[3, 4]]
```

结果是：

```python
[1, 2, 3, 4]
```

所以 diagnostics 最终是一条统一列表：

```text
skill diagnostics + prompt diagnostics + context diagnostics
```

## 30. CodingSession.load() 如何使用它

在 `CodingSession.load()` 里：

```python
resource_paths = resource_paths_with_cwd(config.resource_paths, config.cwd)
resources = _load_session_resources(resource_paths, config.context_files)
```

然后 build system prompt 时使用：

```python
skills=resources.skills
context_files=resources.context_files
```

创建 session 时保存：

```python
skills=resources.skills
prompt_templates=resources.prompt_templates
context_files=resources.context_files
resource_diagnostics=resources.diagnostics
```

这意味着：

```text
即使有某个资源有问题，session 仍可创建；
诊断信息挂在 session.resource_diagnostics 上。
```

## 31. session.resource_diagnostics

`CodingSession` 暴露属性：

```python
@property
def resource_diagnostics(self) -> tuple[ResourceDiagnostic, ...]:
    """Return non-fatal resource discovery diagnostics."""
    return self._resource_diagnostics
```

这让命令系统和 TUI 可以读取诊断。

例如 `/session` 会显示：

```python
lines.append(f"Resource diagnostics: {len(session.resource_diagnostics)}")
```

测试里：

```python
assert len(session.resource_diagnostics) == 1
assert "Duplicate skill name" in session.resource_diagnostics[0].message
assert "Resource diagnostics: 1" in (session.handle_command("/session").message or "")
```

## 32. reload() 也使用宽容加载

Phase 16 不只影响 session 第一次 load。

`CodingSession.reload()` 也会重新调用：

```python
resources = _load_session_resources(self._resource_paths, self._config.context_files)
```

然后更新：

```python
self._skills = resources.skills
self._prompt_templates = resources.prompt_templates
self._context_files = resources.context_files
self._resource_diagnostics = resources.diagnostics
```

所以用户在运行中修改 `.tau/skills`、`.agents/prompts`、`AGENTS.md` 后，可以用：

```text
/reload
```

重新加载。

`/reload` 的返回 summary 里也包含 diagnostics 数量变化。

## 33. commands.py 中的 diagnostics 展示

`commands.py` 里有：

```python
def _format_diagnostics(
    diagnostics: Sequence[ResourceDiagnostic], *, kind: str | None = None
) -> list[str]:
    filtered = [diagnostic for diagnostic in diagnostics if kind is None or diagnostic.kind == kind]
    if not filtered:
        return ["Resource diagnostics: none"]
    lines = ["Resource diagnostics:"]
    lines.extend(f"- {diagnostic.format()}" for diagnostic in filtered)
    return lines
```

这个函数把 diagnostics 转成多行文本。

参数：

```python
kind: str | None = None
```

如果 kind 是 `"skill"`，就只显示 skill diagnostics。

如果 kind 是 `None`，就显示全部 diagnostics。

这里有一个 list comprehension：

```python
[diagnostic for diagnostic in diagnostics if kind is None or diagnostic.kind == kind]
```

意思是：

```text
遍历 diagnostics；
如果没有指定 kind，就都保留；
如果指定了 kind，就只保留对应类型。
```

## 34. 当前代码和 Phase 16 架构文档的差异

Phase 16 架构文档里写到：

```text
/resources
/status
/skills
```

但当前源码经过后续 Pi command alignment 后，默认 registry 不注册这些命令。

当前测试明确要求：

```python
for command in ("/provider", "/skills", "/resources", "/context", "/help"):
    result = registry.execute(session, command)
    assert result.message == f"Unknown command: {command}"
```

也就是说：

```text
Phase 16 当时的架构意图：通过 /resources 等命令展示诊断
当前代码状态：默认公开命令不包含 /resources、/skills、/context、/status
```

但是 diagnostics 机制本身仍然存在，而且当前可以通过：

```text
/session
/reload
```

看到相关数量和 reload summary。

源码里 `_resources_command()`、`_skills_command()`、`_context_command()` 这些函数还在，但没有进入 `create_default_command_registry()`。

学习时要记住：

```text
函数存在，不等于命令已注册。
注册表才决定用户能不能执行。
```

## 35. context discovery diagnostics

虽然 Phase 16 文档重点提 skills 和 prompt templates，但当前 `_load_session_resources()` 也合并了：

```python
discover_project_context_with_diagnostics(resource_paths)
```

这来自：

```text
src/tau_coding/context.py
```

也就是说 AGENTS.md 这类上下文文件如果读取失败，也可以变成 `ResourceDiagnostic`。

这让 resource diagnostics 成为更通用的本地资源诊断流。

## 36. 为什么 override 是 warning，不是 error

假设用户有：

```text
~/.tau/skills/review.md
project/.tau/skills/review.md
```

项目级 review 覆盖用户级 review。

这可能是用户故意的：

```text
这个项目需要定制 review skill
```

所以它不应该是 error。

但也不能完全静默，因为用户可能困惑：

```text
为什么我的 user review skill 没生效？
```

所以记录 warning diagnostic 是合理的折中：

```text
不中断应用，但留下可见解释。
```

## 37. 为什么同目录 duplicate 只保留第一个

同一个目录里：

```text
skills/dup/SKILL.md
skills/dup.md
```

这不是正常 override。

因为它们优先级相同。

如果随便覆盖，用户很难理解哪个会赢。

Phase 16 的宽容加载选择：

```text
按确定性排序保留第一个；
忽略后面的 duplicate；
记录 diagnostic。
```

这样应用能继续启动，同时用户能看到问题。

严格加载器仍然会直接抛 `ResourceError`。

## 38. 为什么要排序

技能加载里：

```python
sorted(skills_dir.iterdir(), key=lambda item: item.name)
```

prompt 加载里：

```python
sorted(prompts_dir.glob("*.md"), key=lambda item: item.name)
```

排序的意义是 deterministic。

如果不排序，文件系统返回顺序可能不稳定。

这样 duplicate 时“哪个先被保留”就可能每次不同。

排序后，测试和用户行为都更稳定。

## 39. 为什么异常没有完全吞掉

宽容加载器捕获：

```python
OSError
UnicodeDecodeError
```

但不是所有异常都捕获。

这是一种很好的边界：

```text
预期的资源读取问题 -> diagnostic
真正的程序 bug -> 仍然应该暴露
```

如果写成：

```python
except Exception:
    ...
```

可能会把代码 bug 也隐藏掉，让开发更难发现问题。

## 40. Phase 16 的测试重点

这一阶段主要测试：

```text
tests/test_resources.py
tests/test_skills.py
tests/test_prompt_templates.py
tests/test_coding_session.py
tests/test_commands.py
```

其中：

- `test_resource_paths_include_agents_and_project_directories` 验证资源目录顺序。
- `test_load_skills_with_diagnostics_reports_overrides` 验证 skill 覆盖诊断。
- `test_load_skills_with_diagnostics_ignores_duplicate_within_directory` 验证 duplicate 不会让宽容加载失败。
- `test_load_prompt_templates_with_diagnostics_reports_overrides` 验证 prompt template 覆盖诊断。
- `test_session_loads_with_resource_diagnostics_instead_of_failing` 验证 `CodingSession.load()` 不因 duplicate skill 失败。
- `/session` 相关测试验证诊断数量能显示出来。

## 41. 你读源码时的推荐顺序

建议这样读：

1. `resources.py` 的 `ResourceDiagnostic`
2. `resources.py` 的 `TauResourcePaths.skills_dirs` 和 `prompts_dirs`
3. `resources.py` 的 `parse_markdown_resource()`
4. `skills.py` 的 `load_skills_with_diagnostics()`
5. `skills.py` 的 `_load_skills_from_dir_with_diagnostics()`
6. `prompt_templates.py` 的 `load_prompt_templates_with_diagnostics()`
7. `session.py` 的 `SessionResources`
8. `session.py` 的 `_load_session_resources()`
9. `CodingSession.load()` 如何保存 `resource_diagnostics`
10. `commands.py` 如何格式化 diagnostics

这个顺序会比直接从 `session.py` 开始容易很多。

## 42. Python 小白应该掌握的语法点

### 42.1 tuple 返回多个值

函数可以返回：

```python
return skills, diagnostics
```

调用时可以解包：

```python
loaded_skills, skill_diagnostics = load_skills_with_diagnostics(resource_paths)
```

这在 Python 里很常见。

### 42.2 list.extend()

```python
diagnostics.extend(directory_diagnostics)
```

`extend()` 会把另一个列表的元素逐个加入当前列表。

不同于：

```python
append(directory_diagnostics)
```

`append()` 会把整个列表当作一个元素放进去。

### 42.3 set 去重

```python
seen: set[str] = set()
```

set 适合判断“是否已经出现过”。

判断速度快，写法清楚：

```python
if name in seen:
    ...
seen.add(name)
```

### 42.4 Path.exists() 和 Path.is_dir()

```python
if not skills_dir.exists() or not skills_dir.is_dir():
    return [], []
```

意思是：

```text
路径不存在，或者不是目录，就不扫描。
```

### 42.5 except (A, B) as exc

```python
except (OSError, UnicodeDecodeError) as exc:
```

表示捕获多个异常类型。

`exc` 是异常对象，可以转成字符串放进诊断消息。

## 43. Phase 16 用一句话总结

Phase 16 的价值是：在 `tau_coding` 的资源加载层加入 `ResourceDiagnostic` 和带 diagnostics 的宽容加载器，让 skills、prompt templates、context files 的发现过程既能处理同名覆盖和局部错误，又不会因为一个坏资源导致整个 coding session 或 TUI 启动失败，同时把诊断信息保留给 `/session`、`/reload` 和后续 UI 展示使用。

## 44. 我的问题与推荐回答

问题：为什么 Tau 要同时保留 `load_skills()` 和 `load_skills_with_diagnostics()`，而不是只保留一个宽容加载器？

我的推荐回答：

因为它们服务的场景不同。`load_skills()` 是严格加载，适合测试、脚本或显式校验，遇到 duplicate 这类问题应该立刻抛 `ResourceError`。`load_skills_with_diagnostics()` 是交互式 session/TUI 更需要的宽容加载，遇到局部问题时尽量保留可用资源，并把问题放进 `ResourceDiagnostic`，这样用户仍然能打开 Tau，再通过 `/session` 或 `/reload` 看到资源诊断。保留两者可以同时满足“严格校验”和“真实使用不中断”。
