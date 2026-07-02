# Phase 10 学习笔记：System Prompt Assembly

对应架构文档：`dev-notes/architecture/phase-10-system-prompt.md`

主要源码：

- `src/tau_coding/system_prompt.py`
- `src/tau_coding/session.py`
- `src/tau_coding/cli.py`
- `src/tau_agent/tools.py`
- `tests/test_system_prompt.py`
- `tests/test_cli.py`
- `tests/test_coding_session.py`

前置阶段：

- Phase 5：工具有 `prompt_snippet` 和 `prompt_guidelines`
- Phase 8：`CodingSession` 负责创建 `AgentHarness`
- Phase 9：skills 和 prompt templates 可以从 Markdown 资源加载
- Phase 10：把工具、规则、项目上下文、skills、日期、cwd 组装成统一 system prompt

## 1. 这一阶段到底在做什么

Phase 10 增加了 Tau 的标准 system prompt builder：

```python
build_system_prompt(...)
```

它位于：

```text
src/tau_coding/system_prompt.py
```

你可以先用一句话理解：

Phase 10 把“告诉模型它是谁、能用什么工具、该遵守什么规则、当前项目有什么指令”这件事，从 CLI/session 里抽出来，变成一个统一、可测试的 prompt 组装模块。

在 Phase 10 之前，print-mode CLI 可能只用一个很小的本地 prompt builder。

但项目继续发展后，system prompt 需要包含更多内容：

- Tau 的身份
- 可用工具
- 工具使用指南
- 额外 guidelines
- 自定义 system prompt
- append system prompt
- 项目上下文文件，比如 `AGENTS.md`
- skills index
- 当前日期
- 当前工作目录

如果这些逻辑散落在 CLI、TUI、CodingSession 里，就会很难维护。

所以 Phase 10 做了一个统一入口：

```text
BuildSystemPromptOptions
  -> build_system_prompt()
  -> str
```

## 2. 为什么 system prompt 属于 tau_coding

system prompt 里包含很多 coding-agent 应用层信息：

- 当前 cwd
- 可用 coding tools
- 项目 instructions
- skills
- prompt 附加规则

这些不是 `tau_agent` 的核心逻辑。

`tau_agent` 只需要接收一个已经准备好的字符串：

```python
AgentHarnessConfig(system=system_prompt)
```

至于这个字符串怎么由项目资源组装出来，是 `tau_coding` 的职责。

所以：

```text
tau_coding.system_prompt
  构建 prompt

tau_agent.AgentHarness
  使用 prompt
```

这个边界非常干净。

## 3. system_prompt.py 的核心对象

这个文件主要有两个 dataclass：

```python
ProjectContextFile
BuildSystemPromptOptions
```

以及几个函数：

```python
build_system_prompt
format_available_tools
collect_prompt_guidelines
format_guidelines
format_project_context
format_skills_for_prompt
```

整体关系：

```text
BuildSystemPromptOptions
  cwd
  tools
  skills
  custom_prompt
  append_system_prompt
  context_files
  current_date
  extra_guidelines
        |
        v
build_system_prompt()
        |
        v
system prompt string
```

## 4. ProjectContextFile

源码：

```python
@dataclass(frozen=True, slots=True)
class ProjectContextFile:
    """A project instruction file included in the system prompt."""

    path: str
    content: str
```

它表示一个要放进 system prompt 的项目上下文文件。

例如：

```python
ProjectContextFile(
    path="/repo/AGENTS.md",
    content="Follow project rules.",
)
```

为什么 path 是 `str`，不是 `Path`？

因为它最终要格式化进 prompt 文本里。

而且有些路径可能来自不同来源，不一定总是本地 `Path` 对象。

## 5. BuildSystemPromptOptions

源码：

```python
@dataclass(frozen=True, slots=True)
class BuildSystemPromptOptions:
    cwd: Path
    tools: Sequence[AgentTool] = ()
    skills: Sequence[Skill] = ()
    custom_prompt: str | None = None
    append_system_prompt: str | None = None
    context_files: Sequence[ProjectContextFile] = ()
    current_date: date | None = None
    extra_guidelines: Sequence[str] = field(default_factory=tuple)
```

它是 system prompt 的输入配置。

逐个解释：

### cwd

当前工作目录。

最终会出现在 prompt 末尾：

```text
Current working directory: /path/to/project
```

### tools

当前可用工具。

工具来自 Phase 5：

```python
create_coding_tools(cwd=tmp_path)
```

每个工具可能带：

- `prompt_snippet`
- `prompt_guidelines`

### skills

Phase 9 加载出来的 skill 列表。

注意：system prompt 只放 skill index，不放完整 skill 内容。

### custom_prompt

如果传入，表示用用户自定义 prompt 替换默认 Tau 身份、工具、guidelines 部分。

注意：

```python
custom_prompt=""
```

和：

```python
custom_prompt=None
```

含义不同。

这一点后面单独讲。

### append_system_prompt

追加到 system prompt 后面的额外规则。

它不会替换默认 prompt，只是追加。

### context_files

项目上下文文件，例如：

```text
AGENTS.md
CLAUDE.md
```

Phase 10 只负责格式化传进来的 context files。

自动发现这些文件是后续 phase 扩展的内容。

### current_date

当前日期。

测试可以传固定日期：

```python
date(2026, 6, 17)
```

这样测试不会因为真实日期变化而失败。

如果没传，就用：

```python
date.today()
```

### extra_guidelines

额外规则列表。

它会和工具自带规则合并、去重。

## 6. Python 知识：datetime.date

源码：

```python
from datetime import date
```

`date` 表示日期，不包含时间。

例如：

```python
date(2026, 6, 17)
```

表示：

```text
2026-06-17
```

调用：

```python
current_date.isoformat()
```

得到字符串：

```text
2026-06-17
```

为什么测试要传固定日期？

因为如果代码直接用今天日期，测试每天结果都不同。

固定日期能让 prompt 输出 deterministic。

deterministic 的意思是：

同样输入永远得到同样输出。

## 7. build_system_prompt() 的主入口

源码开头：

```python
def build_system_prompt(options: BuildSystemPromptOptions) -> str:
    current_date = options.current_date or date.today()
    cwd = _format_path(options.cwd)
    append_section = f"\n\n{options.append_system_prompt}" if options.append_system_prompt else ""
```

这三行分别准备：

- 日期
- cwd 字符串
- append prompt 段落

`options.current_date or date.today()` 的意思是：

如果 `current_date` 有值，就用它。

如果是 `None`，就用今天。

## 8. Python 知识：or 的默认值写法

```python
current_date = options.current_date or date.today()
```

如果左边是真值，就返回左边。

如果左边是假值，就返回右边。

例如：

```python
None or "default"
```

得到：

```text
default
```

但要小心：

```python
"" or "default"
```

也会得到：

```text
default
```

所以在需要区分空字符串和 None 的地方，不能随便用 `or`。

源码里对 `custom_prompt` 就没有用 `or`，而是判断：

```python
if options.custom_prompt is not None:
```

这是一个很重要的细节。

## 9. 默认 prompt 形状

如果没有传 `custom_prompt`，源码构建默认 prompt：

```python
prompt = (
    "You are an expert coding assistant operating inside Tau, a coding agent harness. "
    "You help users by reading files, executing commands, editing code, and writing new files."
    f"\n\nAvailable tools:\n{format_available_tools(options.tools)}"
    "\n\nIn addition to the tools above, you may have access to other custom tools "
    "depending on the project."
    f"\n\nGuidelines:\n{format_guidelines(options.tools, options.extra_guidelines)}"
)
```

默认 prompt 包括：

1. Tau 身份
2. 可用工具
3. 自定义工具说明
4. guidelines

之后再追加：

```python
prompt += append_section
prompt += format_project_context(options.context_files)
if _has_tool(options.tools, "read"):
    prompt += format_skills_for_prompt(options.skills)
prompt += f"\nCurrent date: {current_date.isoformat()}"
prompt += f"\nCurrent working directory: {cwd}"
```

最终顺序是：

```text
身份
Available tools
Guidelines
append prompt
project context
available skills
Current date
Current working directory
```

## 10. format_available_tools()

源码：

```python
def format_available_tools(tools: Sequence[AgentTool]) -> str:
    lines = [f"- {tool.name}: {tool.prompt_snippet}" for tool in tools if tool.prompt_snippet]
    return "\n".join(lines) if lines else "(none)"
```

它把工具格式化成：

```text
- read: Read file contents
- write: Create or overwrite files
- edit: Make precise file edits
- bash: Execute bash commands
```

注意条件：

```python
if tool.prompt_snippet
```

只有有 `prompt_snippet` 的工具才会显示在 system prompt 的 Available tools 里。

这让 Tau 可以把某些工具发给 provider，但不在 prompt 中显式展示。

测试：

```python
test_tool_without_prompt_snippet_is_hidden_from_available_tools
```

验证没有 snippet 时返回：

```text
(none)
```

## 11. Python 知识：列表推导式

这一行：

```python
lines = [f"- {tool.name}: {tool.prompt_snippet}" for tool in tools if tool.prompt_snippet]
```

叫 list comprehension，列表推导式。

等价于：

```python
lines = []
for tool in tools:
    if tool.prompt_snippet:
        lines.append(f"- {tool.name}: {tool.prompt_snippet}")
```

它适合写简单的“遍历 + 过滤 + 转换”。

## 12. collect_prompt_guidelines()

这个函数负责收集和去重规则。

源码：

```python
names = {tool.name for tool in tools}
guidelines: list[str] = []
seen: set[str] = set()
```

`names` 是工具名集合。

例如：

```python
{"read", "write", "edit", "bash"}
```

然后定义内部函数：

```python
def add(value: str) -> None:
    normalized = value.strip()
    if not normalized or normalized in seen:
        return
    seen.add(normalized)
    guidelines.append(normalized)
```

这个 `add()` 做三件事：

1. 去掉前后空白
2. 空字符串不要
3. 已出现过的不要

所以 guidelines 会保持稳定顺序，并去重。

## 13. Python 知识：内部函数

`add()` 定义在 `collect_prompt_guidelines()` 里面。

这叫内部函数。

它可以访问外层变量：

```python
seen
guidelines
```

这让代码更集中：

```python
添加 guideline 的规则只写一次
```

后面所有地方都调用：

```python
add(...)
```

## 14. bash 和探索工具的规则

源码：

```python
has_bash = "bash" in names
has_exploration_tools = bool({"grep", "find", "ls"} & names)
if has_bash and not has_exploration_tools:
    add("Use bash for file operations like ls, rg, find")
elif has_bash and has_exploration_tools:
    add(
        "Prefer grep/find/ls tools over bash for file exploration (faster, respects .gitignore)"
    )
```

这段逻辑意思是：

如果只有 bash，没有单独的 grep/find/ls 工具，就告诉模型：

```text
Use bash for file operations like ls, rg, find
```

如果未来有独立 grep/find/ls 工具，就告诉模型优先用那些工具。

当前 coding tools 是：

```text
read/write/edit/bash
```

所以默认会出现：

```text
- Use bash for file operations like ls, rg, find
```

## 15. 工具自己的 prompt_guidelines

`AgentTool` 定义在 `src/tau_agent/tools.py`：

```python
@dataclass(frozen=True, slots=True)
class AgentTool:
    name: str
    description: str
    input_schema: Mapping[str, JSONValue]
    executor: ToolExecutor
    prompt_snippet: str | None = None
    prompt_guidelines: tuple[str, ...] = ()
```

每个工具可以自带：

```python
prompt_guidelines
```

例如 read 工具可能告诉模型：

```text
Use read to examine files instead of cat or sed.
```

`collect_prompt_guidelines()` 会遍历：

```python
for tool in tools:
    for guideline in tool.prompt_guidelines:
        add(guideline)
```

这让工具自己的使用规则随工具一起注册。

如果工具没有启用，它的规则也不会进入 prompt。

## 16. format_guidelines()

源码：

```python
def format_guidelines(tools: Sequence[AgentTool], extra_guidelines: Sequence[str] = ()) -> str:
    return "\n".join(
        f"- {guideline}" for guideline in collect_prompt_guidelines(tools, extra_guidelines)
    )
```

它把 guidelines 变成 Markdown bullet list：

```text
- Use bash for file operations like ls, rg, find
- Use read to examine files instead of cat or sed.
- Be concise in your responses
- Show file paths clearly when working with files
```

`collect_prompt_guidelines()` 最后一定会加：

```python
add("Be concise in your responses")
add("Show file paths clearly when working with files")
```

所以默认 prompt 至少有这两个通用规则。

## 17. custom_prompt 的行为

如果传入：

```python
custom_prompt="Custom base."
```

源码走这个分支：

```python
if options.custom_prompt is not None:
    prompt = options.custom_prompt
    prompt += append_section
    prompt += format_project_context(options.context_files)
    if _has_tool(options.tools, "read"):
        prompt += format_skills_for_prompt(options.skills)
    prompt += f"\nCurrent date: {current_date.isoformat()}"
    prompt += f"\nCurrent working directory: {cwd}"
    return prompt
```

重要点：

custom prompt 会替换默认的：

- Tau 身份
- Available tools
- Guidelines

但仍然保留：

- append system prompt
- project context
- skills section
- current date
- current working directory

这和架构文档说的 Pi 行为一致。

## 18. 空字符串 custom_prompt 也是 custom

测试里有：

```python
custom_prompt=""
```

期望：

```python
assert "Available tools:" not in prompt
```

也就是说空字符串也表示：

```text
用户明确要用空 custom prompt
```

它不是“没传”。

源码用：

```python
if options.custom_prompt is not None:
```

而不是：

```python
if options.custom_prompt:
```

这正是为了区分：

```python
None
```

和：

```python
""
```

## 19. format_project_context()

源码：

```python
def format_project_context(context_files: Sequence[ProjectContextFile]) -> str:
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

如果没有 context files，返回空字符串。

如果有，比如：

```python
ProjectContextFile(path="/repo/AGENTS.md", content="Follow rules.")
```

格式化后大概是：

```xml
<project_context>

Project-specific instructions and guidelines:

<project_instructions path="/repo/AGENTS.md">
Follow rules.
</project_instructions>

</project_context>
```

XML-like 包装让模型更容易识别：

- 哪段是项目上下文
- 上下文来自哪个文件
- 文件内容是什么

## 20. Python 知识：xml.sax.saxutils.escape

源码：

```python
from xml.sax.saxutils import escape
```

`escape()` 用来转义 XML 特殊字符。

例如：

```python
escape("review&check")
```

会变成：

```text
review&amp;check
```

```python
escape("Review <code>")
```

会变成：

```text
Review &lt;code&gt;
```

为什么需要？

因为 system prompt 里用了 XML-like 标签。

如果 skill 名字里本身有 `<`、`&`，不转义会破坏结构。

测试：

```python
test_skills_are_formatted_as_xml_and_escaped
```

验证了这个行为。

## 21. format_skills_for_prompt()

源码：

```python
def format_skills_for_prompt(skills: Sequence[Skill]) -> str:
    if not skills:
        return ""

    lines = [
        "\n\nThe following skills provide specialized instructions for specific tasks.",
        "Read the full skill file when the task matches its description.",
        ...
        "<available_skills>",
    ]
```

它不会放完整 skill 内容。

它只放 skill index：

```xml
<available_skills>
  <skill>
    <name>python-testing</name>
    <description>Write and run Python tests.</description>
    <location>/home/user/.tau/skills/python-testing/SKILL.md</location>
  </skill>
</available_skills>
```

为什么只放 index？

因为完整 skill 可能很长。

system prompt 应该保持相对轻量。

当任务真的匹配某个 skill 时，模型可以用 read 工具读取完整 skill 文件，或者用户显式用 `/skill:name` 展开。

## 22. 为什么只有 read 工具存在时才放 skills

`build_system_prompt()` 里：

```python
if _has_tool(options.tools, "read"):
    prompt += format_skills_for_prompt(options.skills)
```

如果没有 `read` 工具，就不放 skills。

原因是 skill section 里会告诉模型：

```text
Read the full skill file when the task matches its description.
```

如果没有 read 工具，模型看到了 skill location 却没法读取，反而会困惑。

测试：

```python
test_skills_are_included_only_when_read_tool_is_available
```

验证：

- 没有 read 工具 -> 不包含 `<available_skills>`
- 有 read 工具 -> 包含 `<available_skills>`

## 23. prompt templates 为什么不进入 system prompt

Phase 10 文档特别说：

Prompt templates are not inserted into the system prompt.

原因：

prompt template 是用户输入扩展资源。

例如：

```text
/review src/app.py
```

在用户 prompt 进入 harness 前展开。

它不是告诉模型“你可以主动选择一个模板”的机制。

Skills 更像可被模型理解和选择的任务说明，所以可以放 index。

Prompt templates 更像用户快捷输入，所以不放 system prompt。

## 24. CodingSession 如何接入 system prompt

在 `src/tau_coding/session.py` 的 `CodingSession.load()` 里：

```python
system = (
    config.system
    if config.system is not None
    else build_system_prompt(
        BuildSystemPromptOptions(
            cwd=config.cwd,
            tools=tools,
            skills=resources.skills,
            custom_prompt=config.custom_system_prompt,
            append_system_prompt=config.append_system_prompt,
            context_files=resources.context_files,
        )
    )
)
```

这里的重点是：

如果调用方明确传了 `system`，就用它。

如果 `system is None`，才自动构建。

这意味着：

```python
system=""
```

会保留空字符串。

测试：

```python
test_session_preserves_explicit_empty_system_prompt
```

验证 provider 收到的 system prompt 就是：

```text
""
```

## 25. Print-mode CLI 如何接入

`src/tau_coding/cli.py` 的 `run_print_mode()` 当前会创建 `CodingSession`：

```python
session = await CodingSession.load(
    CodingSessionConfig(
        provider=provider,
        model=model,
        cwd=cwd,
        storage=storage or _MemorySessionStorage(),
        resource_paths=resource_paths,
        ...
    )
)
```

它没有传 `system`。

所以 `CodingSession.load()` 会自动调用：

```python
build_system_prompt(...)
```

测试 `test_run_print_mode_prints_final_text` 会确认：

```python
assert provider.calls[0][1] == build_system_prompt(
    BuildSystemPromptOptions(cwd=tmp_path, tools=create_coding_tools(cwd=tmp_path))
)
```

也就是说 print mode 和 coding session mode 用的是同一套 builder。

## 26. system prompt 的测试价值

System prompt 很容易写成“看起来差不多”的字符串拼接。

但 Tau 给它写了专门测试：

- 默认 prompt 包含工具、guidelines、日期、cwd
- 没有 prompt snippet 的工具不显示
- guidelines 去重
- custom prompt 替换默认部分
- 空 custom prompt 仍然生效
- skills XML 转义
- 只有 read 工具存在时才包含 skills
- print mode 使用同一个 builder
- CodingSession 在 system 省略时自动构建

这很重要。

因为 system prompt 是 agent 行为的“隐形代码”。

如果它不可测试，后续改动很容易悄悄改变 agent 行为。

## 27. 初学者容易误解的点

### 误解 1：system prompt 就是随便写一段字符串

不是。

在 coding agent 里，system prompt 是架构接口。

它承载：

- 身份
- 工具说明
- 使用规则
- 项目上下文
- skill index
- 当前环境信息

### 误解 2：custom_prompt 会替换一切

不是。

custom prompt 只替换默认身份、工具、guidelines。

Tau 仍会追加：

- append prompt
- project context
- skills
- current date
- cwd

### 误解 3：skills 的完整内容进入 system prompt

不是。

system prompt 里只放 skill index。

完整内容通过 read 或 `/skill:name` 获取。

### 误解 4：`system=""` 和 `system=None` 一样

不一样。

`None` 表示“没有显式传 system，请自动构建”。

`""` 表示“显式传了空 system prompt，请使用空字符串”。

## 28. Phase 10 用一句话总结

Phase 10 的价值是：把 Tau 的 system prompt 从分散的局部字符串拼接，升级成一个确定性的共享组装层；它根据 cwd、tools、tool guidelines、skills、project context、custom/append prompt 和当前日期生成 Pi-style system prompt，并让 print mode 与 CodingSession 都使用同一套入口，为后续 TUI、resource discovery、reload 和 provider 配置提供统一基础。

## 29. 我的问题与推荐回答

问题：为什么 `custom_prompt=""` 不能被当作“没传 custom prompt”，而必须保留为空字符串？

我的推荐回答：

因为 `None` 和空字符串表达的是两个不同意图。`custom_prompt=None` 表示调用方没有提供自定义 system prompt，Tau 应该使用默认身份、工具说明和 guidelines 自动构建；`custom_prompt=""` 表示调用方明确提供了一个空的自定义 prompt，Tau 应尊重这个选择，不再插入默认身份和工具说明。源码用 `if options.custom_prompt is not None` 而不是 `if options.custom_prompt`，正是为了保留这个语义差异。`CodingSessionConfig.system` 也类似：`system=None` 才自动 build，`system=""` 会原样传给 provider。
