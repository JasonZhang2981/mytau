# Phase 7 学习笔记：Session Tree and JSONL Persistence

对应架构文档：`dev-notes/architecture/phase-7-session-tree.md`

对应源码：

- `src/tau_agent/session/entries.py`
- `src/tau_agent/session/jsonl.py`
- `src/tau_agent/session/storage.py`
- `src/tau_agent/session/tree.py`
- `src/tau_agent/session/memory.py`
- `src/tau_agent/session/__init__.py`
- `tests/test_session.py`

前置阶段：

- Phase 1：定义 `AgentMessage`
- Phase 3：agent loop 会把新消息追加到 transcript
- Phase 4：`AgentHarness` 拥有内存 transcript
- Phase 6：print mode 已经需要保存运行后的 session

## 1. 这一阶段到底在做什么

Phase 7 给 Tau 增加第一层 durable session 能力。

前面的 transcript 主要在内存里：

```text
[UserMessage, AssistantMessage, ToolResultMessage, ...]
```

进程结束后，如果不保存，这些消息就没了。

Phase 7 开始定义一种可以落盘、可以恢复、可以分支的 session 格式。

核心思想是：

```text
不要原地修改旧状态
只追加新的 SessionEntry
需要当前状态时再 replay
```

这叫 append-only session tree。

## 2. 为什么 session 是 append-only

append-only 的意思是：会话文件只往后追加新记录，不回头修改旧记录。

好处：

- 文件容易检查，一行一个 JSON
- 写入简单，追加比修改安全
- 历史不会被覆盖
- 以后可以支持分支和 fork
- compaction、summary、label 这类状态变化也能作为历史保留

一个 session 文件大概长这样：

```jsonl
{"type":"message","id":"user","message":{"role":"user","content":"Hello"}}
{"type":"message","id":"assistant","parent_id":"user","message":{"role":"assistant","content":"Hi"}}
{"type":"label","id":"label","label":"Greeting"}
```

每一行都是一个 JSON 对象，所以叫 JSONL。

JSONL = JSON Lines。

## 3. 为什么 session primitives 放在 `tau_agent`

Phase 7 的源码在：

```text
src/tau_agent/session/
```

因为 session tree 是 reusable agent brain 的一部分。

它只关心：

- 消息如何保存
- 状态 entry 如何 replay
- branch path 如何恢复
- JSONL 如何序列化

它不关心：

- session 文件具体放在 `~/.tau/` 还是别处
- CLI 命令怎么叫
- TUI 怎么显示 session
- slash command 怎么处理
- cwd 和项目资源怎么发现

这些属于后面的 `tau_coding` session wrapper。

## 4. `entries.py`：定义 append-only entry 类型

这个文件定义所有 session entry 的 Pydantic 模型。

### 4.1 `new_entry_id()`

源码：

```python
def new_entry_id() -> str:
    return uuid4().hex
```

`uuid4()` 会生成随机 UUID。

`.hex` 会返回不带横线的字符串。

比如：

```text
7d9f2f0d4b9f49d68b47b7df7f4b91aa
```

每个 entry 默认都有唯一 id。

### 4.2 `current_timestamp()`

源码：

```python
def current_timestamp() -> float:
    return time()
```

`time()` 返回 Unix timestamp。

它是一个浮点数，表示从 1970-01-01 00:00:00 UTC 到现在的秒数。

### 4.3 `BaseSessionEntry`

源码：

```python
class BaseSessionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_entry_id)
    parent_id: str | None = None
    timestamp: float = Field(default_factory=current_timestamp)
```

所有 session entry 都有：

- `id`：这条 entry 的唯一 id
- `parent_id`：父 entry id，用于形成 tree
- `timestamp`：创建时间

`Field(default_factory=...)` 表示每次创建实例时动态生成默认值。

不能写成：

```python
id: str = new_entry_id()
```

因为那样会在类定义时只执行一次。

### 4.4 `parent_id` 是 session tree 的关键

线性会话可以这样：

```text
user -> assistant -> user2 -> assistant2
```

分支会话可以这样：

```text
root
 ├─ left
 └─ right
```

靠的就是每个 entry 的：

```python
parent_id: str | None
```

## 5. entry 类型列表

Phase 7 定义了这些 entry。

### 5.1 `MessageEntry`

```python
class MessageEntry(BaseSessionEntry):
    type: Literal["message"] = "message"
    message: AgentMessage
```

保存 transcript 消息。

比如：

```python
MessageEntry(message=UserMessage(content="Hello"))
```

这里的 `message` 可以是 Phase 1 定义的：

- `UserMessage`
- `AssistantMessage`
- `ToolResultMessage`

### 5.2 `ModelChangeEntry`

```python
class ModelChangeEntry(BaseSessionEntry):
    type: Literal["model_change"] = "model_change"
    model: str
```

记录模型选择变化。

比如从 `gpt-5.5` 切到另一个模型。

### 5.3 `ThinkingLevelChangeEntry`

```python
class ThinkingLevelChangeEntry(BaseSessionEntry):
    type: Literal["thinking_level_change"] = "thinking_level_change"
    thinking_level: str | None = None
```

记录 thinking/reasoning level 变化。

这是当前源码里后续 thinking 功能的基础。

### 5.4 `CompactionEntry`

```python
class CompactionEntry(BaseSessionEntry):
    type: Literal["compaction"] = "compaction"
    summary: str
    replaces_entry_ids: list[str] = Field(default_factory=list)
```

记录上下文压缩摘要。

架构文档说它一开始是 placeholder，但当前源码已经能 replay compaction。

意思是：

```text
这些旧 message 被 summary 代替
```

### 5.5 `BranchSummaryEntry`

```python
class BranchSummaryEntry(BaseSessionEntry):
    type: Literal["branch_summary"] = "branch_summary"
    summary: str
    branch_root_id: str | None = None
```

记录某个分支的摘要。

当前 `SessionState` 会把它 replay 成一条 `UserMessage` 风格的上下文摘要。

### 5.6 `LabelEntry`

```python
class LabelEntry(BaseSessionEntry):
    type: Literal["label"] = "label"
    label: str
```

记录会话标题或标签。

### 5.7 `LeafEntry`

```python
class LeafEntry(BaseSessionEntry):
    type: Literal["leaf"] = "leaf"
    entry_id: str | None = None
```

记录当前活动分支的 leaf pointer。

可以理解成：

```text
当前会话视图应该停在哪个 entry 上
```

### 5.8 `SessionInfoEntry`

```python
class SessionInfoEntry(BaseSessionEntry):
    type: Literal["session_info"] = "session_info"
    created_at: float = Field(default_factory=current_timestamp)
    cwd: str | None = None
    title: str | None = None
```

记录会话元信息，比如创建时间、cwd、标题。

### 5.9 `CustomEntry`

```python
class CustomEntry(BaseSessionEntry):
    type: Literal["custom"] = "custom"
    namespace: str
    data: dict[str, JSONValue] = Field(default_factory=dict)
```

给扩展或应用层保存自定义数据。

`namespace` 用来区分不同来源。

## 6. `SessionEntry` 联合类型

源码：

```python
type SessionEntry = Annotated[
    MessageEntry
    | ModelChangeEntry
    | ThinkingLevelChangeEntry
    | CompactionEntry
    | BranchSummaryEntry
    | LabelEntry
    | LeafEntry
    | SessionInfoEntry
    | CustomEntry,
    Field(discriminator="type"),
]
```

这表示一条 session entry 可以是以上任意一种。

### 6.1 `Field(discriminator="type")`

这是 Pydantic 的 discriminated union。

意思是：反序列化时看 `type` 字段来判断具体是哪种模型。

比如 JSON 里：

```json
{"type":"message", ...}
```

Pydantic 就知道应该解析成 `MessageEntry`。

如果：

```json
{"type":"label", ...}
```

就解析成 `LabelEntry`。

这比手写一堆 if/else 更稳。

## 7. `jsonl.py`：JSONL 编解码

这个文件负责 session entry 和 JSON line 之间的转换。

### 7.1 `TypeAdapter`

源码：

```python
_SESSION_ENTRY_ADAPTER: TypeAdapter[SessionEntry] = TypeAdapter(SessionEntry)
```

Pydantic 的 `TypeAdapter` 可以直接校验、序列化一个类型。

这里的类型不是一个普通 BaseModel 类，而是 `SessionEntry` 联合类型。

所以需要 `TypeAdapter`。

### 7.2 `entry_to_json_line()`

源码：

```python
def entry_to_json_line(entry: SessionEntry) -> str:
    return _SESSION_ENTRY_ADAPTER.dump_json(entry).decode() + "\n"
```

作用：把 entry 转成一行 JSON 字符串，并加换行。

`dump_json()` 返回 bytes，所以要 `.decode()` 转成 str。

### 7.3 `entry_from_json_line()`

源码：

```python
def entry_from_json_line(line: str, *, line_number: int | None = None) -> SessionEntry:
    try:
        return _SESSION_ENTRY_ADAPTER.validate_json(line)
    except ValidationError as exc:
        location = f" on line {line_number}" if line_number is not None else ""
        raise SessionJsonlError(f"Invalid session entry{location}: {exc}") from exc
```

作用：把一行 JSON 转回 typed session entry。

如果失败，会抛 `SessionJsonlError`。

`from exc` 的意思是保留原始异常链，方便调试。

### 7.4 `entries_from_json_lines()`

```python
for index, line in enumerate(lines, start=1):
    if not line.strip():
        continue
    entries.append(entry_from_json_line(line, line_number=index))
```

它会：

- 按行号遍历
- 跳过空行
- 解析每一行
- 出错时带上 line number

测试里：

```python
with pytest.raises(SessionJsonlError, match="Invalid session entry on line 3"):
    entry_from_json_line('{"type":"unknown"}', line_number=3)
```

## 8. `storage.py`：存储接口和 JSONL 实现

### 8.1 `SessionStorage` Protocol

源码：

```python
class SessionStorage(Protocol):
    async def append(self, entry: SessionEntry) -> None:
        ...

    async def read_all(self) -> list[SessionEntry]:
        ...
```

这是存储接口。

只要一个对象有这两个 async 方法，就可以被当成 session storage。

这使得后面可以有：

- JSONL 文件 storage
- 内存 storage
- 测试 fake storage
- 未来数据库 storage

### 8.2 `JsonlSessionStorage`

源码：

```python
class JsonlSessionStorage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
```

它把 session 保存到本地 JSONL 文件。

### 8.3 append

```python
async def append(self, entry: SessionEntry) -> None:
    self.path.parent.mkdir(parents=True, exist_ok=True)
    with self.path.open("a", encoding="utf-8") as file:
        file.write(entry_to_json_line(entry))
```

做了两件事：

1. 自动创建父目录
2. 用 append 模式 `"a"` 写入一行

`"a"` 表示 append，不覆盖原文件。

### 8.4 read_all

```python
async def read_all(self) -> list[SessionEntry]:
    if not self.path.exists():
        return []
    return entries_from_json_lines(self.path.read_text(encoding="utf-8").splitlines())
```

如果文件不存在，就返回空列表。

这让新 session 的加载更简单。

## 9. `tree.py`：从 entry id 还原分支路径

### 9.1 `entries_by_id()`

源码：

```python
def entries_by_id(entries: list[SessionEntry]) -> dict[str, SessionEntry]:
    result = {}
    for entry in entries:
        if entry.id in result:
            raise SessionTreeError(...)
        result[entry.id] = entry
    return result
```

作用：把 entry list 转成按 id 索引的 dict。

同时拒绝重复 id。

### 9.2 `path_to_entry()`

源码：

```python
def path_to_entry(entries: list[SessionEntry], leaf_id: str) -> list[SessionEntry]:
    by_id = entries_by_id(entries)
    path = []
    seen = set()
    current_id = leaf_id

    while current_id is not None:
        ...
        path.append(entry)
        current_id = entry.parent_id

    path.reverse()
    return path
```

它从 leaf id 一路沿着 parent_id 往上找 root。

找到的顺序是：

```text
leaf -> parent -> grandparent -> root
```

所以最后要：

```python
path.reverse()
```

变成：

```text
root -> ... -> leaf
```

### 9.3 为什么要 `seen`

```python
if current_id in seen:
    raise SessionTreeError(f"Cycle detected ...")
```

如果 session entry 形成循环：

```text
a.parent = b
b.parent = a
```

那就会无限循环。

`seen` 用来检测循环。

### 9.4 branch path 示例

测试里：

```python
root = MessageEntry(id="root", ...)
left = MessageEntry(id="left", parent_id="root", ...)
right = MessageEntry(id="right", parent_id="root", ...)

path_to_entry([root, left, right], "right")
```

结果是：

```python
[root, right]
```

左分支不会混进来。

## 10. `memory.py`：replay 成 SessionState

`SessionState` 是从 append-only entries replay 得到的当前内存状态。

源码：

```python
@dataclass(frozen=True, slots=True)
class SessionState:
    messages: tuple[AgentMessage, ...]
    model: str | None
    thinking_level: str | None
    label: str | None
    active_leaf_id: str | None
    session_info: SessionInfoEntry | None
    custom_entries: tuple[CustomEntry, ...]
    compaction_entries: tuple[CompactionEntry, ...]
    context_entry_ids: tuple[str, ...]
    entries: tuple[SessionEntry, ...]
```

它包含：

- 当前 transcript messages
- 当前 model
- 当前 thinking level
- 当前 label
- 当前 active leaf
- session metadata
- custom entries
- compaction entries
- 当前上下文对应的 entry ids
- replay 过的原始 entries

## 11. `SessionState.from_entries()`

这是 replay 入口。

### 11.1 不传 leaf_id：线性 replay

```python
state = SessionState.from_entries(entries)
```

默认按 storage 顺序 replay 所有 entries。

适合普通线性 session。

### 11.2 传 leaf_id：只 replay 一条分支路径

```python
state = SessionState.from_entries(entries, leaf_id="right")
```

会先调用：

```python
path_to_entry(entries, "right")
```

只拿 root 到 right 的路径。

这样 sibling branch 不会泄漏进 transcript。

### 11.3 显式传 `leaf_id=None`

测试里：

```python
state = SessionState.from_entries([root], leaf_id=None)
```

这表示 replay 空路径。

结果：

```python
state.messages == ()
state.active_leaf_id is None
```

这和“不传 leaf_id”不同。

源码用 `_UNSET_LEAF_ID` 来区分：

```python
leaf_id 没传
leaf_id 显式传 None
```

## 12. replay 的 match/case

源码：

```python
for entry in replay_entries:
    match entry.type:
        case "message":
            message_rows.append((entry.id, entry.message))
        case "model_change":
            model = entry.model
        case "thinking_level_change":
            thinking_level = entry.thinking_level
        case "label":
            label = entry.label
        case "leaf":
            active_leaf_id = entry.entry_id
        case "session_info":
            session_info = entry
        case "custom":
            custom_entries.append(entry)
        case "compaction":
            ...
        case "branch_summary":
            ...
```

这是 Python 的结构化模式匹配。

可以理解成更适合复杂对象的 switch/case。

这里根据 `entry.type` 更新不同状态。

## 13. 为什么 `message_rows` 保存 entry id 和 message

源码：

```python
message_rows: list[tuple[str, AgentMessage]] = []
```

它不只保存 message，还保存 entry id。

因为 compaction 需要知道哪些 message entry 被替换：

```python
replaces_entry_ids=["user", "assistant"]
```

如果只保存 message，就不知道谁该被 summary 替换。

## 14. compaction replay

当前源码已经支持 compaction。

测试：

```python
compaction = CompactionEntry(
    id="compact",
    summary="The user asked about sessions...",
    replaces_entry_ids=["user", "assistant"],
)
```

replay 后，旧 user 和 assistant 会被替换成：

```python
UserMessage(
    content="Previous conversation summary:\nThe user asked about sessions..."
)
```

### 14.1 `_apply_compaction()`

逻辑是：

1. 遍历当前 message rows
2. 如果 entry_id 不在 replaced_ids，保留
3. 如果在 replaced_ids，第一次遇到时插入 summary
4. 后续被替换的 entry 跳过
5. 如果没有匹配任何旧 message，也追加 summary

这样 compaction summary 会进入模型上下文，但旧消息不会重复进入。

## 15. branch summary replay

`BranchSummaryEntry` 会被 replay 成一条 UserMessage：

```text
The following is a summary of a branch that this conversation came back from:
<summary>
...
</summary>
```

这让模型在回到主线时知道旁支发生了什么。

当前源码还有一个细节：

```python
latest_branch_summary_index = _latest_branch_summary_index(replay_entries)
if latest_branch_summary_index is not None:
    replay_entries = replay_entries[latest_branch_summary_index:]
```

如果 replay path 上有 branch summary，就从最近的 branch summary 开始 replay。

这避免更早的 branch 内容直接混进当前上下文。

## 16. `__init__.py`：对外导出

`src/tau_agent/session/__init__.py` 把常用类型导出：

- `MessageEntry`
- `ModelChangeEntry`
- `ThinkingLevelChangeEntry`
- `CompactionEntry`
- `BranchSummaryEntry`
- `LabelEntry`
- `LeafEntry`
- `SessionInfoEntry`
- `CustomEntry`
- `SessionState`
- `JsonlSessionStorage`
- `SessionStorage`
- `entry_to_json_line`
- `entry_from_json_line`
- `path_to_entry`

所以外部可以写：

```python
from tau_agent.session import JsonlSessionStorage, MessageEntry, SessionState
```

## 17. tests/test_session.py 怎么读

建议按下面顺序读。

### 17.1 JSONL 往返

```python
test_session_entry_round_trips_jsonl
test_tool_result_message_metadata_round_trips_jsonl
test_compaction_entry_round_trips_jsonl
```

验证 entry 序列化再反序列化后仍然相等。

特别注意 tool result metadata：

```python
data={"patch": "..."}
details={"first_changed_line": 12}
```

也能保存和恢复。

### 17.2 错误 JSONL

```python
test_invalid_jsonl_line_raises_useful_error
```

验证无效 entry 会抛 `SessionJsonlError`，并带 line number。

### 17.3 JSONL storage

```python
test_jsonl_storage_appends_and_reads_entries
test_jsonl_storage_missing_file_is_empty
```

验证 append/read 和文件不存在为空。

### 17.4 线性 replay

```python
test_session_state_replays_linear_entries
```

验证：

- messages
- model
- label
- active leaf
- custom entries
- context_entry_ids

都能从 entries replay 出来。

### 17.5 branch replay

```python
test_path_to_entry_returns_root_to_leaf_branch
test_session_state_can_replay_one_branch
```

验证只 replay root 到指定 leaf 的路径。

### 17.6 compaction 和 branch summary

```python
test_session_state_replays_compaction_as_context_summary
test_session_state_inserts_partial_compaction_before_retained_messages
test_session_state_replays_branch_summary_as_context_summary
test_session_state_replays_compaction_on_active_branch
```

验证当前源码已经支持 summary 类 entry 影响 replay 上下文。

### 17.7 缺 parent 报错

```python
test_path_to_entry_rejects_missing_parent
```

如果 parent_id 指向不存在的 entry，抛 `SessionTreeError`。

## 18. Phase 7 里用到的 Python 知识

### 18.1 `uuid4`

生成唯一 id。

```python
uuid4().hex
```

### 18.2 `time()`

生成 Unix timestamp。

### 18.3 Pydantic discriminated union

```python
Field(discriminator="type")
```

让 Pydantic 根据 `type` 字段选择具体 entry 模型。

### 18.4 `TypeAdapter`

用于校验和序列化非普通 BaseModel 的类型，比如 union。

### 18.5 `Protocol`

定义 storage 接口。

只要对象有 `append()` 和 `read_all()`，就可以当 `SessionStorage`。

### 18.6 `match/case`

根据 `entry.type` 分支处理不同 entry。

### 18.7 `dataclass(frozen=True, slots=True)`

用于不可随意修改的轻量状态快照。

### 18.8 `Final`

源码：

```python
_UNSET_LEAF_ID: Final[object] = object()
```

`Final` 表示这个变量不应该被重新赋值。

这里的 `_UNSET_LEAF_ID` 是哨兵对象，用于区分“参数没传”和“参数显式传 None”。

## 19. 小白必须分清的几组概念

### 19.1 transcript message 不是 session entry

`UserMessage`、`AssistantMessage`、`ToolResultMessage` 是 transcript message。

`MessageEntry` 是把 message 包起来、带上 id/parent/timestamp 后保存到 session 文件的 entry。

### 19.2 JSONL 不是一个大 JSON 数组

JSONL 是一行一个 JSON 对象。

追加时只需要往文件末尾写一行。

### 19.3 append-only 不是不能改变状态

状态当然会改变。

但不是修改旧 entry，而是追加新 entry。

当前状态通过 replay 算出来。

### 19.4 leaf 不是普通消息

`LeafEntry` 是当前活动分支指针。

它告诉系统“当前视图停在哪个 entry 上”。

### 19.5 branch replay 不是按文件顺序全读

传了 `leaf_id` 时，只 replay root-to-leaf path。

兄弟分支不会进入当前 transcript。

## 20. 运行测试

Phase 7 最相关测试：

```text
tests/test_session.py
```

运行：

```bash
uv run pytest tests/test_session.py
```

这组测试覆盖：

- session entry JSONL 往返
- tool result metadata 持久化
- compaction entry 往返
- invalid JSONL error
- JSONL append/read
- missing file empty session
- linear replay
- explicit empty leaf replay
- compaction replay
- branch summary replay
- root-to-leaf path reconstruction
- missing parent validation

## 21. 用一句话总结 Phase 7

Phase 7 的价值是：把 agent 的对话消息和状态变化定义成 append-only session entries，并用 JSONL 文件持久化，再通过 replay 和 root-to-leaf traversal 恢复当前 session state，为后续 CodingSession、resume、branch/fork、compaction 打基础。

## 22. 我的问题与推荐回答

问题：为什么 Tau 不直接把当前 transcript 覆盖写成一个 JSON 文件，而要用 append-only JSONL entries？

我的推荐回答：

因为 coding agent 的会话不是单纯的“当前消息列表”，还包含模型切换、label、leaf 指针、compaction、branch summary、未来的分支/fork 等状态变化。append-only JSONL 可以保留完整历史，每次只追加一行，写入简单且更适合崩溃恢复；需要当前视图时通过 replay 得到。这样既能恢复线性 transcript，也能按 leaf_id 只恢复某条分支路径，避免 sibling branch 混进当前上下文。
