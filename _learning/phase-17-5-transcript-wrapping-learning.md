# Phase 17.5 学习笔记：TUI Transcript Wrapping

对应架构文档：`dev-notes/architecture/phase-17-5-transcript-wrapping.md`

主要源码：

- `src/tau_coding/tui/state.py`
- `src/tau_coding/tui/widgets.py`
- `src/tau_coding/tui/app.py`
- `tests/test_tui_app.py`

前置阶段：

- Phase 11：print-mode renderer 已经能把 agent events 渲染到终端
- Phase 12：Textual TUI 已经能显示 transcript
- Phase 17：TUI 输入框已经有 autocomplete
- Phase 17.5：TUI transcript 从“带前缀的文本行”升级成“可换行的独立消息块”

## 1. 这一阶段到底在做什么

Phase 17.5 处理的是 TUI transcript 的显示质量。

transcript 就是 TUI 中显示对话历史的区域。

早期很容易写成：

```text
you: Read the file
assistant: Done.
tool: read README.md
```

这种方式简单，但问题很多：

- 长文本容易撑宽终端
- 复制选择可能横跨一大块 transcript
- role 前缀占空间
- 不像真正的 chat stack
- UI 很难按 message 单独控制样式

Phase 17.5 的目标是：

```text
每条消息是一个独立 block；
role 用颜色和左侧 accent 表达；
正文根据终端宽度自动换行；
选择文本按 message widget 管理。
```

一句话：

Phase 17.5 把 transcript 从“拼起来的一整段文本”变成“由多个可独立渲染、可独立选择的消息 widget 组成的滚动视图”。

## 2. 三层边界

架构文档强调这个边界：

```text
CodingSession emits events
TuiEventAdapter builds display state
TranscriptView renders blocks
```

也就是说：

```text
CodingSession      不知道 Textual 怎么显示
TuiEventAdapter    把 agent event 转成 TuiState
TranscriptView     把 TuiState 渲染成 UI widgets
```

这样 `tau_agent` 和 `tau_coding/session.py` 都不需要关心终端宽度、颜色、选择文本。

## 3. ChatItem：显示状态仍然简单

位置：

```text
src/tau_coding/tui/state.py
```

源码：

```python
@dataclass(slots=True)
class ChatItem:
    """One rendered item in the TUI transcript."""

    role: ChatItemRole
    text: str
    tool_call_id: str | None = None
    tool_result_text: str | None = None
    always_show_tool_result: bool = False
```

`ChatItem` 只是显示状态，不是 UI widget。

字段解释：

```text
role                    这条消息是什么角色
text                    当前可见文本
tool_call_id            如果和工具调用有关，记录 tool call id
tool_result_text        工具结果详情
always_show_tool_result 是否永远显示工具结果
```

注意它没有：

- color
- width
- padding
- Textual widget
- Rich renderable

这些都属于渲染层。

## 4. ChatItemRole

源码：

```python
ChatItemRole = Literal[
    "user",
    "assistant",
    "tool",
    "error",
    "status",
    "thinking",
    "skill",
    "branch_summary",
    "compaction_summary",
]
```

这里用的是 `Literal`。

`Literal["user", "assistant"]` 表示：

```text
这个字段只能是这些固定字符串之一。
```

这比普通 `str` 更精确。

例如 `role="foobar"` 就不是合法角色。

对 Python 小白来说，你可以简单理解：

```text
Literal 是类型标注层面的枚举约束。
```

## 5. TuiState：可变的显示状态

源码：

```python
@dataclass(slots=True)
class TuiState:
    """Mutable display state for the interactive TUI."""

    items: list[ChatItem] = field(default_factory=list)
    assistant_buffer: str = ""
    running: bool = False
    error: str | None = None
    show_tool_results: bool = False
    show_thinking: bool = False
    ...
```

`TuiState` 是 TUI 的显示状态。

注意它是 mutable。

也就是它会随着事件到来而改变。

例如：

```python
self.items.append(...)
```

会添加新的 transcript item。

### 5.1 field(default_factory=list)

这里非常重要：

```python
items: list[ChatItem] = field(default_factory=list)
```

不能写成：

```python
items: list[ChatItem] = []
```

因为默认 list 是可变对象，多个实例可能共享同一个 list。

`default_factory=list` 表示每次创建 `TuiState` 时都新建一个 list。

## 6. add_item()

源码：

```python
def add_item(
    self,
    role: ChatItemRole,
    text: str,
    *,
    tool_call_id: str | None = None,
    tool_result_text: str | None = None,
    always_show_tool_result: bool = False,
) -> None:
    """Append a transcript item."""
    self.items.append(
        ChatItem(
            role=role,
            text=text,
            tool_call_id=tool_call_id,
            tool_result_text=tool_result_text,
            always_show_tool_result=always_show_tool_result,
        )
    )
```

这就是把一条消息加入 transcript display state。

它仍然不渲染。

只是创建一个 `ChatItem` 放进 `items`。

渲染交给 `TranscriptView`。

## 7. TranscriptView：滚动容器

位置：

```text
src/tau_coding/tui/widgets.py
```

源码：

```python
class TranscriptView(VerticalScroll):
    """Scrollable transcript view backed by individual selectable message widgets."""
```

它继承 Textual 的：

```python
VerticalScroll
```

也就是说 transcript 是一个垂直滚动容器。

这个容器里不是一整段字符串，而是多个子 widget：

```text
TranscriptMessageWidget
StreamingTranscriptMessageWidget
TranscriptMessageWidget
...
```

## 8. min_width = 1

`TranscriptView.__init__()`：

```python
min_width = kwargs.pop("min_width", None)
super().__init__(*args, **kwargs)
self.min_width = min_width
if min_width is not None:
    self.styles.min_width = min_width
```

架构文档里强调：

```python
min_width = 1
```

测试里确认：

```python
assert transcript.min_width == 1
```

为什么重要？

如果 transcript 的最小宽度被长文本撑大，终端变窄时会出现水平滚动。

Phase 17.5 希望长文本在 block 内折行，而不是把整个 transcript 撑宽。

所以 transcript 容器要允许自己变窄。

## 9. TranscriptMessageWidget：单条消息 widget

源码：

```python
class TranscriptMessageWidget(Horizontal):
    """One selectable transcript message with a non-selectable visual gutter."""
```

它继承 `Horizontal`。

也就是说一条消息横向分成两部分：

```text
左侧 gutter/accent
右侧 message body
```

在 `compose()` 里：

```python
gutter = NonSelectableStatic("▌", classes="transcript-message-gutter")
gutter.styles.color = self._role_style.border
body = self._body_widget()
yield gutter
yield body
```

左侧的：

```text
▌
```

就是 role accent。

测试验证：

```python
assert "▌ Read the file" in output
```

## 10. 为什么不用 you:/assistant: 前缀

测试：

```python
assert "you:" not in output
assert "assistant:" not in output
assert "tool:" not in output
```

Phase 17.5 用颜色和左侧 accent 表达角色。

这样文本主体更干净。

例如：

```text
▌ Read the file
```

而不是：

```text
you: Read the file
```

这也更接近 minimal chat stack。

## 11. DEFAULT_CSS

`TranscriptMessageWidget` 有自己的 CSS：

```python
DEFAULT_CSS = """
TranscriptMessageWidget {
    width: 1fr;
    height: auto;
    margin: 1 1 2 0;
}

TranscriptMessageWidget > .transcript-message-gutter {
    width: 1;
    height: auto;
}

TranscriptMessageWidget > .transcript-message-body {
    width: 1fr;
    height: auto;
    padding: 0 1 0 1;
}
...
"""
```

这里有几个 Textual CSS 概念：

```text
width: 1fr     占可用空间的一份
height: auto   高度随内容变化
margin         外边距
padding        内边距
```

右侧 body 用：

```text
width: 1fr
```

表示它跟随容器宽度，而不是被内容强行撑大。

## 12. _body_widget()

源码：

```python
def _body_widget(self) -> Static | ThemedMarkdownWidget:
    if _use_plain_transcript_body(self.item):
        body = Static(...)
    else:
        body = ThemedMarkdownWidget(...)
    return body
```

不同 role 使用不同 body widget。

纯文本类：

```text
user
tool
skill
error
```

使用 `Static`。

Markdown 类：

```text
assistant
thinking
status
branch_summary
compaction_summary
```

使用 `ThemedMarkdownWidget`。

当前代码已经有 Phase 23 之后的 Markdown polish，所以 assistant 消息会走更丰富的 Markdown 渲染。

但 Phase 17.5 的底层形状仍然一样：

```text
每条消息一个 widget
宽度可收缩
长文本可折行
```

## 13. Text overflow="fold"

纯文本 body 使用：

```python
Text(text, style=body_style, overflow="fold", no_wrap=False)
```

这里是 Rich 的 `Text`。

关键参数：

```text
overflow="fold"
no_wrap=False
```

`no_wrap=False` 表示允许换行。

`overflow="fold"` 表示长到超出宽度时折到下一行。

尤其是这种没有空格的长字符串：

```text
supercalifragilisticexpialidocioussupercalifragilisticexpialidocious
```

也要折行，而不是撑出横向滚动。

测试验证：

```python
assert max(len(line) for line in output.splitlines()) <= 36
```

## 14. render_chat_item()

这个函数用于把 `ChatItem` 渲染成 Rich renderable。

源码：

```python
def render_chat_item(
    item: ChatItem,
    *,
    theme: TuiTheme = TAU_DARK_THEME,
    show_tool_results: bool = False,
) -> RenderableType:
    """Render a chat item as a standalone Toad-inspired transcript block."""
```

它做几件事：

1. 根据 role 找样式。
2. 渲染正文。
3. 创建两列表格。
4. 左列放 `▌`。
5. 右列放 padding 后的 body。
6. 整个 block 再加外层 padding。

核心：

```python
table = Table.grid(expand=True)
table.add_column(width=1, style=role_style.border)
table.add_column(ratio=1, style=role_style.body)
table.add_row(
    Align.left(Text("▌", style=role_style.border)),
    Padding(body, (0, 1, 0, 1), style=role_style.body),
)
return Padding(table, (1, 1, 1, 0), style=role_style.body)
```

这个函数更多用于 Rich 渲染和测试。

Textual 中则主要由 `TranscriptMessageWidget` 挂载。

但视觉模型一致。

## 15. Table.grid(expand=True)

`Table.grid(expand=True)` 是 Rich 的网格布局。

它不是普通 Markdown 表格。

它用于把 renderable 按列组织。

这里两列：

```text
左列：role accent
右列：message body
```

`expand=True` 表示使用可用宽度。

这对折行很重要。

## 16. role style

`_chat_item_role_style()`：

```python
def _chat_item_role_style(item: ChatItem, theme: TuiTheme) -> TuiRoleStyle:
    if item.role == "tool" and item.tool_result_text:
        if item.tool_result_text.startswith("✓"):
            return TuiRoleStyle(...)
        if item.tool_result_text.startswith("✗"):
            return TuiRoleStyle(...)
    return theme.role_styles[item.role]
```

普通情况下根据 role 从 theme 里取样式：

```python
theme.role_styles[item.role]
```

tool 比较特殊。

如果 tool result 以：

```text
✓
```

开头，说明成功，用成功色。

如果以：

```text
✗
```

开头，说明失败，用错误色。

## 17. _use_plain_transcript_body()

源码：

```python
def _use_plain_transcript_body(item: ChatItem) -> bool:
    """Return whether a transcript item can use fast selectable plain text."""
    return item.role in {"user", "tool", "skill", "error"}
```

这表示这些 role 用 plain body：

```text
user
tool
skill
error
```

为什么 user 不走 Markdown？

因为用户输入通常应该按原文显示，避免 Markdown 解释改变文本。

assistant 则更适合 Markdown，因为模型会输出列表、代码块、表格等。

## 18. _transcript_plain_body_text()

源码核心：

```python
if item.role != "tool":
    return Text(text, style=body_style, overflow="fold", no_wrap=False)
```

非 tool 的 plain body 直接返回可折行 Text。

tool 特殊，因为 tool 有 invocation 和 result：

```python
invocation, separator, result_text = text.partition("\n\n")
```

如果有空行分隔，就把前半部分当 tool invocation，后半部分当结果正文。

这样 tool 名称和结果可以分别处理。

## 19. Markdown body

如果不是 plain body：

```python
body = ThemedMarkdownWidget(
    self._markdown_text,
    theme=self._theme,
    classes="transcript-message-body transcript-markdown-body",
)
```

当前代码已经支持：

- assistant Markdown
- inline code
- headings
- links
- lists
- tables
- fenced code blocks
- unknown language fallback

这些属于后续 Phase 23 polish 的结果。

Phase 17.5 的重点是：

```text
Markdown 也被放在每条消息自己的 body widget 里；
不会变成一个巨大 transcript 文本块。
```

## 20. selection_text：复制时拿纯文本

`TranscriptMessageWidget.__init__()`：

```python
self.selection_text = transcript_item_selection_text(
    item,
    show_tool_results=show_tool_results,
)
```

`selection_text` 是这条消息被复制时应该得到的纯文本。

为什么不直接复制渲染后的 Rich/Textual 内容？

因为渲染内容可能有：

- 颜色
- Markdown 结构
- gutter
- padding
- 语法高亮

复制时用户想要的是原始可读文本。

所以每个 message widget 保存自己的 selection_text。

## 21. get_selection()

源码：

```python
def get_selection(self, selection: Selection) -> tuple[str, str] | None:
    """Return selected plain text from this message, not rendered Markdown markup."""
    selected_text = _extract_text_selection(self.selection_text, selection)
    if not selected_text:
        return None
    return selected_text, "\n"
```

它返回：

```python
(selected_text, "\n")
```

第二个值是分隔符。

如果多个 message 被选中，TUI 可以用换行拼接。

测试：

```python
assert widget.get_selection(Selection(Offset(6, 0), Offset(10, 0))) == (
    "beta",
    "\n",
)
```

## 22. 多消息选择

测试：

```python
app.screen.selections = {
    messages[0]: Selection(Offset(6, 0), None),
    messages[1]: SELECT_ALL,
    messages[2]: Selection(None, Offset(5, 0)),
}

assert app.screen.get_selected_text() == "one\nmiddle message\nthird"
```

这说明 selection 是按 widget 分开的。

第一条选后半段：

```text
one
```

第二条全选：

```text
middle message
```

第三条选前半段：

```text
third
```

最后用换行拼起来。

这比一个大 transcript 文本区域更可控。

## 23. StreamingTranscriptMessageWidget

assistant 回复是 streaming 的。

所以有专门的：

```python
class StreamingTranscriptMessageWidget(ThemedMarkdownWidget):
    """One assistant or thinking Markdown block that accepts streamed fragments."""
```

它支持：

```python
async def append_fragment(self, fragment: str) -> None:
```

当 provider 一段一段返回 assistant delta 时：

```python
self.item.text += fragment
self.selection_text += fragment
await self.update(self.item.text)
```

这样 UI 可以逐步更新，而不是等整条消息结束。

## 24. append_assistant_delta()

`TranscriptView` 里：

```python
async def append_assistant_delta(
    self,
    delta: str,
    *,
    theme: TuiTheme = TAU_DARK_THEME,
    scroll_end: bool = False,
) -> None:
    """Append streamed assistant text to the active message widget."""
    self._active_thinking_widget = None
    self._hidden_thinking_placeholder_visible = False
    widget = await self.start_assistant_message(theme=theme, scroll_end=scroll_end)
    await widget.append_fragment(delta)
    if scroll_end:
        self.scroll_end(animate=False)
```

如果当前没有 active assistant widget，就先创建。

然后把 delta 追加进去。

测试验证 streaming delta 不会强制滚到底：

```python
assert forced_scrolls == 0
```

这是用户体验细节：

如果用户已经滚到上面看旧内容，新 token 不应该强行把他拉回底部。

## 25. on_resize()：终端尺寸变化时重绘

`TranscriptView.on_resize()`：

```python
def on_resize(self, event: Resize) -> None:
    """Re-render transcript entries when the terminal width changes."""
    del event
    if self._render_state is None:
        return
    width = self.scrollable_content_region.width
    if width <= 0 or width == self._last_render_width:
        return
    was_at_end = self.is_vertical_scroll_end
    self._redraw(scroll_end=was_at_end)
    self.scroll_to(x=0, animate=False, immediate=True)
```

当终端变窄或变宽时，transcript 需要重新按新宽度换行。

最后：

```python
self.scroll_to(x=0, animate=False, immediate=True)
```

确保横向滚动位置回到 0。

测试：

```python
assert transcript.virtual_size.width <= transcript.scrollable_content_region.width
assert transcript.scroll_offset.x == 0
```

## 26. _redraw()

`_redraw()` 会根据当前 `TuiState` 重新挂载 message widgets：

```python
self.remove_children([...])
self._active_assistant_widget = None
...
for item in state.items:
    self.mount(
        TranscriptMessageWidget(
            item,
            theme=theme,
            show_tool_results=state.show_tool_results or item.always_show_tool_result,
        )
    )
```

这说明：

```text
TuiState 是源数据；
TranscriptView 可以随时根据它重建显示。
```

这对 resize、theme change、tool result expand/collapse 都有帮助。

## 27. render_chat_item() 和 TranscriptMessageWidget 的关系

你会看到两套渲染入口：

```python
render_chat_item(...)
TranscriptMessageWidget(...)
```

它们不是互相替代。

可以这样理解：

```text
render_chat_item       Rich 级别的 renderable，方便单元测试和一些静态渲染
TranscriptMessageWidget Textual 级别的 widget，真正挂在 TUI transcript 里
```

两者共享视觉思想：

- 左侧 accent
- body 可折行
- role style
- 不用 `you:`/`assistant:` 前缀

## 28. 当前代码里的 Phase 23 影响

架构文档里写：

```text
Later Phase 23 polish keeps the same display-state shape but renders fenced
code blocks, edit patches, and assistant Markdown with Rich renderables inside
the block.
```

当前源码已经包含这些后续 polish。

所以在 `tests/test_tui_app.py` 里你会看到很多比 Phase 17.5 更高级的测试：

- fenced code 去掉反引号
- Python code 语法高亮
- unknown fenced language fallback
- inline code 渲染
- Markdown heading 左对齐
- Markdown links
- Markdown lists
- Markdown tables
- patch diff 上色

这些不是 Phase 17.5 的核心，但它们都建立在 Phase 17.5 的 message block 架构上。

也就是说：

```text
Phase 17.5 先把 transcript 变成独立 block；
后续 phase 再让 block 内部渲染更漂亮。
```

## 29. tests/test_tui_app.py 里本阶段关键测试

关键测试包括：

```text
test_chat_items_render_as_unlabeled_blocks
test_chat_items_use_left_accent_instead_of_box_border
test_chat_items_have_bottom_padding
test_chat_items_fold_long_unbroken_text_to_console_width
test_tui_app_mounts_sidebar_and_transcript
test_tui_transcript_reflows_when_terminal_resizes
test_transcript_message_widget_extracts_plain_text_selection
test_tui_transcript_selects_only_one_message
test_tui_transcript_extracts_adjacent_message_selection
test_streaming_transcript_deltas_do_not_force_scroll_end
```

它们分别验证：

- 不再显示 `you:`、`assistant:`、`tool:` 前缀
- 使用左侧 `▌` accent
- block 底部有间距
- 超长无空格文本能折行
- transcript 的 min_width 是 1
- resize 后不会产生横向滚动
- selection 是纯文本
- selection 按 message widget 管理
- streaming 不会强制滚动到底

## 30. Python 小白应该掌握的语法点

### 30.1 Literal

```python
ChatItemRole = Literal["user", "assistant", "tool"]
```

表示值只能是这些固定字符串。

### 30.2 field(default_factory=list)

```python
items: list[ChatItem] = field(default_factory=list)
```

给每个实例创建自己的新 list。

### 30.3 isinstance(A | B)

当前代码里有：

```python
isinstance(child, TranscriptMessageWidget | StreamingTranscriptMessageWidget)
```

这是 Python 新版本支持的写法，用 `|` 表示多个类型。

意思是：

```text
child 是 TranscriptMessageWidget 或 StreamingTranscriptMessageWidget 都可以。
```

### 30.4 async def

```python
async def append_assistant_delta(...)
```

这是异步函数。

Textual 的 mount/update 等操作常常需要异步。

调用时要：

```python
await transcript.append_assistant_delta("alpha")
```

### 30.5 del event

```python
def on_resize(self, event: Resize) -> None:
    del event
```

这里表示参数按框架要求必须接收，但函数内部不用它。

写 `del event` 可以让 lint 工具知道这是有意不用。

## 31. 你读源码时的推荐顺序

建议这样读：

1. `tui/state.py` 的 `ChatItemRole`
2. `tui/state.py` 的 `ChatItem`
3. `tui/state.py` 的 `TuiState.add_item()`
4. `tui/widgets.py` 的 `render_chat_item()`
5. `tui/widgets.py` 的 `TranscriptMessageWidget`
6. `tui/widgets.py` 的 `_transcript_plain_body_text()`
7. `tui/widgets.py` 的 `TranscriptView`
8. `TranscriptView.on_resize()`
9. `TranscriptView.append_assistant_delta()`
10. `tests/test_tui_app.py` 中 transcript wrapping 相关测试

这样读会先看到数据形状，再看到 Rich 静态渲染，最后看 Textual 动态挂载。

## 32. Phase 17.5 用一句话总结

Phase 17.5 的价值是：让 TUI transcript 从带 `you:`、`assistant:` 前缀的大文本区域，升级成由独立 `TranscriptMessageWidget` 组成的可滚动消息块，每条消息拥有自己的 role accent、可折行 body 和纯文本 selection，从而避免长文本撑宽终端，并为后续 Markdown、代码块、patch diff 等更精细渲染打下基础。

## 33. 我的问题与推荐回答

问题：为什么 Phase 17.5 要让每条 transcript message 成为独立 widget，而不是继续把所有消息拼成一个大字符串放进一个 Static 里？

我的推荐回答：

因为一个大字符串很难同时做好换行、样式、复制选择和 streaming 更新。独立 widget 让每条消息自己控制 body 宽度、role 颜色、纯文本 selection 和工具结果展开；`TranscriptView` 只负责滚动和挂载这些消息。这样长文本不会撑出横向滚动，复制时也能按消息边界提取纯文本，后续要给 assistant Markdown、代码块或 patch diff 增强渲染，也只需要增强单条消息的 body，而不破坏整个 transcript。
