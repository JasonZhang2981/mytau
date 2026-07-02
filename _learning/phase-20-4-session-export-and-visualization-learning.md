# Phase 20.4 学习笔记：Session Export and Visualization

对应架构文档：`dev-notes/architecture/phase-20-4-session-export.md`

对应源码：

- `src/tau_coding/session_export.py`
- `src/tau_coding/session.py`
- `src/tau_coding/cli.py`
- `src/tau_coding/commands.py`
- `src/tau_coding/tui/app.py`
- `tests/test_session_export.py`
- `tests/test_coding_session.py`
- `tests/test_cli.py`
- `tests/test_commands.py`
- `tests/test_tui_app.py`
- `website/src/content/docs/guides/sessions.md`
- `website/src/content/docs/reference/cli.md`
- `website/src/content/docs/reference/slash-commands.md`

## 1. 这一阶段到底在做什么

Phase 20.4 给 Tau 增加 session export。

前面 Phase 7 已经让 session 可以保存成 JSONL。

Phase 20.4 解决的是：

```text
保存下来的 session 怎么拿出来看？
能不能不打开 Tau TUI 也检查历史？
能不能导出成 HTML 分享或回顾？
能不能导出原始 JSONL 做备份或调试？
```

所以这一阶段是把 append-only session tree 变成用户可读 artifact。

## 2. 用户能怎么导出

架构文档列出：

```bash
tau export <session-id>
tau export <session-id> session.html
tau export <session-id> --format jsonl
tau export ~/.tau/sessions/<project>/<session-id>.jsonl
```

TUI 内部也支持：

```text
/export
/export --format jsonl
/export --format html report.html
```

当前 docs 也在：

- `website/src/content/docs/guides/sessions.md`
- `website/src/content/docs/reference/cli.md`
- `website/src/content/docs/reference/slash-commands.md`

## 3. 为什么不是只导出普通聊天记录

Tau 的 session 不是一个简单 list。

从 Phase 7 开始，它是：

```text
append-only session entries + parent_id tree
```

里面可能有：

- user message
- assistant message
- tool result
- model change
- thinking level change
- compaction
- branch summary
- leaf pointer
- custom entry

如果只导出普通聊天记录，会丢掉很多重要结构。

所以 Phase 20.4 的 HTML export 有两块：

```text
Session Tree
Transcript Entries
```

## 4. `session_export.py`

核心文件：

```text
src/tau_coding/session_export.py
```

它的定位是：

```text
把 SessionEntry 序列渲染成 HTML 或 JSONL artifact
```

它属于 `tau_coding`。

因为 export 是应用层工作流，不属于 reusable agent brain。

## 5. 为什么 export 不放在 `tau_agent`

`tau_agent` 只需要定义：

- session entry 类型
- JSONL 读写
- replay
- tree traversal

它不应该知道：

- HTML 怎么写
- CSS 怎么写
- CLI 命令怎么叫
- TUI `/export` 怎么提示
- 默认导出到哪个 cwd

所以 export 放在 `tau_coding`。

## 6. `SessionExportError`

源码：

```python
class SessionExportError(ValueError):
    """Raised when a session cannot be exported."""
```

这是导出层自己的错误类型。

例如用户传了不支持的格式：

```text
pdf
```

就会抛：

```text
Unsupported export format
```

## 7. 默认导出路径

源码：

```python
def default_session_export_path(session_path: Path) -> Path:
    return session_path.with_suffix(".html")
```

这个函数表示：

```text
如果 session 文件是 session.jsonl
默认 HTML 是 session.html
```

但 Phase 20.4 又新增了用户友好的 artifact 路径：

```python
def default_session_export_artifact_path(
    session_path: Path,
    *,
    destination_dir: Path,
    format: str = "html",
) -> Path:
    suffix = _export_suffix(format)
    return destination_dir / f"{session_path.stem}{suffix}"
```

这表示：

```text
默认导出到用户当前目录，而不是写回 Tau 内部 session storage 目录
```

例如：

```text
~/.tau/sessions/project/session-1.jsonl
```

导出到当前目录：

```text
./session-1.html
```

## 8. `normalize_export_format()`

源码：

```python
def normalize_export_format(value: str | None) -> str:
    normalized = (value or "html").strip().lower().removeprefix(".")
    if normalized in {"htm", "html"}:
        return "html"
    if normalized == "jsonl":
        return "jsonl"
    raise SessionExportError(f"Unsupported export format: {value}")
```

支持：

- `html`
- `.html`
- `htm`
- `.htm`
- `jsonl`
- `.jsonl`

默认是：

```text
html
```

## 9. `export_session_jsonl()`

源码：

```python
def export_session_jsonl(entries: Sequence[SessionEntry], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [entry.model_dump_json() for entry in entries]
    output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return output_path
```

它把 entries 重新写成 JSONL。

这里用的是 Pydantic 的：

```python
entry.model_dump_json()
```

每个 entry 一行。

如果 entries 不为空，最后加一个换行。

这和 Unix 文本文件习惯一致。

## 10. `export_session_html()`

源码：

```python
def export_session_html(entries, output_path, *, title="Tau Session Export", source=None):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_session_html(entries, title=title, source=source),
        encoding="utf-8",
    )
    return output_path
```

它负责写文件。

真正生成 HTML 字符串的是：

```python
render_session_html()
```

## 11. `export_session_artifact()`

源码：

```python
def export_session_artifact(..., format: str | None = None) -> Path:
    export_format = normalize_export_format(format or output_path.suffix.removeprefix("."))
    if export_format == "jsonl":
        return export_session_jsonl(entries, output_path)
    return export_session_html(entries, output_path, title=title, source=source)
```

这个函数是统一入口。

它根据 format 决定写：

- JSONL
- HTML

调用方不用自己分支。

## 12. HTML 是 self-contained

`render_session_html()` 返回完整文档：

```html
<!doctype html>
<html lang="en">
<head>
  ...
  <style>
    ...
  </style>
</head>
<body>
...
</body>
</html>
```

CSS 直接内联在 `<style>` 里。

所以导出的 HTML 不需要 Tau 服务、不需要 Textual、不需要额外 JS。

用户可以直接打开文件。

## 13. `html` 标准库

`session_export.py` 里：

```python
import html
```

用于：

```python
html.escape(...)
```

为什么要 escape？

假设用户消息是：

```text
Start <session>
```

如果不 escape，浏览器可能把 `<session>` 当成 HTML 标签。

测试里验证：

```python
assert "Start &lt;session&gt;" in html
```

这就是 HTML escape。

## 14. `datetime` 和 `UTC`

源码：

```python
generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
```

导出文件会包含生成时间。

`UTC` 是标准库里的时区对象。

`replace(microsecond=0)` 去掉微秒，让显示更干净。

`isoformat()` 输出类似：

```text
2026-07-01T12:34:56+00:00
```

## 15. active leaf

源码：

```python
def _active_leaf_id(entries):
    for entry in reversed(entries):
        if isinstance(entry, LeafEntry):
            return entry.entry_id
    if entries:
        return entries[-1].id
    return None
```

逻辑：

```text
从后往前找最后一个 LeafEntry
如果找到了，用它的 entry_id
如果没有 leaf，但有 entries，用最后一条 entry
如果没有 entries，返回 None
```

active leaf 表示当前 session tree 的活动分支终点。

## 16. active path

源码：

```python
def _active_path_ids(entries, active_leaf_id):
    if active_leaf_id is None:
        return set()
    try:
        return {entry.id for entry in path_to_entry(entries, active_leaf_id)}
    except SessionTreeError:
        return {active_leaf_id}
```

它用 Phase 7 的：

```python
path_to_entry()
```

找出 root-to-leaf 路径。

HTML 中这些节点会加：

```text
active-path
active-leaf
```

用于 CSS 高亮。

## 17. `_render_tree()`

这个函数把 entries 渲染成树。

核心数据结构：

```python
children_by_parent: dict[str | None, list[SessionEntry]] = defaultdict(list)
```

`defaultdict` 来自标准库 `collections`。

它的好处是：

```python
children_by_parent[entry.parent_id].append(entry)
```

即使 key 还不存在，也会自动创建空 list。

## 18. root 节点

源码：

```python
roots = [
    entry for entry in entries if entry.parent_id is None or entry.parent_id not in entry_ids
]
```

root 包括：

- `parent_id is None`
- parent 缺失的 entry

后者是为了容错。

即使 session tree 有坏链接，export 也尽量显示出来，而不是直接崩。

## 19. `_render_tree_node()`

这个函数递归渲染一个节点和它的子节点。

递归就是函数调用自己。

每个节点会输出类似：

```html
<li class="tree-node active-path">
  <a class="node-link" href="#entry-root">
    <span class="node-type">message:user</span>
    <span class="node-meta">Start</span>
  </a>
  ...
</li>
```

点击树节点可以跳到详情区对应 entry。

## 20. 防止循环

session tree 理论上不应该有环。

但 export 需要尽量 robust。

所以 `_render_tree_node()` 接收：

```python
ancestors: set[str]
rendered_ids: set[str]
```

用于避免无限递归。

## 21. `_render_entry_details()`

树只是导航。

真正详情在：

```python
_render_entry_details()
```

它按 storage order 遍历 entries：

```python
for index, entry in enumerate(entries, start=1)
```

这很重要。

HTML 同时保留两种视角：

```text
tree order       看 parent-child/branch
storage order    看 append-only 写入顺序
```

## 22. `_render_entry_body()`

这个函数根据 entry 类型渲染不同正文。

支持：

- `MessageEntry`
- `ModelChangeEntry`
- `ThinkingLevelChangeEntry`
- `CompactionEntry`
- `BranchSummaryEntry`
- `LabelEntry`
- `LeafEntry`
- `SessionInfoEntry`
- `CustomEntry`

这比普通 transcript 更完整。

## 23. message rendering

`_render_message_entry()` 里继续区分：

- `UserMessage`
- `AssistantMessage`
- `ToolResultMessage`

assistant message 如果有 tool calls，会显示：

```text
Tool calls
```

tool result 会显示：

- tool name
- tool_call_id
- ok
- error
- content
- data
- details

这对调试 agent 行为很有帮助。

## 24. `CodingSession.export()`

`src/tau_coding/session.py`：

```python
async def export(self, destination: Path | None = None, *, format: str | None = None) -> Path:
    entries = await self._read_session_entries()
    session_path = _storage_path(self._config.storage)
    export_format = normalize_export_format(...)
    output_path = _resolve_export_destination(...)
    return export_session_artifact(...)
```

这说明：

```text
CodingSession 负责读取当前 session storage
session_export 负责真正写 artifact
```

## 25. 默认导出到 cwd

测试验证：

```python
output_path = await session.export()
assert output_path == tmp_path / "session-1.html"
```

这里 `tmp_path` 是 session cwd。

也就是说，交互式 session 里 `/export` 默认把文件写到当前项目目录，而不是内部 `~/.tau/sessions/...`。

## 26. CLI `tau export`

`src/tau_coding/cli.py` 里：

```python
if prompt_option is None and command == "export":
    session_ref, output_path, export_format = _parse_export_cli_args(...)
    exported_path = anyio.run(export_session_command, ...)
```

CLI 支持两种 source：

```text
session id
JSONL 文件路径
```

`_resolve_export_source()` 会先把输入当路径看。

如果路径存在，就直接用这个 JSONL 文件。

如果路径不存在，就当 session id 去 `SessionManager` 里查。

## 27. suffixless output path

测试：

```python
output_path = await cli.export_session_command(str(session_path), tmp_path / "exports")
assert output_path == tmp_path / "exports" / "session.html"
```

如果用户传的输出路径没有后缀：

```text
exports
```

Tau 把它当目录。

如果有后缀：

```text
session.html
```

Tau 把它当具体文件。

## 28. TUI `/export`

`commands.py` 解析：

```text
/export [--format html|jsonl] [destination]
```

返回：

```python
CommandResult(export_requested=True, export_destination=..., export_format=...)
```

TUI app 收到后：

```python
exported_path = await self.session.export(...)
self._notify(f"Exported session to {exported_path}")
```

所以 TUI 和 CLI 复用同一套 session export 逻辑。

## 29. 当前文档系统差异

架构文档最后的 full gate 还写了：

```bash
uv run --group docs mkdocs build --strict
```

但当前仓库已经迁移到 Astro/Starlight 文档站。

所以当前应理解为：

```text
架构意图：导出功能需要文档覆盖
当前形态：website/src/content/docs/ 里的 sessions/cli/slash-command 文档
```

## 30. 测试如何覆盖这一阶段

### 30.1 `tests/test_session_export.py`

覆盖：

- HTML 保留 branch tree
- active path / active leaf 高亮
- HTML escape
- tool calls 和 compaction 信息出现
- `export_session_html()` 写文件

### 30.2 `tests/test_coding_session.py`

覆盖：

- `session.export()` 默认写到 cwd
- JSONL format 写到目标目录

### 30.3 `tests/test_cli.py`

覆盖：

- indexed session id 导出 HTML
- JSONL path 导出 HTML
- `--format jsonl` 导出 JSONL
- 无后缀 destination 当目录
- CLI 参数解析

### 30.4 `tests/test_commands.py`

覆盖：

- `/export`
- `/export --format jsonl exports/session.jsonl`

### 30.5 `tests/test_tui_app.py`

覆盖：

- TUI `/export` 会调用 `session.export()`
- 成功后 notify exported path

## 31. 小白必须分清的几组概念

### 31.1 export 不是 session persistence

Persistence 是运行时持续写 JSONL。

Export 是把已有 session entries 转成用户可查看 artifact。

### 31.2 HTML export 不是 TUI

HTML 是静态文件。

不需要 Textual，不需要 Python 进程。

### 31.3 tree view 和 transcript view 不同

Tree view 看分支结构。

Transcript/details view 看 append-only 写入顺序和 entry 详情。

### 31.4 JSONL export 是原始数据导出

HTML 适合人看。

JSONL 适合备份、调试、程序处理。

### 31.5 CLI 和 TUI 复用同一底层

`tau export` 和 `/export` 最后都走 session export helper。

这减少行为分叉。

## 32. 运行测试

Phase 20.4 相关测试：

```bash
uv run pytest tests/test_session_export.py tests/test_cli.py tests/test_coding_session.py tests/test_commands.py tests/test_tui_app.py -k export
```

如果想跑更完整一点：

```bash
uv run pytest tests/test_session_export.py tests/test_cli.py tests/test_coding_session.py tests/test_commands.py tests/test_tui_app.py
```

## 33. 用一句话总结 Phase 20.4

Phase 20.4 的价值是：把 Tau 的 append-only JSONL session tree 导出成可检查、可分享的静态 HTML 或原始 JSONL artifact，让用户在 TUI 之外也能理解消息、工具调用、compaction、thinking/model changes、leaf pointer 和 branch path。

## 34. 我的问题与推荐回答

问题：为什么 Tau 的 HTML export 要同时显示 session tree 和 storage-order transcript/details，而不是只显示最终聊天记录？

我的推荐回答：

因为 Tau session 是 append-only tree，不是单纯的线性聊天记录。branch/fork、leaf pointer、compaction、model change、thinking change、tool result 都是 session 历史的一部分。只显示最终聊天记录会丢掉 parent-child 关系和写入顺序，调试 replay、branch 或 compaction 时很难判断发生了什么。Phase 20.4 同时保留 tree view 和 storage-order details，让用户既能看当前 active path，也能检查完整 JSONL 历史。
