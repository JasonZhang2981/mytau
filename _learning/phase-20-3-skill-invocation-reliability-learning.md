# Phase 20.3 学习笔记：Skill Invocation Reliability

对应架构文档：`dev-notes/architecture/phase-20-3-skill-invocation.md`

对应源码：

- `src/tau_coding/skills.py`
- `src/tau_coding/system_prompt.py`
- `src/tau_coding/session.py`
- `src/tau_coding/commands.py`
- `src/tau_coding/tui/state.py`
- `src/tau_coding/tui/adapter.py`
- `src/tau_coding/tui/autocomplete.py`
- `tests/test_skills.py`
- `tests/test_system_prompt.py`
- `tests/test_coding_session.py`
- `tests/test_commands.py`
- `tests/test_cli.py`
- `tests/test_tui_adapter.py`
- `tests/test_tui_autocomplete.py`

## 1. 这一阶段到底在做什么

Phase 20.3 让 Tau 的 skill 调用更可靠。

这里的 skill 指的是 markdown 技能文件，例如：

```text
.tau/skills/testing.md
.agents/skills/review.md
~/.tau/skills/python/SKILL.md
```

前面阶段已经实现了 skill discovery。

Phase 20.3 更关心：

```text
技能如何暴露给模型？
用户如何手动调用技能？
调用后 prompt 格式是否清楚？
TUI 如何避免把大段 skill markdown 直接糊在聊天界面里？
```

## 2. 两条 skill 使用路径

Phase 20.3 有两条路径：

```text
自动路径：模型看到 skill index，然后自己 read 完整 skill 文件
手动路径：用户输入 /skill:name request，Tau 直接把完整 skill 内容展开进 prompt
```

这两条路径都重要。

### 2.1 自动路径

用户只是说：

```text
add tests
```

模型从 system prompt 里看到：

```xml
<available_skills>
  <skill>
    <name>testing</name>
    <description>Use when writing tests</description>
    <location>/repo/.agents/skills/testing.md</location>
  </skill>
</available_skills>
```

如果模型判断任务匹配 `testing` skill，就调用 `read` 工具读取这个文件。

### 2.2 手动路径

用户明确说：

```text
/skill:testing add parser tests
```

Tau 不等模型自己发现。

它直接把 prompt 展开成：

```text
<skill name="testing" location="/repo/.agents/skills/testing.md">
References are relative to /repo/.agents/skills.

# Testing
Run pytest.
</skill>

add parser tests
```

这样模型收到的第一条 user message 就包含完整技能内容。

## 3. 为什么不做一个特殊 skill tool

架构文档强调：

```text
The model-visible skill index uses the existing read tool instead of adding a special skill tool.
```

意思是：

```text
Tau 不给 tau_agent 新增一个 special skill tool
```

原因是保持核心简单。

已有 `read` 工具已经能读取文件。

Skill 本质也是 markdown 文件。

所以自动路径只需要：

```text
system prompt 告诉模型 skill 文件在哪里
模型用 read 工具读取它
```

这样 `tau_agent` 不需要知道 skill 是什么。

## 4. `Skill` 数据结构

`src/tau_coding/skills.py`：

```python
@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    path: Path
    content: str
    description: str | None = None
```

字段含义：

- `name`：技能名，例如 `testing`
- `path`：技能文件路径
- `content`：技能 markdown 内容
- `description`：技能描述，通常从 frontmatter 或标题推导

## 5. `SkillInvocation`

源码：

```python
@dataclass(frozen=True, slots=True)
class SkillInvocation:
    name: str
    location: str
    content: str
    additional_instructions: str | None = None
```

这个类不是加载 skill 用的。

它是 TUI 解析“已经展开后的 skill prompt”用的。

也就是说：

```text
provider-visible message 是完整 skill block
TUI-visible item 可以压缩成 Using skill: xxx
```

## 6. `expand_skill_command()`

源码：

```python
def expand_skill_command(text: str, skills: Sequence[Skill]) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("/skill:"):
        return None

    command, separator, request = stripped.partition(" ")
    name = command.removeprefix("/skill:").strip()
    if not name:
        raise ResourceError("Skill command must include a skill name")

    skill_by_name = {skill.name: skill for skill in skills}
    skill = skill_by_name.get(name)
    if skill is None:
        raise ResourceError(f"Unknown skill: {name}")

    additional_instructions = request.strip() if separator else None
    return format_skill_invocation(skill, additional_instructions)
```

这个函数做几件事：

```text
1. 判断是不是 /skill: 开头
2. 拆出 skill name 和后续 request
3. 检查 skill name 不能为空
4. 在已加载 skills 里找同名 skill
5. 找不到就报 ResourceError
6. 找到就格式化成完整 skill invocation
```

## 7. `partition(" ")`

这里用了：

```python
command, separator, request = stripped.partition(" ")
```

`partition` 是字符串方法。

它会按第一个分隔符拆成三段：

```text
分隔符前面的内容
分隔符本身
分隔符后面的内容
```

例如：

```python
"/skill:testing add tests".partition(" ")
```

得到：

```python
("/skill:testing", " ", "add tests")
```

如果没有空格：

```python
"/skill:testing".partition(" ")
```

得到：

```python
("/skill:testing", "", "")
```

所以代码可以用 `separator` 判断有没有额外 instructions。

## 8. `removeprefix()`

源码：

```python
name = command.removeprefix("/skill:").strip()
```

`removeprefix()` 是字符串方法。

它从开头移除指定前缀。

例如：

```python
"/skill:testing".removeprefix("/skill:")
```

得到：

```text
testing
```

## 9. 为什么 `/skill:` 不由 slash command registry 处理

`commands.py` 里有一段很关键：

```python
if stripped.startswith("/skill:"):
    return CommandResult(handled=False)
```

这表示：

```text
/skill:testing 不是一个会立即结束的 slash command
它是一个 prompt expansion directive
```

也就是说，`/skill:testing add tests` 最终仍然会作为用户 prompt 进入 agent。

只是在进入 agent 前，`CodingSession.expand_prompt_text()` 会把它展开。

## 10. registry 里为什么还有 `skill` command

`create_default_command_registry()` 里注册了：

```python
SlashCommand(
    name="skill",
    usage="/skill:<name> [request]",
    description="Expand a loaded skill into your prompt.",
    handler=_skill_command,
)
```

这个 command 主要用于：

- 命令列表
- autocomplete
- 用户输入 `/skill` 时提示用法

但真正的 `/skill:name` 会被 registry 标记为 unhandled，交给 prompt expansion。

这个设计有点绕，但很合理：

```text
/skill      是帮助型 slash command
/skill:name 是 prompt expansion
```

## 11. `CodingSession.expand_prompt_text()`

源码：

```python
def expand_prompt_text(self, text: str) -> str:
    expanded_prompt = expand_prompt_template_command(text, self._prompt_templates)
    if expanded_prompt is not None:
        return expanded_prompt
    expanded_skill = expand_skill_command(text, self._skills)
    return expanded_skill if expanded_skill is not None else text
```

展开顺序：

```text
1. 先尝试 prompt template
2. 再尝试 skill command
3. 都不是就原样返回
```

这意味着：

```text
/skill:testing add tests
```

会在真正调用 harness 前变成完整 skill block。

## 12. `format_skill_invocation()`

源码：

```python
def format_skill_invocation(skill: Skill, additional_instructions: str | None = None) -> str:
    skill_block = (
        f'<skill name="{skill.name}" location="{skill.path}">\n'
        f"References are relative to {skill.path.parent}.\n\n"
        f"{skill.content.strip()}\n"
        "</skill>"
    )
    if additional_instructions and additional_instructions.strip():
        return f"{skill_block}\n\n{additional_instructions.strip()}"
    return skill_block
```

输出格式包含三类信息：

- skill name
- skill 文件路径
- relative references 应该基于哪个目录解析
- skill markdown 正文
- 用户额外要求

## 13. 为什么要写 `References are relative to ...`

很多 skill 文件会引用相对路径。

例如：

```text
Read references/rules.md
```

如果模型不知道这个路径相对哪里，就容易读错文件。

所以展开时明确告诉模型：

```text
References are relative to /path/to/skill/parent.
```

如果 skill 是：

```text
/repo/.agents/skills/testing.md
```

相对路径基准就是：

```text
/repo/.agents/skills
```

如果 skill 是：

```text
/repo/.agents/skills/testing/SKILL.md
```

相对路径基准就是：

```text
/repo/.agents/skills/testing
```

## 14. `parse_skill_invocation()`

源码：

```python
match = re.match(
    r'^<skill name="([^"]+)" location="([^"]+)">\n([\s\S]*?)\n</skill>(?:\n\n([\s\S]+))?$',
    text,
)
```

这是用正则解析展开后的 skill block。

它提取：

- name
- location
- content
- additional instructions

## 15. `re` 是什么

`re` 是 Python 标准库的正则表达式模块。

正则适合做格式匹配。

这里的格式是 Tau 自己生成的，所以比较可控。

不是任意 HTML/XML parser。

## 16. `[\s\S]*?`

正则里：

```text
[\s\S]*?
```

表示：

```text
匹配任意字符，包括换行，但尽量少匹配
```

因为 skill content 是 markdown，可能有多行。

普通 `.` 默认不匹配换行，所以这里用 `[\s\S]`。

## 17. 自动 skill index：`format_skills_for_prompt()`

`src/tau_coding/system_prompt.py`：

```python
def format_skills_for_prompt(skills: Sequence[Skill]) -> str:
    if not skills:
        return ""

    lines = [
        "\n\nThe following skills provide specialized instructions for specific tasks.",
        "Read the full skill file when the task matches its description.",
        "When a skill file references a relative path, resolve it against the skill directory ...",
        "",
        "<available_skills>",
    ]
    ...
```

如果加载到了 skills，system prompt 会包含一个 skill index。

重要 wording：

```text
Read the full skill file when the task matches its description.
```

也就是说，模型不是只看 description。

如果任务匹配，它应该用 `read` 工具读取完整 skill 文件。

## 18. skill index 为什么只放摘要，不放全文

如果每个 skill 全文都塞进 system prompt，上下文会很快变大。

所以自动路径只放：

```text
name
description
location
```

让模型按需读取。

手动路径 `/skill:name` 才直接把全文展开进当前 prompt。

## 19. TUI 如何压缩显示 skill invocation

`src/tau_coding/tui/state.py`：

```python
skill_invocation = parse_skill_invocation(content)
if skill_invocation is None:
    self.add_item("user", content)
    return
self.add_item("skill", f"Using skill: {skill_invocation.name}")
if skill_invocation.additional_instructions:
    self.add_item("user", skill_invocation.additional_instructions)
```

这说明：

```text
真实 session/provider message 仍然是完整 skill block
TUI 正常聊天视图只显示 Using skill: testing
额外 instructions 作为用户消息显示
```

比如：

```text
/skill:review check the auth flow
```

TUI 显示为：

```text
Using skill: review
check the auth flow
```

而不是显示整篇 skill markdown。

## 20. TUI 如何识别模型读取 skill 文件

`TuiState._read_skill_name()` 会看 tool call：

```text
如果 tool 是 read
且 path 等于某个 loaded skill.path
则显示 Loading skill: <name>
```

这对应自动路径：

```text
模型根据 skill index 选择 read skill 文件
```

TUI 会把普通 read 和 skill read 区分开。

## 21. Autocomplete

`src/tau_coding/tui/autocomplete.py` 里支持：

```text
/skill:
/skill:r
/skill:review fix tests
```

测试验证：

- `/skill:` 会出现在 command completion
- 输入 `/skill:r` 会补全到 `/skill:review`
- 已经输入完整 `/skill:review ` 后，不继续弹 skill name completion
- 补全时保留后面的 request text

这提高了手动调用的可靠性。

## 22. CLI print mode 也支持 skill expansion

测试 `test_run_print_mode_expands_skill_commands` 验证：

```python
await run_print_mode(
    prompt="/skill:testing add tests",
    ...
)
```

provider 收到的 user message 包含：

```text
<skill name="testing" location="...">
References are relative to ...
...
</skill>

add tests
```

所以 skill invocation 不是 TUI 独有能力。

print mode 也能用。

## 23. `ResourceError`

如果用户输入：

```text
/skill:missing
```

`expand_skill_command()` 会抛：

```python
ResourceError(f"Unknown skill: {name}")
```

`ResourceError` 是 Tau resource 层的错误类型。

这比普通 `ValueError` 更表达语义：

```text
这是资源加载/查找问题
```

## 24. 测试如何覆盖这一阶段

### 24.1 `tests/test_skills.py`

覆盖：

- 从目录和单文件加载 skill
- `.agents` skill 加载
- project skill 覆盖 user skill
- duplicate skill diagnostics
- `expand_skill_command()`
- `format_skill_invocation()`
- `parse_skill_invocation()`
- unknown skill 报错

### 24.2 `tests/test_system_prompt.py`

覆盖：

- system prompt 中包含 `<available_skills>`
- skill description/location 被 XML escape
- wording 包含“Read the full skill file...”

### 24.3 `tests/test_coding_session.py`

覆盖：

- session load 时加载 skills
- `/skill:testing add tests` 展开后发送给 provider
- `/skill:testing` 不被 command registry 截断
- agent 能通过 skill index 读取相关 skill 文件

### 24.4 `tests/test_cli.py`

覆盖 print mode 里的 skill expansion。

### 24.5 `tests/test_tui_adapter.py`

覆盖 TUI 把 expanded skill invocation 显示成：

```text
Using skill: review
```

并保留 additional instructions。

### 24.6 `tests/test_tui_autocomplete.py`

覆盖 `/skill:` 的补全体验。

## 25. 小白必须分清的几组概念

### 25.1 skill loading 不是 skill invocation

loading 是把 markdown 文件读成 `Skill` 对象。

invocation 是用户或模型决定使用某个 skill。

### 25.2 `/skill:name` 不是普通 slash command

它是 prompt expansion directive。

`CommandRegistry.execute()` 对它返回：

```python
CommandResult(handled=False)
```

让它继续进入 prompt 流程。

### 25.3 provider 看到全文，TUI 显示摘要

为了模型效果，provider-visible message 必须包含完整 skill 内容。

为了用户体验，TUI 普通视图只显示 compact item。

### 25.4 自动路径和手动路径不同

自动路径：

```text
system prompt skill index -> model read skill file
```

手动路径：

```text
user /skill:name -> Tau expand full skill block
```

### 25.5 `read` 工具复用是架构选择

Tau 没给 agent core 新增 special skill mechanism。

Skill 仍然是 `tau_coding` 的资源概念。

`tau_agent` 只看到普通 message 和普通 tool call。

## 26. 运行测试

Phase 20.3 相关测试：

```bash
uv run pytest tests/test_skills.py tests/test_cli.py tests/test_coding_session.py tests/test_system_prompt.py tests/test_tui_adapter.py tests/test_tui_app.py tests/test_tui_autocomplete.py tests/test_commands.py
```

## 27. 用一句话总结 Phase 20.3

Phase 20.3 的价值是：让 skill 既能被模型通过 system prompt index 自动发现并读取，也能被用户用 `/skill:name` 手动展开成完整、路径明确、可解析的 prompt block，同时让 TUI 用 compact presentation 隐藏大段 markdown 噪音。

## 28. 我的问题与推荐回答

问题：为什么 Tau 手动调用 skill 时要把完整 skill markdown 展开进 user message，而不是只告诉模型“使用 testing skill”？

我的推荐回答：

因为模型不能凭空知道 `testing` skill 的完整规则。只写“使用 testing skill”会依赖模型猜测，可靠性差。Tau 把 `/skill:testing add parser tests` 展开成带 `name`、`location`、相对路径基准和完整 markdown 内容的 `<skill ...>` block，这样 provider-visible message 是自包含的；同时 TUI 再把这个大块解析成“Using skill: testing”，避免普通聊天界面被技能全文淹没。
