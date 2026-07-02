# Phase 9 学习笔记：Skills and Prompt Templates

对应架构文档：`dev-notes/architecture/phase-9-skills-prompts.md`

主要源码：

- `src/tau_coding/resources.py`
- `src/tau_coding/skills.py`
- `src/tau_coding/prompt_templates.py`
- `src/tau_coding/session.py`
- `src/tau_coding/__init__.py`
- `tests/test_resources.py`
- `tests/test_skills.py`
- `tests/test_prompt_templates.py`
- `tests/test_coding_session.py`

前置阶段：

- Phase 8：`CodingSession` 已经能加载资源、运行 prompt、持久化消息
- Phase 9：给 `CodingSession` 增加第一层 Markdown 资源系统

## 1. 这一阶段到底在做什么

Phase 9 给 Tau 增加了两个非常重要的能力：

- skills
- prompt templates

它们都来自 Markdown 文件。

你可以先这样理解：

```text
skill = 一份可复用的专业任务说明
prompt template = 一份可复用的提示词模板
```

比如一个 skill：

```text
python-testing
  告诉 agent：遇到 Python 测试任务时应该怎么做
```

比如一个 prompt template：

```text
review.md
  写好一段固定的 code review prompt
  用户输入 /review src/app.py 就能展开
```

Phase 9 的目标不是完整 system prompt assembly。

它只先建立资源层：

```text
磁盘 Markdown 文件
  -> loader
  -> Python 对象
  -> prompt expansion
  -> CodingSession 使用
```

## 2. 为什么 skills / prompt templates 放在 tau_coding

Skills 和 prompt templates 都是 coding-agent 应用资源。

它们依赖这些概念：

- 用户 home 目录
- 项目目录
- `.tau`
- `.agents`
- Markdown 文件
- slash-command 风格输入

这些都不是核心 agent brain 的职责。

所以它们放在：

```text
src/tau_coding/
```

而不是：

```text
src/tau_agent/
```

这继续遵守项目边界：

```text
tau_agent 只做可复用 agent harness
tau_coding 处理本地 coding agent 环境
```

## 3. Phase 9 的三个核心文件

### resources.py

负责通用资源能力：

- 资源目录路径
- frontmatter 解析
- description 推导
- resource diagnostics
- resource errors

### skills.py

负责 skill：

- `Skill`
- `load_skills`
- `load_skills_with_diagnostics`
- `expand_skill_command`
- `format_skill_invocation`
- `parse_skill_invocation`
- `build_skill_index`

### prompt_templates.py

负责 prompt template：

- `PromptTemplate`
- `load_prompt_templates`
- `load_prompt_templates_with_diagnostics`
- `render_prompt_template`
- `expand_prompt_template_command`

## 4. resources.py：通用资源基础

先看 `ResourceError`：

```python
class ResourceError(ValueError):
    """Raised when Tau resources are invalid or cannot be expanded."""
```

它继承自 `ValueError`。

意思是：

资源内容不合法、无法展开、变量缺失、skill 不存在时，可以抛这个错误。

例如：

```python
raise ResourceError("Unknown skill: testing")
```

为什么不直接用普通 `Exception`？

因为 `ResourceError` 更具体。

调用方可以只捕获资源错误：

```python
except ResourceError:
    ...
```

而不是吞掉所有异常。

## 5. ResourceDiagnostic：非致命问题

`ResourceDiagnostic` 是一个 dataclass：

```python
@dataclass(frozen=True, slots=True)
class ResourceDiagnostic:
    kind: str
    message: str
    path: Path | None = None
    name: str | None = None
    severity: str = "warning"
```

它表示“资源发现过程中发生了问题或提示，但不一定要中断程序”。

例如：

- 某个同名 skill 覆盖了另一个 skill
- 同一个目录里发现重复 skill
- 某个文件读不了

这些情况有时不应该让 Tau 整个崩掉。

所以当前代码有两种加载方式：

```python
load_skills(...)
```

遇到问题可能直接抛 `ResourceError`。

```python
load_skills_with_diagnostics(...)
```

尽量继续加载，把问题放进 diagnostics。

这对 TUI 很有用：

```text
能启动，但在侧边栏或命令里提示用户哪些资源有问题。
```

## 6. ResourceDiagnostic.format()

源码：

```python
def format(self) -> str:
    parts = [self.severity, self.kind]
    if self.name is not None:
        parts.append(self.name)
    label = " ".join(parts)
    if self.path is None:
        return f"{label}: {self.message}"
    return f"{label}: {self.message} ({self.path})"
```

这个方法把 diagnostic 变成一行人能读的文字。

例如：

```text
warning skill review: overrides lower-precedence resource at /old/path (/new/path)
```

Python 点：

```python
" ".join(parts)
```

表示用空格把 list 里的字符串连起来。

例如：

```python
" ".join(["warning", "skill", "review"])
```

得到：

```text
warning skill review
```

## 7. TauResourcePaths：资源目录配置

`TauResourcePaths` 是 Phase 9 的路径核心：

```python
@dataclass(frozen=True, slots=True)
class TauResourcePaths:
    root: Path = field(default_factory=lambda: Path.home() / ".tau")
    cwd: Path | None = None
    agents_root: Path | None = field(default_factory=lambda: Path.home() / ".agents")
    paths: TauPaths | None = None
```

默认情况下：

```text
root        = ~/.tau
agents_root = ~/.agents
```

所以基础目录是：

```text
~/.tau/skills
~/.tau/prompts
~/.agents/skills
~/.agents/prompts
```

如果还传了 `cwd`，当前实现还会加载项目级资源：

```text
<cwd>/.tau/skills
<cwd>/.tau/prompts
<cwd>/.agents/skills
<cwd>/.agents/prompts
```

以及项目级 `.agents` 根目录里的 `.md` skill 文件。

## 8. Python 知识：field(default_factory=...)

这里有：

```python
root: Path = field(default_factory=lambda: Path.home() / ".tau")
```

`field` 来自标准库：

```python
from dataclasses import field
```

`default_factory` 表示：

每次创建对象时，调用这个函数生成默认值。

为什么不用：

```python
root: Path = Path.home() / ".tau"
```

这里也不是绝对不行，但 `default_factory` 更适合“运行时计算默认值”。

它常用于：

- list
- dict
- set
- Path.home() 这种运行时路径

例如：

```python
@dataclass
class Bag:
    items: list[str] = field(default_factory=list)
```

这样每个 `Bag` 都有自己的 list，不会共享同一个 list。

## 9. skills_dir 和 prompts_dir

`TauResourcePaths` 里有两个基础属性：

```python
@property
def skills_dir(self) -> Path:
    return self.root / "skills"

@property
def prompts_dir(self) -> Path:
    return self.root / "prompts"
```

如果：

```python
paths = TauResourcePaths(root=Path("/tmp/resources"))
```

那么：

```text
paths.skills_dir  -> /tmp/resources/skills
paths.prompts_dir -> /tmp/resources/prompts
```

测试 `test_resource_paths_use_tau_subdirectories` 验证了这个行为。

## 10. skills_dirs：按优先级加载多个目录

当前实现中的 `skills_dirs`：

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

返回顺序是“优先级从低到高”。

也就是说越后面的目录越能覆盖前面的同名资源。

顺序大概是：

```text
~/.tau/skills
~/.agents/skills
~/.agents
<cwd>/.tau/skills
<cwd>/.agents/skills
<cwd>/.agents
```

为什么 project-local 放后面？

因为项目里的规则通常应该覆盖用户全局规则。

例如：

```text
~/.agents/skills/review.md
<project>/.agents/skills/review.md
```

如果同名，项目内的 `review.md` 更具体，所以覆盖用户级。

## 11. prompts_dirs：prompt templates 的目录

`prompts_dirs` 类似：

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

大概顺序：

```text
~/.tau/prompts
~/.agents/prompts
<cwd>/.tau/prompts
<cwd>/.agents/prompts
```

注意 prompt templates 不会从 `.agents` 根目录直接加载。

skills 会额外支持 `.agents` 根目录，是为了兼容一些 agent 资源布局。

## 12. _dedupe_paths：路径去重

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

作用：

如果多个配置算出同一个路径，只保留一次。

Python 点：

- `set()` 用来快速判断是否见过
- `continue` 表示跳过本轮循环
- `path.expanduser()` 会展开 `~`

例如：

```python
Path("~/x").expanduser()
```

会变成：

```text
/Users/yourname/x
```

## 13. parse_markdown_resource：解析 frontmatter

Markdown 资源可以这样写：

```md
---
description: Write tests
---
# Testing
Use pytest.
```

`parse_markdown_resource(text)` 返回两个东西：

```python
metadata, body = parse_markdown_resource(text)
```

其中：

```python
metadata == {"description": "Write tests"}
body == "# Testing\nUse pytest."
```

源码先统一换行：

```python
normalized = text.replace("\r\n", "\n").replace("\r", "\n")
```

这是为了兼容不同系统的换行：

- Unix/macOS 常见：`\n`
- Windows 常见：`\r\n`

然后判断是否以：

```text
---
```

开头。

如果不是，就认为没有 frontmatter。

## 14. 为什么不用完整 YAML 解析器

架构文档说得很清楚：

这个 parser 只支持简单的：

```text
key: value
```

不支持复杂 YAML。

好处：

- 不引入额外依赖
- 行为更可控
- 不执行任何代码
- 对 skill/prompt template 已经够用

源码：

```python
key, separator, value = stripped.partition(":")
if not separator:
    continue
metadata[key.strip()] = value.strip().strip("\"'")
```

`partition(":")` 会把字符串按第一个 `:` 分成三段。

例如：

```python
"description: Write tests".partition(":")
```

得到：

```python
("description", ":", " Write tests")
```

如果没有 `:`，中间的 `separator` 是空字符串。

## 15. derive_description：从内容推导描述

如果 frontmatter 没写 description，Tau 会尝试从正文推导。

源码：

```python
def derive_description(content: str) -> str | None:
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
        return stripped
    return None
```

规则：

1. 找第一行非空内容
2. 如果是 Markdown 标题，就去掉 `#`
3. 否则直接用第一段文字

例如：

```python
derive_description("\n# Title\nBody")
```

返回：

```text
Title
```

这让 skill/prompt 即使没写 frontmatter，也能有一个简短描述。

## 16. skills.py：Skill 数据结构

`Skill` 是一个 dataclass：

```python
@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    path: Path
    content: str
    description: str | None = None
```

字段含义：

- `name`：skill 名字，比如 `python-testing`
- `path`：Markdown 文件路径
- `content`：Markdown 正文内容
- `description`：简短描述

例如：

```python
Skill(
    name="testing",
    path=Path("/tmp/skills/testing.md"),
    content="# Testing\nRun pytest.",
    description="Testing",
)
```

注意：skill 的 `content` 是正文，不包含 frontmatter。

## 17. 支持两种 skill 文件布局

源码里 `_load_skills_from_dir_with_diagnostics()` 支持：

### 文件形式

```text
skills/git-review.md
```

skill name 是：

```text
git-review
```

也就是文件名去掉 `.md`。

### 目录形式

```text
skills/python-testing/SKILL.md
```

skill name 是：

```text
python-testing
```

也就是目录名。

为什么支持目录形式？

因为一个复杂 skill 可能还带额外参考文件：

```text
skills/python-testing/
  SKILL.md
  examples/
  scripts/
  references/
```

`SKILL.md` 是入口，其他文件可以被 skill 内容引用。

## 18. _load_skills_from_dir_with_diagnostics()

核心循环：

```python
for path in sorted(skills_dir.iterdir(), key=lambda item: item.name):
    skill_path: Path | None = None
    name = path.stem
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

逐句解释：

```python
skills_dir.iterdir()
```

遍历目录下一级文件和文件夹。

```python
sorted(..., key=lambda item: item.name)
```

按名称排序，保证加载顺序稳定。

```python
path.is_dir()
```

判断是不是目录。

```python
path.is_file()
```

判断是不是普通文件。

```python
path.suffix.lower() == ".md"
```

只接受 Markdown 文件。

```python
path.name.upper() == "AGENTS.MD"
```

排除 `AGENTS.md`。

因为 `AGENTS.md` 是项目指令，不是 skill。

测试 `test_agents_md_is_not_loaded_as_a_skill` 验证了这个规则。

## 19. 同目录重复 skill 怎么办

同一个目录里可能同时有：

```text
skills/dup/SKILL.md
skills/dup.md
```

它们的 skill name 都是：

```text
dup
```

源码用：

```python
seen: set[str] = set()
```

记录同目录内已经见过的名字。

如果重复：

```python
diagnostics.append(ResourceDiagnostic(...))
continue
```

`load_skills_with_diagnostics()` 会返回 diagnostic。

但 `load_skills()` 会把 diagnostic 转成 `ResourceError`：

```python
if diagnostics:
    first = diagnostics[0]
    raise ResourceError(first.message)
```

所以：

- 严格加载：直接报错
- 容错加载：保留第一个，报告 warning

## 20. 跨目录同名 skill：后者覆盖前者

`load_skills()` 里：

```python
skills_by_name: dict[str, Skill] = {}

for skills_dir in resource_paths.skills_dirs:
    for skill in _load_skills_from_dir(skills_dir):
        skills_by_name[skill.name] = skill
```

字典同一个 key 被赋值多次，后面的值会覆盖前面的。

因为 `skills_dirs` 是低优先级到高优先级，所以后加载的项目资源覆盖用户资源。

例如：

```text
~/.agents/skills/review.md
project/.agents/skills/review.md
```

最终保留项目里的 review。

`load_skills_with_diagnostics()` 会额外记录：

```text
overrides lower-precedence resource
```

这样用户知道发生了覆盖。

## 21. expand_skill_command()

用户输入：

```text
/skill:testing add parser tests
```

源码：

```python
def expand_skill_command(text: str, skills: Sequence[Skill]) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("/skill:"):
        return None

    command, separator, request = stripped.partition(" ")
    name = command.removeprefix("/skill:").strip()
    ...
    return format_skill_invocation(skill, additional_instructions)
```

如果不是 `/skill:` 开头，返回 `None`。

这表示：

```text
这不是 skill 命令，调用方可以继续按普通 prompt 处理。
```

如果是 `/skill:`，就解析出：

```text
name = testing
request = add parser tests
```

然后找到同名 skill，并格式化成完整 prompt。

## 22. Python 知识：Sequence

函数签名：

```python
def expand_skill_command(text: str, skills: Sequence[Skill]) -> str | None:
```

`Sequence` 来自：

```python
from collections.abc import Sequence
```

它表示“有顺序、可以遍历、可以按下标访问”的集合。

比如：

- list
- tuple

都可以作为 `Sequence`。

为什么不用 `list[Skill]`？

因为函数不需要修改 skills，只需要读。

用 `Sequence[Skill]` 更宽松。

调用方传 list 或 tuple 都行。

## 23. format_skill_invocation()

这是 skill 展开的核心格式：

```python
skill_block = (
    f'<skill name="{skill.name}" location="{skill.path}">\n'
    f"References are relative to {skill.path.parent}.\n\n"
    f"{skill.content.strip()}\n"
    "</skill>"
)
```

展开后类似：

```xml
<skill name="testing" location="/tmp/skills/testing.md">
References are relative to /tmp/skills.

# Testing
Run pytest.
</skill>

add parser tests
```

为什么把 skill 包在 XML-like 标签里？

因为模型更容易看出：

```text
这是一份 skill 指令
这是 skill 名字
这是 skill 文件路径
这是用户额外要求
```

`References are relative to ...` 很重要。

如果 skill 内容里说：

```text
Read examples/foo.md
```

agent 需要知道这个相对路径应该从哪里开始解析。

## 24. parse_skill_invocation()

`parse_skill_invocation()` 反向解析已经展开的 skill prompt：

```python
match = re.match(
    r'^<skill name="([^"]+)" location="([^"]+)">\n([\s\S]*?)\n</skill>(?:\n\n([\s\S]+))?$',
    text,
)
```

这里用到了标准库 `re`，也就是正则表达式。

它可以从文本里提取：

- skill name
- location
- skill content
- additional instructions

这个函数对 TUI 很有用。

TUI 不一定想把完整 skill 内容原样塞在聊天窗口里。

它可以显示成：

```text
Using skill: testing
add parser tests
```

而不是展示一大段 skill Markdown。

## 25. Python 知识：正则表达式 re

`re.match(pattern, text)` 表示：

从文本开头匹配一个模式。

这里的片段：

```regex
([^"]+)
```

表示：

匹配一个或多个不是双引号的字符，并捕获。

这里的：

```regex
[\s\S]*?
```

表示：

匹配任意字符，包括换行，尽量少匹配。

初学时不用一次背会正则。

你先知道它在这里的作用：

```text
从固定格式的 <skill ...>...</skill> 文本里提取字段。
```

## 26. build_skill_index()

源码：

```python
def build_skill_index(skills: Sequence[Skill]) -> str:
    if not skills:
        return "Available skills: none"
    lines = ["Available skills:"]
    for skill in sorted(skills, key=lambda item: item.name):
        description = skill.description or "No description"
        lines.append(f"- {skill.name}: {description}")
    return "\n".join(lines)
```

它生成简短 skill 列表：

```text
Available skills:
- testing: Test things
- review: Review diffs
```

这个列表给后续 system prompt assembly 使用。

注意它不是把完整 skill 内容塞进 system prompt。

它只是告诉 agent：

```text
有哪些 skill 可用，它们在哪里。
```

真正使用某个 skill 时，再通过 `/skill:name` 展开完整内容。

## 27. prompt_templates.py：PromptTemplate 数据结构

`PromptTemplate` 和 `Skill` 很像：

```python
@dataclass(frozen=True, slots=True)
class PromptTemplate:
    name: str
    path: Path
    content: str
    description: str | None = None
```

区别是：

skill 更像“任务方法说明”。

prompt template 更像“可填变量的提示词模板”。

例如 `review.md`：

```md
---
description: Review code
---
Review {{ arguments }} for correctness.
```

用户输入：

```text
/review src/app.py
```

展开为：

```text
Review src/app.py for correctness.
```

## 28. 模板变量语法

源码中有：

```python
_TEMPLATE_VARIABLE_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")
```

它匹配：

```text
{{ variable }}
{{variable}}
{{ variable_name }}
```

变量名规则：

- 第一个字符必须是字母或下划线
- 后面可以是字母、数字、下划线

例如：

```text
{{ topic }}
{{ focus }}
{{ base_branch }}
```

## 29. render_prompt_template()

函数签名：

```python
def render_prompt_template(
    template: PromptTemplate,
    variables: Mapping[str, str],
    *,
    missing: str | None = None,
) -> str:
```

它把模板里的变量替换成真实值。

例如：

```python
template.content = "Review {{ topic }} for {{ focus }}."
variables = {"topic": "auth", "focus": "security"}
```

结果：

```text
Review auth for security.
```

如果变量缺失，默认抛错：

```python
ResourceError("Missing prompt template variable: topic")
```

但如果传了：

```python
missing=""
```

缺失变量会被替换成空字符串。

## 30. Python 知识：Mapping

`Mapping[str, str]` 表示类似字典的只读映射。

常见传入对象就是：

```python
{"topic": "auth", "focus": "security"}
```

为什么用 `Mapping` 而不是 `dict`？

因为函数只需要读取：

```python
variables.get(name)
```

它不需要修改这个字典。

所以用更抽象的 `Mapping` 更合适。

## 31. expand_prompt_template_command()

用户输入：

```text
/example src/app.py
```

源码先判断：

```python
if not stripped.startswith("/") or stripped.startswith("//") or stripped.startswith("/skill:"):
    return None
```

意思是：

- 不以 `/` 开头：不是 prompt template 命令
- 以 `//` 开头：忽略，可能是用户想输入普通文本
- 以 `/skill:` 开头：这是 skill，不是 prompt template

然后解析命令名：

```python
name, args = _parse_prompt_template_command(stripped)
```

`/example src/app.py` 会得到：

```python
name = "example"
args = "src/app.py"
```

再按 name 找同名模板。

如果找不到，返回 `None`。

这很重要：未知 slash command 不一定是 prompt template，它可能交给 command registry 处理。

## 32. arguments / args 特殊变量

架构文档说：

调用命令后的文本会放进：

```text
{{ arguments }}
```

或：

```text
{{ args }}
```

源码：

```python
rendered = render_prompt_template(
    template,
    {"arguments": args, "args": args},
    missing="",
)
```

也就是说：

```text
/review src/app.py
```

里的 `src/app.py` 可以被模板用：

```md
Review {{ arguments }}.
```

展开成：

```text
Review src/app.py.
```

## 33. 如果模板没有 arguments 变量怎么办

源码：

```python
if args and not _template_references_arguments(template.content):
    return f"{rendered.rstrip()}\n\n{args}"
return rendered
```

意思是：

如果用户输入了参数，但模板没有写 `{{ arguments }}` 或 `{{ args }}`，Tau 会把参数追加到模板末尾。

例如模板：

```md
Review this code.
```

用户输入：

```text
/review src/app.py
```

展开成：

```text
Review this code.

src/app.py
```

这个设计很贴心：

用户不需要每个模板都显式写 `{{ arguments }}`。

## 34. strict render 和 forgiving command expansion

这里有一个容易混的点。

直接调用：

```python
render_prompt_template(template, variables)
```

是严格模式。

缺变量就报错。

但是 slash-command expansion：

```python
expand_prompt_template_command(...)
```

会传：

```python
missing=""
```

所以缺失自定义变量会变成空字符串。

为什么？

因为 TUI 用户输入 `/review 168` 时，如果模板里有一个可选变量：

```md
Base branch: {{ base_branch }}
Review PR {{ arguments }}.
```

用户没有提供 `base_branch`，不应该让整个输入崩掉。

测试：

```python
test_expand_prompt_template_command_blanks_missing_custom_variables
```

验证了这个行为。

## 35. CodingSession 如何接入 Phase 9

Phase 8 的 `CodingSession.load()` 当前有：

```python
resource_paths = resource_paths_with_cwd(config.resource_paths, config.cwd)
resources = _load_session_resources(resource_paths, config.context_files)
```

`_load_session_resources()` 里：

```python
loaded_skills, skill_diagnostics = load_skills_with_diagnostics(resource_paths)
loaded_prompt_templates, prompt_diagnostics = load_prompt_templates_with_diagnostics(
    resource_paths
)
```

然后放到 `SessionResources`：

```python
return SessionResources(
    skills=tuple(loaded_skills),
    prompt_templates=tuple(loaded_prompt_templates),
    context_files=...,
    diagnostics=...,
)
```

最后 `CodingSession` 保存：

```python
self._skills = skills
self._prompt_templates = prompt_templates
self._resource_diagnostics = resource_diagnostics
```

对外暴露：

```python
session.skills
session.prompt_templates
session.resource_diagnostics
```

## 36. expand_prompt_text()

`CodingSession` 真正使用 skills/templates 的入口是：

```python
def expand_prompt_text(self, text: str) -> str:
    expanded_prompt = expand_prompt_template_command(text, self._prompt_templates)
    if expanded_prompt is not None:
        return expanded_prompt
    expanded_skill = expand_skill_command(text, self._skills)
    return expanded_skill if expanded_skill is not None else text
```

顺序是：

1. 先尝试 prompt template
2. 再尝试 skill
3. 都不是就返回原文

为什么 `/skill:` 不会被 prompt template 吃掉？

因为 `expand_prompt_template_command()` 明确排除了：

```python
stripped.startswith("/skill:")
```

所以 skill 有自己的通道。

## 37. handle_command() 为什么不处理 /skill:name

`CodingSession.handle_command()` 里有：

```python
if expand_prompt_template_command(text, self._prompt_templates) is not None:
    return CommandResult(handled=False)
return self._command_registry.execute(self, text)
```

而 `CommandRegistry.execute()` 里也有：

```python
if stripped.startswith("/skill:"):
    return CommandResult(handled=False)
```

意思是：

`/skill:name` 不是那种“处理完就结束”的命令。

它是 prompt expansion directive。

也就是说：

```text
/skill:testing add tests
```

应该被展开后继续送进模型。

它不是像 `/quit` 那样让 UI 退出。

测试 `test_session_loads_and_expands_skills` 会确认：

```python
assert session.handle_command("/skill:testing").handled is False
```

## 38. 一次 /skill 输入的完整流程

假设磁盘里有：

```text
resources/skills/testing.md
```

内容：

```md
# Testing
Run pytest.
```

用户输入：

```text
/skill:testing add tests
```

流程：

```text
CodingSession.load()
  -> load_skills_with_diagnostics()
  -> Skill(name="testing", ...)

session.prompt("/skill:testing add tests")
  -> expand_prompt_text()
  -> expand_skill_command()
  -> format_skill_invocation()
  -> AgentHarness.prompt(expanded_text)
```

模型最终看到的不是原始 `/skill:...`。

模型看到的是：

```xml
<skill name="testing" location=".../testing.md">
References are relative to .../skills.

# Testing
Run pytest.
</skill>

add tests
```

测试里通过 `FakeProvider` 记录 provider 收到的 messages，确认：

```python
assert '<skill name="testing" location="' in provider.calls[0][2][0].content
```

## 39. 一次 prompt template 输入的完整流程

假设磁盘里有：

```text
resources/prompts/example.md
```

内容：

```md
Custom prompt for {{ arguments }}.
```

用户输入：

```text
/example src/app.py
```

流程：

```text
CodingSession.load()
  -> load_prompt_templates_with_diagnostics()
  -> PromptTemplate(name="example", ...)

session.prompt("/example src/app.py")
  -> expand_prompt_text()
  -> expand_prompt_template_command()
  -> render_prompt_template()
  -> AgentHarness.prompt("Custom prompt for src/app.py.")
```

测试：

```python
assert provider.calls[0][2][0].content == "Custom prompt for src/app.py."
```

## 40. __init__.py 的公开 API

`src/tau_coding/__init__.py` 里把 Phase 9 的对象导出：

```python
from tau_coding.prompt_templates import (
    PromptTemplate,
    expand_prompt_template_command,
    load_prompt_templates,
    load_prompt_templates_with_diagnostics,
    render_prompt_template,
)

from tau_coding.skills import (
    Skill,
    build_skill_index,
    expand_skill_command,
    format_skill_invocation,
    load_skills,
    load_skills_with_diagnostics,
    parse_skill_invocation,
)
```

这样外部可以写：

```python
from tau_coding import load_skills, load_prompt_templates
```

而不是：

```python
from tau_coding.skills import load_skills
from tau_coding.prompt_templates import load_prompt_templates
```

这是 package public API 的一部分。

## 41. 当前实现比 Phase 9 初始文档多了什么

`phase-9-skills-prompts.md` 重点讲：

```text
~/.tau/skills
~/.tau/prompts
```

但当前源码已经支持更多目录：

```text
~/.agents/skills
~/.agents/prompts
project/.tau/skills
project/.tau/prompts
project/.agents/skills
project/.agents/prompts
project/.agents
```

这说明后续 Phase 13 / Phase 16 等资源发现能力已经叠加进来了。

学习时要区分：

```text
Phase 9 的主线：
  Markdown resource -> Python object -> prompt expansion

后续扩展：
  多目录发现、项目级资源、override diagnostics
```

但这些扩展并不改变 Phase 9 的基本模型。

## 42. tests/test_resources.py 应该看什么

这个测试文件验证：

- `TauResourcePaths` 能算出 skills/prompts 目录
- 加上 cwd 后会包含项目级目录
- frontmatter 能解析 description
- Windows CRLF 换行会被规范成 `\n`
- `derive_description()` 能从标题或第一段推导描述

重点测试：

```text
test_resource_paths_use_tau_subdirectories
test_resource_paths_include_agents_and_project_directories
test_parse_frontmatter_description
test_parse_frontmatter_normalizes_crlf_line_endings
test_derive_description_uses_first_heading_or_paragraph
```

## 43. tests/test_skills.py 应该看什么

它验证：

- skills 目录不存在时返回空 list
- 目录形式和文件形式都能加载
- user/project `.agents` 目录会参与加载
- 项目 skill 覆盖用户 skill
- diagnostic 会报告覆盖
- 同目录重复 skill 会报错或 diagnostic
- `AGENTS.md` 不会被当成 skill
- `/skill:name` 能展开
- 未知 skill 会报 `ResourceError`
- skill index 能生成

最重要的是：

```text
test_expand_skill_command_includes_skill_and_user_request
```

它把 Phase 9 的核心行为测得很清楚。

## 44. tests/test_prompt_templates.py 应该看什么

它验证：

- prompts 目录不存在时返回空 list
- Markdown prompt template 能加载
- user/project `.agents/prompts` 会参与加载
- 项目 template 覆盖用户 template
- diagnostic 会报告覆盖
- `{{ variable }}` 会替换
- 缺变量时直接 render 会报错
- slash command expansion 会更宽容
- 没有 `{{ arguments }}` 时会追加参数
- 未知 slash command 返回 `None`

最核心测试：

```text
test_render_prompt_template_replaces_variables
test_expand_prompt_template_command_replaces_slash_command
test_expand_prompt_template_command_appends_arguments_without_placeholder
```

## 45. 初学者容易误解的点

### 误解 1：skill 会自动全部塞进 system prompt

不是。

Phase 9 的 skill 主要是可加载、可索引、可通过 `/skill:name` 展开。

后续 system prompt 可能包含 skill index，但不应该把每个 skill 的完整内容都塞进去。

### 误解 2：prompt template 是命令系统的一部分

它看起来像 slash command，但本质是 prompt expansion。

例如：

```text
/review src/app.py
```

不是执行命令，而是展开成一段 prompt 再交给模型。

### 误解 3：ResourceDiagnostic 就是错误

不完全是。

它是“发现资源时的提示/警告/错误记录”。

有些 diagnostic 不阻止 session 继续运行。

### 误解 4：同名资源一定报错

同一个目录内同名通常是问题。

跨目录同名是 override 机制。

项目级覆盖用户级是预期行为。

## 46. Phase 9 用一句话总结

Phase 9 的价值是：把 Markdown 文件变成 Tau 可加载的资源对象，skills 提供可复用任务说明，prompt templates 提供可展开提示词模板，并通过 `CodingSession.expand_prompt_text()` 在用户 prompt 进入 `AgentHarness` 之前完成资源展开；这样后续 system prompt、TUI autocomplete、resource reload 和项目级 agent 指令都有了统一资源基础。

## 47. 我的问题与推荐回答

问题：为什么 `/skill:testing add tests` 不应该被 `handle_command()` 当成普通 slash command 处理掉，而是要返回 `handled=False` 继续进入 `session.prompt()`？

我的推荐回答：

因为 `/skill:testing add tests` 的目的不是让前端执行一个动作后结束，而是把用户输入扩展成一段更完整的 prompt 交给模型。`handle_command()` 适合处理 `/quit`、`/new` 这类 UI/session 控制命令；skill 和 prompt template 属于 prompt expansion。让它返回 `handled=False`，后续 `session.prompt()` 会调用 `expand_prompt_text()`，把 `/skill:testing add tests` 展开成包含 skill Markdown、skill 路径和用户额外要求的完整消息，再送进 `AgentHarness`。这样 command system 和 prompt resource system 的边界更清楚。
