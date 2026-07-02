# Phase 17 学习笔记：TUI Slash-command Autocomplete

对应架构文档：`dev-notes/architecture/phase-17-tui-autocomplete.md`

主要源码：

- `src/tau_coding/tui/autocomplete.py`
- `src/tau_coding/tui/app.py`
- `src/tau_coding/tui/widgets.py`
- `tests/test_tui_autocomplete.py`
- `tests/test_tui_app.py`

前置阶段：

- Phase 9：skills 和 prompt templates 已经能被加载
- Phase 12：Textual TUI 已经有 prompt 输入框
- Phase 15：slash command registry 提供命令元数据
- Phase 16：资源发现更稳健，TUI 可以拿到当前 skills/templates
- Phase 17：TUI 输入框开始基于这些元数据做 autocomplete

## 1. 这一阶段到底在做什么

Phase 17 给 Tau 的 Textual TUI 增加 prompt autocomplete。

也就是用户在输入框里输入：

```text
/
```

TUI 会显示可用命令。

输入：

```text
/ski
```

可以补全成：

```text
/skill:
```

输入：

```text
/skill:r fix tests
```

如果有一个 skill 叫 `review`，可以补全成：

```text
/skill:review fix tests
```

Phase 17 的重点不是“界面上多了一个提示条”。

真正重点是：

```text
补全匹配和替换逻辑被做成纯 Python 模型，可以不启动 Textual 直接测试。
```

这个模型在：

```text
src/tau_coding/tui/autocomplete.py
```

## 2. 当前源码比 Phase 17 文档更丰富

架构文档主要描述：

- slash command completion
- `/skill:<name>` completion
- Tab/Up/Down 操作

当前源码已经继续扩展出了更多补全：

- custom prompt template completion，例如 `/example`
- `/model` 参数补全
- `/login`、`/logout` provider 参数补全
- `/resume` session id 参数补全
- `/theme` theme 参数补全
- 普通 prompt 里的 `@file` 文件引用补全
- `!`、`!!` shell command 的路径补全

但是它们都复用同一个核心模型：

```python
CompletionItem
CompletionState
build_completion_state(...)
```

所以 Phase 17 的学习重点仍然是这三个对象。

## 3. 为什么 autocomplete 仍然属于 tau_coding

补全依赖很多应用层概念：

- CommandRegistry
- SlashCommand
- Skill
- PromptTemplate
- model names
- provider names
- session ids
- TUI themes
- cwd 下的文件路径

这些都不是 `tau_agent` 的职责。

`tau_agent` 只负责 agent harness、messages、tools、events、sessions。

所以补全逻辑放在：

```text
src/tau_coding/tui/autocomplete.py
```

注意，虽然路径里有 `tui`，但这个文件本身没有强依赖 Textual。

它只是纯数据和纯函数。

真正的 Textual 集成在：

```text
src/tau_coding/tui/app.py
src/tau_coding/tui/widgets.py
```

## 4. autocomplete.py 的 import

文件开头：

```python
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
```

这些在前面阶段已经见过。

### 4.1 Sequence

`Sequence[T]` 表示一组有顺序的 T。

这里常见写法：

```python
skills: Sequence[Skill]
prompt_templates: Sequence[PromptTemplate]
```

它不强制必须是 list。

tuple 也可以。

这让函数调用更灵活。

### 4.2 dataclass

补全里的几个对象都只是保存数据，所以使用：

```python
@dataclass(frozen=True, slots=True)
```

它们更像“不可随便修改的数据记录”。

### 4.3 pathlib.Path

补全支持文件路径，所以要用：

```python
Path
```

例如：

```python
cwd: Path | None = None
```

## 5. 忽略目录列表

源码：

```python
IGNORED_FILE_COMPLETION_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tau",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)
```

这是文件补全时要忽略的目录。

例如：

- `.git`
- `node_modules`
- `.venv`
- `__pycache__`

这些目录通常很大，或者不适合让用户在 prompt 里引用。

这里用的是：

```python
frozenset(...)
```

`set` 是集合。

`frozenset` 是不可变集合。

因为这个忽略列表是常量，不应该运行中修改，所以用 frozenset 很合适。

## 6. MAX_FILE_COMPLETIONS

源码：

```python
MAX_FILE_COMPLETIONS = 50
```

这表示文件补全最多返回 50 条。

为什么需要限制？

因为项目文件可能非常多。

如果一次返回几千条：

- UI 会卡
- 用户也看不过来
- 测试和渲染都变重

所以补全系统做了上限。

## 7. CompletionOption：参数补全选项

源码：

```python
@dataclass(frozen=True, slots=True)
class CompletionOption:
    """A possible argument completion value with optional picker metadata."""

    value: str
    description: str | None = None
```

它表示一个“可以补全的值”。

比如 `/resume` 的 session 选项：

```python
CompletionOption(
    value="session-2",
    description="Newer - qwen - /repo",
)
```

这里：

```text
value        真正插入输入框的值
description 右侧显示给用户看的说明
```

测试里有：

```python
assert [item.display for item in state.items] == ["session-2", "session-1"]
assert [item.description for item in state.items] == [
    "Newer - qwen - /repo",
    "Older - gpt - /repo",
]
```

## 8. CompletionItem：一个可选补全项

源码：

```python
@dataclass(frozen=True, slots=True)
class CompletionItem:
    """One selectable prompt completion."""

    display: str
    replacement: str
    start: int
    end: int
    description: str | None = None
    category: str | None = None
```

这是补全系统最重要的数据结构。

字段解释：

```text
display      UI 上显示什么
replacement 选中后真正替换成什么
start        替换输入文本的起始位置
end          替换输入文本的结束位置
description 说明文字
category    分组，例如 Commands、Custom prompts
```

为什么同时需要 display 和 replacement？

因为显示和插入不一定永远相同。

例如 `/skill` 命令在补全里显示：

```text
/skill:
```

插入也是：

```text
/skill:
```

但搜索词补全时，用户输入：

```text
/cl
```

匹配到了 `/new` 的 search term `clear`。

UI 显示和插入都应该是 canonical command：

```text
/new
```

而不是 `/clear`。

## 9. CompletionItem.apply()

源码：

```python
def apply(self, text: str) -> str:
    """Apply this completion to input text."""
    return f"{text[: self.start]}{self.replacement}{text[self.end :]}"
```

这行很短，但非常关键。

它做的是字符串切片替换。

假设：

```python
text = "/skill:r fix tests"
start = 0
end = 8
replacement = "/skill:review"
```

那么：

```python
text[:start]
```

是：

```text
""
```

```python
text[end:]
```

是：

```text
" fix tests"
```

拼起来：

```text
/skill:review fix tests
```

这就是为什么补全 skill 名时可以保留后面的 request text。

测试验证：

```python
assert state.selected.apply("/skill:r fix tests") == "/skill:review fix tests"
```

## 10. CompletionState：当前补全状态

源码：

```python
@dataclass(frozen=True, slots=True)
class CompletionState:
    """Current autocomplete state for the prompt input."""

    items: tuple[CompletionItem, ...] = ()
    selected_index: int = 0
```

它保存：

```text
items          当前可选补全项
selected_index 当前选中第几个
```

例如：

```text
items = ["/resume", "/new"]
selected_index = 0
```

表示当前选中 `/resume`。

## 11. selected 属性

源码：

```python
@property
def selected(self) -> CompletionItem | None:
    """Return the currently selected completion item."""
    if not self.items:
        return None
    return self.items[self.selected_index]
```

如果没有补全项，返回 `None`。

如果有，就返回当前选中的 item。

这让调用方可以写：

```python
item = self._completion_state.selected
if item is None:
    return None
return item.apply(value)
```

## 12. select_next() 和 select_previous()

源码：

```python
def select_next(self) -> CompletionState:
    """Return a state with the next item selected."""
    if not self.items:
        return self
    return CompletionState(
        items=self.items,
        selected_index=(self.selected_index + 1) % len(self.items),
    )
```

它不会修改当前对象，而是返回一个新的 `CompletionState`。

这和 `frozen=True` 一致。

这里用了取模 `%`：

```python
(self.selected_index + 1) % len(self.items)
```

如果当前是最后一个，再按 Down，会回到第一个。

这叫 wrapping。

测试验证：

```python
assert state.select_previous().selected_index == len(state.items) - 1
assert state.select_next().selected_index == 1
```

`select_previous()` 同理：

```python
(self.selected_index - 1) % len(self.items)
```

如果当前是第一个，上一项就是最后一个。

## 13. build_completion_state()：补全入口

核心函数：

```python
def build_completion_state(
    text: str,
    *,
    command_registry: CommandRegistry,
    skills: Sequence[Skill],
    prompt_templates: Sequence[PromptTemplate],
    model_names: Sequence[str] = (),
    provider_names: Sequence[str] = (),
    thinking_levels: Sequence[str] = (),
    theme_names: Sequence[str] = (),
    session_ids: Sequence[str] = (),
    session_options: Sequence[CompletionOption] = (),
    cwd: Path | None = None,
) -> CompletionState:
```

它的输入是当前 prompt 文本和各种可用元数据。

它的输出是：

```python
CompletionState
```

也就是：

```text
当前应该显示哪些补全项，选中哪一项
```

注意参数里的 `*`。

```python
def build_completion_state(text: str, *, command_registry: CommandRegistry, ...)
```

`*` 后面的参数必须用名字传。

所以调用时要写：

```python
build_completion_state(
    "/",
    command_registry=registry,
    skills=(),
    prompt_templates=(),
)
```

这样更清晰，也避免参数太多时传错位置。

## 14. 普通文本时的补全逻辑

源码开头：

```python
if not text.startswith("/") or text.startswith("//"):
    if cwd is not None:
        shell_completions = _shell_path_completions(text=text, cwd=cwd)
        if shell_completions is not None:
            return CompletionState(shell_completions)
        return CompletionState(_file_reference_completions(text=text, cwd=cwd))
    return CompletionState()
```

如果文本不是 slash command：

- 可以尝试 shell path completion
- 可以尝试 `@file` reference completion
- 如果没有 cwd，就没有文件补全

`text.startswith("//")` 表示：

```text
如果用户输入 //，不要当 slash command
```

这可能是用户想输入普通文本或特殊内容。

## 15. slash command 的 token

源码：

```python
token_end = _first_token_end(text)
token = text[:token_end]
has_argument_text = token_end < len(text)
```

`_first_token_end()`：

```python
def _first_token_end(text: str) -> int:
    separator = text.find(" ")
    return len(text) if separator == -1 else separator
```

它找到第一个空格的位置。

例如：

```text
/model fak
```

第一个 token 是：

```text
/model
```

`token_end` 是 `/model` 的结束位置。

`has_argument_text` 表示后面是否还有参数文本。

## 16. /skill: 的补全逻辑

源码：

```python
if token.startswith("/skill:"):
    if has_argument_text and _matches_skill_command(token, skills):
        return CompletionState()
    return CompletionState(_skill_completions(token=token, token_end=token_end, skills=skills))
```

分两种情况。

### 16.1 skill 已经完整，且后面有 request

例如：

```text
/skill:review fix tests
```

`token` 是：

```text
/skill:review
```

如果 `review` 是已存在 skill，且后面有 request，就不再显示补全。

因为用户已经选好了 skill，正在写请求。

### 16.2 skill 名还没写完

例如：

```text
/skill:r fix tests
```

此时调用：

```python
_skill_completions(...)
```

生成 `/skill:review`。

替换范围是：

```text
start=0
end=token_end
```

也就是只替换 `/skill:r`，保留后面的 ` fix tests`。

## 17. _skill_completions()

源码：

```python
def _skill_completions(
    *, token: str, token_end: int, skills: Sequence[Skill]
) -> tuple[CompletionItem, ...]:
    prefix = token.removeprefix("/skill:").lower()
    suggestions = [
        CompletionItem(
            display=f"/skill:{skill.name}",
            replacement=f"/skill:{skill.name}",
            start=0,
            end=token_end,
            description=skill.description,
        )
        for skill in sorted(skills, key=lambda item: item.name)
        if skill.name.lower().startswith(prefix)
    ]
    return tuple(suggestions)
```

这里有一个 list comprehension。

逻辑是：

1. 去掉 `/skill:`，得到用户输入的 skill 前缀。
2. 按 skill name 排序。
3. 只保留名字以 prefix 开头的 skills。
4. 为每个 skill 创建 `CompletionItem`。

例如：

```text
prefix = "r"
skills = ["review", "testing"]
```

只返回：

```text
/skill:review
```

## 18. 含冒号的普通 slash token 会关闭补全

源码：

```python
if ":" in token:
    return CompletionState()
```

除了 `/skill:` 以外，其他带冒号的 slash token 不补全。

这是防御性规则。

例如：

```text
/unknown:abc
```

系统不应该乱猜。

## 19. 命令参数补全优先

源码：

```python
argument_completions = _command_argument_completions(...)
if argument_completions is not None:
    return CompletionState(argument_completions)
```

这一步发生在普通命令名补全之前。

为什么？

因为用户输入：

```text
/model fak
```

此时命令名 `/model` 已经完整。

系统应该补全 model 参数：

```text
fake-model
```

而不是继续补全命令名。

测试名字也说明了这个优先级：

```python
test_builtin_command_argument_completion_wins_over_completed_command_hide
```

## 20. _command_argument_completions()

源码支持几类参数补全：

```python
if command_name in {"model", "scoped-models"}:
    ...
if command_name in {"login", "logout"}:
    ...
if command_name == "resume":
    ...
if command_name == "theme":
    ...
```

分别是：

```text
/model         补全 model_names
/scoped-models 补全 model_names
/login         补全 provider_names
/logout        补全 provider_names
/resume        补全 session ids/options
/theme         补全 theme_names
```

注意测试里：

```python
test_thinking_argument_completion_uses_available_modes
```

当前源码没有给 `/thinking` 做参数补全，因为 `/thinking` 当前也不是默认注册命令。

所以测试期望：

```python
assert state.items == ()
```

## 21. _value_completions()

源码：

```python
def _value_completions(
    *,
    text: str,
    start: int,
    options: Sequence[CompletionOption],
    sort: bool,
) -> tuple[CompletionItem, ...]:
    end = _argument_token_end(text, start)
    prefix = text[start:end].lower()
    ordered_options = sorted(options, key=lambda item: item.value) if sort else options
    return tuple(
        CompletionItem(
            display=option.value,
            replacement=option.value,
            start=start,
            end=end,
            description=option.description,
        )
        for option in ordered_options
        if option.value.lower().startswith(prefix)
    )
```

这个函数是“值补全”的通用工具。

例如：

```text
/theme tau-
```

`start` 是参数开始位置。

`prefix` 是：

```text
tau-
```

可选值：

```python
("tau-dark", "tau-light", "high-contrast")
```

匹配结果：

```text
tau-dark
tau-light
```

选中后只替换参数部分，不替换 `/theme `。

## 22. 命令名补全

如果不是 `/skill:`，也不是参数补全，就进入：

```python
return CompletionState(
    _command_completions(
        token=token,
        token_end=token_end,
        registry=command_registry,
        prompt_templates=prompt_templates,
    )
)
```

命令名补全来自两个来源：

1. `CommandRegistry` 里的 registered commands
2. 已加载的 prompt templates

所以输入：

```text
/
```

会同时看到：

- Commands
- Custom prompts

## 23. _command_completions()

源码：

```python
prefix = token.removeprefix("/").lower()
command_suggestions: list[CompletionItem] = []
for command in registry.list_commands():
    command_suggestions.extend(
        _command_alias_completions(command, prefix=prefix, token_end=token_end)
    )
```

这部分从 registry 取所有命令。

对每个 command，调用 `_command_alias_completions()`。

然后 prompt templates：

```python
prompt_suggestions = [
    CompletionItem(
        display=f"/{template.name}",
        replacement=f"/{template.name}",
        start=0,
        end=token_end,
        description=template.description or "Prompt template",
        category="Custom prompts",
    )
    for template in prompt_templates
    if template.name.lower().startswith(prefix)
]
```

也就是说 `.agents/prompts/example.md` 可以变成：

```text
/example
```

## 24. search_terms：搜索词不是命令

Phase 15 里我们讲过：

```python
SlashCommand(
    name="new",
    search_terms=("clear", "reset"),
)
```

在补全里，用户输入：

```text
/cl
```

可以匹配到 `clear` 这个 search term。

但插入结果必须是：

```text
/new
```

源码：

```python
replacement_name = name if name in (command.name, *command.aliases) else command.name
```

如果匹配的是真实命令名或 alias，就用那个名字。

如果匹配的是 search term，就回到 canonical command name。

所以 `/cl` 选中后变成：

```text
/new
```

测试验证：

```python
assert clear_state.selected.apply("/cl") == "/new"
```

## 25. 直接匹配优先于搜索词匹配

如果用户输入：

```text
/res
```

它可以直接匹配：

```text
/resume
```

也可能通过 `/new` 的 search term `reset` 匹配：

```text
/new
```

系统应该优先显示 `/resume`。

排序函数：

```python
def _command_completion_sort_key(item: CompletionItem, prefix: str) -> tuple[int, str]:
    if not prefix:
        return (0, item.display)
    display_name = item.display.removeprefix("/").removesuffix(":").lower()
    direct_match_rank = 0 if display_name.startswith(prefix) else 1
    return (direct_match_rank, item.display)
```

返回值是 tuple。

Python 排序 tuple 时，会先比第一个元素，再比第二个元素。

所以：

```text
direct_match_rank = 0
```

会排在：

```text
direct_match_rank = 1
```

前面。

测试验证：

```python
assert [item.display for item in state.items[:2]] == ["/resume", "/new"]
```

## 26. custom prompt 补全

当前源码已经支持 prompt template 作为 slash command 补全。

例如有：

```python
PromptTemplate(
    name="example",
    path=Path("example.md"),
    content="Example prompt.",
    description="Run example.",
)
```

输入：

```text
/exa
```

补全：

```text
/example
```

测试：

```python
assert [item.display for item in state.items] == ["/example"]
```

如果用户已经输入：

```text
/example fix tests
```

补全会隐藏。

因为这时用户已经在写 template 参数了。

## 27. @file 引用补全

普通 prompt 不以 `/` 开头时，如果有 cwd，会尝试：

```python
_file_reference_completions(text=text, cwd=cwd)
```

例如：

```text
please read @app
```

如果项目里有：

```text
src/app.py
```

补全结果：

```text
@src/app.py
```

测试：

```python
assert state.selected.apply("please read @app") == "please read @src/app.py"
```

### 27.1 _active_file_reference_token()

源码：

```python
cursor = len(text)
token_start = max(text.rfind(" ", 0, cursor), text.rfind("\n", 0, cursor)) + 1
at_index = text.rfind("@", token_start, cursor)
if at_index == -1:
    return None
return at_index, cursor
```

它找当前光标前最后一个 token 里的 `@`。

如果没有 `@`，就不做文件引用补全。

当前实现默认光标在文本末尾。

### 27.2 _iter_file_reference_paths()

它从 cwd 开始遍历文件：

```python
stack = [cwd]
while stack:
    directory = stack.pop()
    ...
```

这是一个栈式遍历。

遇到目录就加入 stack。

遇到忽略目录就跳过。

## 28. ! shell 路径补全

Tau 支持终端命令：

```text
!cat READ
!!cat READ
```

补全可以把 `READ` 补成：

```text
README.md
```

源码先判断前缀：

```python
def _shell_command_prefix_span(text: str) -> tuple[int, int] | None:
    leading_whitespace = len(text) - len(text.lstrip())
    stripped = text[leading_whitespace:]
    if stripped.startswith("!!"):
        return (leading_whitespace, leading_whitespace + 2)
    if stripped.startswith("!"):
        return (leading_whitespace, leading_whitespace + 1)
    return None
```

`!` 和 `!!` 都支持。

测试：

```python
assert state.selected.apply("!cat READ") == "!cat README.md"
assert state.selected.apply("!!cat READ") == "!!cat README.md"
```

## 29. shell 路径为什么做安全限制

`_parse_shell_path_token()` 会拒绝一些复杂情况：

```python
if path_text.startswith(("/", "~")):
    return None
if any(char in path_text for char in "\"'`$*?[{"):
    return None
```

也就是说它不补全：

- 绝对路径
- home 路径
- 带引号
- 带 shell 展开符
- 带 glob 字符

这是为了保持补全逻辑简单可靠。

shell 语法很复杂，如果补全器假装自己能正确理解所有 shell 语法，很容易出 bug。

当前实现只处理简单相对路径。

## 30. Textual PromptInput 如何接入按键

`src/tau_coding/tui/app.py` 里有：

```python
class PromptInput(TextArea):
    """Multiline prompt input with completion key bindings."""
```

它继承 Textual 的 `TextArea`。

也就是说输入框不是简单一行 input，而是多行文本区域。

它有几个动作：

```python
def action_accept_completion(self) -> None:
    self._completion_target().action_accept_completion()

def action_completion_next(self) -> None:
    if self._has_completion_options():
        self._completion_target().action_completion_next()
    else:
        self.action_cursor_down()

def action_completion_previous(self) -> None:
    if self._has_completion_options():
        self._completion_target().action_completion_previous()
    ...
```

这里的设计是：

```text
如果有补全项，上下键切换补全；
如果没有补全项，上下键就是普通光标移动。
```

这让输入框行为比较自然。

## 31. on_key() 如何拦截按键

`PromptInput.on_key()` 里：

```python
elif event.key == keybindings.accept_completion:
    event.stop()
    self._completion_target().action_accept_completion()
```

默认 `accept_completion` 是：

```text
tab
```

所以按 Tab 会接受当前补全。

Down/Up：

```python
elif event.key == keybindings.completion_next:
    event.stop()
    if self._has_completion_options():
        self._completion_target().action_completion_next()
    else:
        self.action_cursor_down()
```

这就是补全选择上下移动的入口。

## 32. TUI 什么时候刷新补全

当输入框文本变化时：

```python
def on_text_area_changed(self, event: TextArea.Changed) -> None:
    """Update prompt autocomplete when the prompt text changes."""
    if event.text_area.id != "prompt":
        return
    self._sync_prompt_shell_mode(event.text_area.text)
    self._completion_state = self._build_completion_state(event.text_area.text)
    self._refresh_completions()
```

流程：

1. 确认变化来自 prompt 输入框。
2. 同步 shell mode 样式。
3. 根据当前文本重新 build completion state。
4. 刷新补全显示。

这里说明补全状态不是长期缓存的。

每次文本变化都重新计算。

## 33. TUI 如何构建 CompletionState

`TauTuiApp._build_completion_state()`：

```python
def _build_completion_state(self, text: str) -> CompletionState:
    registry = _session_command_registry(self.session)
    return build_completion_state(
        text,
        command_registry=registry,
        skills=self.session.skills,
        prompt_templates=self.session.prompt_templates,
        model_names=self.session.available_models,
        provider_names=self.session.available_providers,
        thinking_levels=getattr(self.session, "available_thinking_levels", ()),
        theme_names=BUILTIN_TUI_THEME_NAMES,
        session_options=_session_options(self.session),
        cwd=self.session.cwd,
    )
```

这就是把 session 当前状态喂给纯补全函数。

可以看到补全来源包括：

- command registry
- skills
- prompt templates
- available models
- providers
- themes
- session options
- cwd

所以补全结果会随当前 session 状态变化。

## 34. TUI 如何应用选中的补全

核心函数：

```python
def _apply_selected_completion(self, value: str) -> str | None:
    item = self._completion_state.selected
    if item is None:
        return None
    return item.apply(value)
```

它不自己拼字符串。

它委托给：

```python
CompletionItem.apply()
```

这样替换逻辑只有一份。

## 35. Enter 也会先接受补全

提交 prompt 时：

```python
applied_completion = self._apply_selected_completion(raw_text)
if applied_completion is not None and applied_completion != raw_text:
    prompt.text = applied_completion
    prompt.move_cursor(_text_end_location(applied_completion))
    self._completion_state = self._build_completion_state(applied_completion)
    self._refresh_completions()
    return
```

这意味着如果当前有补全项，按 Enter 会先接受补全，而不是直接提交。

测试里有：

```text
test_tui_app_enter_accepts_completion_without_submitting
```

这是一种常见交互：

```text
先完成输入，再提交输入。
```

## 36. _refresh_completions()

源码：

```python
def _refresh_completions(self) -> None:
    suggestions = self.query_one("#autocomplete", Static)
    suggestions.display = bool(self._completion_state.items)
    suggestions.update(
        render_completion_suggestions(
            _visible_completion_state(...),
            theme=self.tui_settings.resolved_theme,
        )
    )
    self._refresh_footer_bindings()
```

它做三件事：

1. 找到 id 为 `autocomplete` 的 Static widget。
2. 如果有补全项就显示，没有就隐藏。
3. 用 `render_completion_suggestions()` 渲染补全列表。
4. 更新 footer 里的按键提示。

## 37. render_completion_suggestions()

位置：

```text
src/tau_coding/tui/widgets.py
```

源码：

```python
def render_completion_suggestions(
    state: CompletionState,
    *,
    theme: TuiTheme = TAU_DARK_THEME,
) -> RenderableType:
```

它使用 Rich 的 `Table.grid()` 渲染：

```python
table = Table.grid(expand=True)
table.add_column(no_wrap=True)
table.add_column(ratio=1)
```

第一列显示命令或补全值。

第二列显示 description。

如果 item 有 category，会先输出分组标题：

```python
if item.category != previous_category:
    ...
    if item.category:
        table.add_row(Text(item.category, style=theme.completion_description), Text(""))
```

被选中的项前面有：

```text
›
```

测试里检查：

```python
assert "› /skill:review" in rendered
```

## 38. 补全列表为什么要限制可见窗口

TUI 里有：

```python
_visible_completion_state(...)
```

它会确保：

```text
当前选中的补全项在可见区域内
```

如果补全项很多，不可能全部展开，否则会挤掉输入框和 transcript。

所以 UI 只展示一个窗口。

随着用户按 Down/Up，窗口滚动，选中项保持可见。

测试包括：

```text
test_visible_completion_state_keeps_selected_item_in_render_window
test_visible_completion_state_accounts_for_wrapped_descriptions
test_tui_app_scrolls_completion_selection_into_view
```

## 39. 为什么 autocomplete.py 可以独立测试

`tests/test_tui_autocomplete.py` 大量测试都只调用：

```python
build_completion_state(...)
```

例如：

```python
state = build_completion_state(
    "/se",
    command_registry=create_default_command_registry(),
    skills=(),
    prompt_templates=(),
)

assert [item.display for item in state.items] == ["/session"]
assert state.selected.apply("/se") == "/session"
```

这里没有启动 Textual。

没有 TUI event loop。

没有真实终端。

这就是纯模型的好处：

```text
匹配规则和替换规则可以快速、稳定地单元测试。
```

Textual 层只需要测试：

- 按键是否调用对应 action
- UI 是否显示补全条
- 接受补全是否写回 prompt text

## 40. Phase 17 的测试重点

主要测试文件：

```text
tests/test_tui_autocomplete.py
tests/test_tui_app.py
```

覆盖内容包括：

- `/` 能列出所有注册命令
- 命令和 custom prompts 可以分组显示
- search terms 能匹配 canonical command
- 直接匹配优先于 search-term 匹配
- `/skill:` 可以补全 skill 名
- skill 补全保留后面的 request text
- 完整命令后有参数时隐藏命令名补全
- `/model`、`/login`、`/resume`、`/theme` 参数补全
- `@file` 文件引用补全
- `!` 和 `!!` shell path 补全
- selection wrapping
- TUI 里 Tab/Enter/Up/Down 的行为
- 补全渲染的描述换行对齐

## 41. 和前面阶段的连接

### 41.1 连接 Phase 15

Phase 15 的 `CommandRegistry` 提供：

```python
registry.list_commands()
```

Phase 17 直接读这个注册表生成命令补全。

这样命令列表不需要在 TUI 里手写第二份。

### 41.2 连接 Phase 9

Phase 9 的 `Skill` 和 `PromptTemplate` 成为补全来源。

TUI 可以根据当前加载资源建议：

```text
/skill:review
/example
```

### 41.3 连接 Phase 14

`/resume` 的参数补全来自 session options。

这依赖 Phase 14 的 session manager/index。

### 41.4 连接 Phase 12

Phase 12 建立了 Textual TUI。

Phase 17 在它的 prompt input 上增加补全行为。

## 42. Python 小白应该掌握的语法点

### 42.1 字符串切片

```python
text[: self.start]
text[self.end :]
```

这是 Python 字符串切片。

它常用于替换一段文本。

### 42.2 startswith()

```python
text.startswith("/")
```

判断字符串是否以某个前缀开头。

### 42.3 removeprefix()

```python
token.removeprefix("/skill:")
```

如果 token 以 `/skill:` 开头，就去掉它。

### 42.4 rfind()

```python
text.rfind("@", token_start, cursor)
```

从右往左找某个字符。

文件引用补全用它找当前 token 里的最后一个 `@`。

### 42.5 modulo %

```python
(self.selected_index + 1) % len(self.items)
```

取模可以做循环选择。

最后一项再往下，回到第一项。

### 42.6 tuple 排序 key

```python
return (direct_match_rank, item.display)
```

Python 排序 tuple 时按顺序比较。

这适合表达多级排序规则。

## 43. 你读源码时的推荐顺序

建议这样读：

1. `CompletionItem`
2. `CompletionItem.apply()`
3. `CompletionState`
4. `build_completion_state()`
5. `_skill_completions()`
6. `_command_completions()`
7. `_command_argument_completions()`
8. `_file_reference_completions()`
9. `_shell_path_completions()`
10. `PromptInput` 的按键处理
11. `TauTuiApp._build_completion_state()`
12. `TauTuiApp._refresh_completions()`
13. `render_completion_suggestions()`

这样读会先掌握纯逻辑，再看 UI 接线。

## 44. Phase 17 用一句话总结

Phase 17 的价值是：为 Tau TUI 引入一个可独立测试的 prompt autocomplete 模型，用 `CompletionItem` 描述“显示什么、替换哪里、替换成什么”，用 `CompletionState` 描述“有哪些选项、当前选中哪个”，再让 Textual 层只负责按键、渲染和应用补全，从而把命令、skills、prompt templates、session/model/theme 参数和文件路径补全统一到同一套机制里。

## 45. 我的问题与推荐回答

问题：为什么 Tau 不直接在 Textual 的 `PromptInput` 里写一堆 if/else 来做补全，而要单独做 `build_completion_state()`、`CompletionItem` 和 `CompletionState`？

我的推荐回答：

因为补全本质上分成两件事：一是“根据当前文本和 session 元数据算出可选项”，二是“在 TUI 里显示并响应按键”。`build_completion_state()` 把第一件事做成纯函数，不依赖 Textual，所以可以用普通单元测试快速验证命令匹配、skill 补全、参数补全和字符串替换。`PromptInput` 和 `TauTuiApp` 只负责第二件事，比如 Tab 接受、Up/Down 切换、渲染补全条。这样逻辑更清楚，测试也更稳定。
