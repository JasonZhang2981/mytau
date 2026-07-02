# Phase 14 学习笔记：Session Manager and Resume

对应架构文档：`dev-notes/architecture/phase-14-session-manager-resume.md`

主要源码：

- `src/tau_coding/session_manager.py`
- `src/tau_coding/session.py`
- `src/tau_coding/cli.py`
- `src/tau_coding/tui/app.py`
- `tests/test_session_manager.py`
- `tests/test_coding_session.py`
- `tests/test_cli.py`
- `tests/test_tui_app.py`

前置阶段：

- Phase 7：append-only JSONL session entries
- Phase 8：`CodingSession` 可以加载和持久化 transcript
- Phase 13：`TauPaths` 定义了用户 home 下按项目隔离的 session 路径
- Phase 14：把 session metadata 升级成可创建、可索引、可列出、可恢复的记录

## 1. 这一阶段到底在做什么

Phase 14 给 Tau 加入了真正的 session manager：

```python
SessionManager
```

它位于：

```text
src/tau_coding/session_manager.py
```

你可以先用一句话理解：

Phase 14 把“一个 session JSONL 文件”升级成“一个可被用户看到、可列出、可恢复、可更新 metadata 的 session record”。

前面 Phase 7/8 已经能保存对话消息。

但只有 JSONL 文件还不够。

用户还需要：

- 创建新 session
- 看到有哪些 session
- 按 id 恢复某个 session
- 知道 session 属于哪个 cwd
- 知道 session 用的 model/provider
- 知道最近更新时间
- TUI 能 `/resume <session-id>`
- CLI 能 `tau sessions`

这些就是 `SessionManager` 的职责。

## 2. transcript 和 metadata 的区别

Phase 14 最重要的概念是分清两类数据：

### Transcript

真正的会话内容。

存储在：

```text
<session-id>.jsonl
```

里面是 Phase 7 的 append-only entries：

- `MessageEntry`
- `LeafEntry`
- `ModelChangeEntry`
- `CompactionEntry`
- 等等

### Metadata

用于管理和展示 session 的索引信息。

例如：

- id
- path
- cwd
- model
- provider_name
- title
- created_at
- updated_at

这些存储在：

```text
index.jsonl
```

所以：

```text
session transcript = 具体对话内容
session metadata   = 方便查找和展示这段对话的卡片信息
```

## 3. 为什么 SessionManager 在 tau_coding

`tau_agent` 只应该知道：

```text
append-only entries
SessionStorage
SessionState replay
```

它不应该知道：

- 用户 home 在哪里
- session id 怎么生成
- index.jsonl 放在哪里
- TUI 如何列 session
- CLI 如何 `tau sessions`
- resume 时 provider/model 怎么选

这些都是 coding-agent 应用层行为。

所以 `SessionManager` 放在：

```text
tau_coding
```

而不是：

```text
tau_agent
```

## 4. SessionRecordModel：JSON 可序列化模型

源码：

```python
class SessionRecordModel(BaseModel):
    """JSON-serializable coding-session metadata."""

    model_config = ConfigDict(extra="ignore")

    id: str
    path: str
    cwd: str
    model: str
    provider_name: str | None = None
    title: str | None = None
    created_at: float
    updated_at: float
```

它继承自 Pydantic 的 `BaseModel`。

这个类主要用于：

```text
index.jsonl 读写
```

因为 JSON 里没有 `Path` 对象，所以：

```python
path: str
cwd: str
```

都用字符串。

## 5. ConfigDict(extra="ignore")

源码：

```python
model_config = ConfigDict(extra="ignore")
```

意思是：

如果 JSON 里有当前模型没声明的额外字段，忽略它们。

例如 index 里有：

```json
{"id":"s1","path":"...","cwd":"...","model":"fake","unknown":"x"}
```

`unknown` 不会让解析失败。

为什么这样做？

因为 metadata schema 以后可能扩展。

旧代码读到新字段时，最好不要直接崩。

测试：

```python
test_session_manager_ignores_extra_index_metadata
```

验证了额外 metadata 不会破坏读取。

## 6. CodingSessionRecord：Python 内部记录

源码：

```python
@dataclass(frozen=True, slots=True)
class CodingSessionRecord:
    """Metadata for one durable coding session."""

    id: str
    path: Path
    cwd: Path
    model: str
    title: str | None
    created_at: float
    updated_at: float
    provider_name: str | None = None
```

这是 Tau 代码内部使用的 session metadata。

和 `SessionRecordModel` 不同：

```python
path: Path
cwd: Path
```

在 Python 里用 `Path` 更方便。

所以有两个转换方法：

```python
from_model()
to_model()
```

## 7. from_model() 和 to_model()

`from_model()`：

```python
@classmethod
def from_model(cls, model: SessionRecordModel) -> CodingSessionRecord:
    return cls(
        id=model.id,
        path=Path(model.path),
        cwd=Path(model.cwd),
        ...
    )
```

把 JSON-friendly 的字符串路径转回 `Path`。

`to_model()`：

```python
def to_model(self) -> SessionRecordModel:
    return SessionRecordModel(
        id=self.id,
        path=str(self.path),
        cwd=str(self.cwd),
        ...
    )
```

把 `Path` 转成字符串，方便写入 JSON。

这是一种常见分层：

```text
Pydantic model 负责文件格式
dataclass record 负责业务内部使用
```

## 8. SessionManager 初始化

源码：

```python
class SessionManager:
    """Create, index, list, and resume user-home coding sessions."""

    def __init__(self, paths: TauPaths | None = None) -> None:
        self.paths = paths or TauPaths()
```

默认使用：

```python
TauPaths()
```

也就是：

```text
~/.tau
~/.agents
```

测试里会传：

```python
TauPaths(home=tmp_path / ".tau", agents_home=tmp_path / ".agents")
```

避免污染真实用户目录。

## 9. index_path 和 project_index_path

源码：

```python
@property
def index_path(self) -> Path:
    """Return the legacy global session metadata index path."""
    return self.paths.sessions_dir / "index.jsonl"

def project_index_path(self, cwd: Path) -> Path:
    """Return the session metadata index path for a project cwd."""
    return self.paths.project_session_dir(cwd) / "index.jsonl"
```

有两个 index 概念：

### legacy global index

```text
~/.tau/sessions/index.jsonl
```

这是兼容旧实现。

### project index

```text
~/.tau/sessions/<project-slug-hash>/index.jsonl
```

这是当前主要使用的位置。

每个项目有自己的 index。

这让按 cwd 列出 sessions 更自然。

## 10. create_session()

源码：

```python
def create_session(...):
    record = self.prepare_session(...)
    self.index_session(record)
    return record
```

它做两步：

1. 准备 session record
2. 写入 index

这表示 session 创建后立刻可被：

```python
manager.list_sessions()
manager.get_session(record.id)
```

查到。

测试：

```python
test_session_manager_creates_and_lists_sessions
```

验证：

- record path 在 `~/.tau/sessions/<project>/`
- `index.jsonl` 存在
- 全局 `~/.tau/sessions/index.jsonl` 不存在
- `get_session(record.id)` 能找到
- `list_sessions(cwd)` 能找到

## 11. prepare_session()

源码：

```python
def prepare_session(...):
    now = time()
    resolved_cwd = cwd.resolve()
    record_id = session_id or uuid4().hex
    path = self.paths.project_session_dir(resolved_cwd) / f"{record_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return CodingSessionRecord(...)
```

它只创建 metadata 对象和目录，不写 index。

为什么需要 prepare 而不是每次都 create？

因为有些 session 只有在第一次真正持久化消息后，才应该出现在 resume 列表里。

例如 TUI 新建 session 后，用户还没发任何消息。

这时可以先：

```python
record = manager.prepare_session(...)
```

等第一次落盘时再 index。

## 12. Python 包：uuid4

源码：

```python
from uuid import uuid4
record_id = session_id or uuid4().hex
```

`uuid4()` 会生成一个随机 UUID。

`.hex` 会返回不带横线的字符串。

例如：

```text
f3d8a82f9d984b5c8a9a2df9d2c1a100
```

如果调用方没有指定 session_id，Tau 就用 uuid 生成一个。

## 13. Python 包：time()

源码：

```python
from time import time
now = time()
```

`time()` 返回 Unix timestamp，类型是 float。

例如：

```text
1780000000.123
```

它表示从 1970-01-01 UTC 到现在的秒数。

`created_at` 和 `updated_at` 都用这个。

优点是：

- 容易排序
- 容易存成 JSON number
- 跨平台简单

## 14. index_session()

源码：

```python
def index_session(self, record: CodingSessionRecord) -> CodingSessionRecord:
    self._upsert(record)
    return record
```

它把 prepared record 写入 index。

`upsert` 是 update + insert 的缩写：

- 如果 id 不存在，就插入
- 如果 id 已存在，就替换

## 15. _upsert()

源码：

```python
def _upsert(self, record: CodingSessionRecord) -> None:
    path = self.project_index_path(record.cwd)
    records = [item for item in self._read_index(path) if item.id != record.id]
    records.append(record)
    self._write_index(path, records)
```

它先读当前项目 index。

然后过滤掉同 id 的旧 record。

再 append 新 record。

最后写回 index。

这样保证同一个 session id 只有一条最新记录。

## 16. _write_index()

源码：

```python
content = "\n".join(record.to_model().model_dump_json() for record in records)
if content:
    content += "\n"
path.write_text(content, encoding="utf-8")
```

index 文件也是 JSONL。

一行一个 session metadata JSON。

例如：

```json
{"id":"session-1","path":"/.../session-1.jsonl","cwd":"/repo","model":"fake","created_at":1.0,"updated_at":2.0}
```

为什么用 JSONL？

因为 session transcript 已经是 JSONL。

metadata index 用 JSONL 也方便追加/读取/调试。

当前 `_write_index()` 是整体重写 index，不是 append-only。

因为 metadata index 是一个可更新索引，不是审计日志。

## 17. _read_index()

源码：

```python
def _read_index(self, path: Path) -> list[CodingSessionRecord]:
    if not path.exists():
        return []

    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        model = SessionRecordModel.model_validate_json(stripped)
        records.append(CodingSessionRecord.from_model(model))
    return records
```

逻辑：

1. index 文件不存在，返回空 list
2. 按行读取
3. 跳过空行
4. 用 Pydantic 解析 JSON
5. 转成 `CodingSessionRecord`

这里的：

```python
model_validate_json(...)
```

是 Pydantic 从 JSON 字符串解析模型的方法。

## 18. list_sessions()

源码：

```python
def list_sessions(self, cwd: Path | None = None) -> list[CodingSessionRecord]:
    records = self._read_project_records(cwd) if cwd is not None else self._read_all_records()
    return sorted(records, key=lambda record: record.updated_at, reverse=True)
```

如果传了 cwd：

```python
manager.list_sessions(cwd)
```

只列这个项目的 session。

如果没传：

```python
manager.list_sessions()
```

聚合所有项目。

最后按 `updated_at` 倒序排序。

也就是最新使用的 session 排在前面。

## 19. Python 知识：sorted(key=..., reverse=True)

```python
sorted(records, key=lambda record: record.updated_at, reverse=True)
```

表示：

- 按 `record.updated_at` 排序
- `reverse=True` 表示从大到小

所以最近更新的 session 在前。

这符合 session picker 的体验：

```text
最近用过的会话优先显示。
```

## 20. get_session()

源码：

```python
def get_session(self, session_id: str) -> CodingSessionRecord | None:
    for record in self._read_all_records():
        if record.id == session_id:
            return record
    return None
```

它按 id 查找 session。

找不到返回：

```python
None
```

这比抛异常更适合 manager 底层 API。

上层可以决定怎么处理：

- CLI 显示 unknown session
- TUI 通知用户
- `CodingSession.resume()` 抛 `ValueError`

## 21. latest_session_for_cwd()

源码：

```python
def latest_session_for_cwd(self, cwd: Path) -> CodingSessionRecord | None:
    records = self.list_sessions(cwd)
    return records[0] if records else None
```

它返回某个项目最近更新的 session。

当前 TUI 启动逻辑里已经有后续阶段的 provider/model selection 逻辑会用到类似能力。

Phase 14 时主要理解：

```text
SessionManager 可以按项目找到最近 session。
```

## 22. get_or_create_default_session()

源码：

```python
def get_or_create_default_session(...):
    resolved_cwd = cwd.resolve()
    project_hash = self.paths.project_session_dir(resolved_cwd).name
    session_id = f"default-{project_hash}"
    existing = self.get_session(session_id)
    if existing is not None:
        return existing
    ...
```

它是为了兼容早期 TUI 默认 session 行为。

默认 session id 形如：

```text
default-repos-my-project-a1b2c3
```

文件名仍是：

```text
default.jsonl
```

测试：

```python
test_session_manager_gets_or_creates_default_session
```

验证同一个 cwd 第二次调用会返回同一个 record。

## 23. touch_session()

源码：

```python
def touch_session(
    self,
    session_id: str,
    *,
    model: str | None = None,
    provider_name: str | None = None,
    title: str | None = None,
) -> CodingSessionRecord | None:
```

它更新 session metadata：

- `updated_at` 改成当前时间
- model 可更新
- provider_name 可更新
- title 可更新

如果 session 不存在，返回：

```python
None
```

`CodingSession` 在持久化消息后会调用它，让 resume 列表能按最近使用排序。

## 24. CodingSession 如何 touch manager

`src/tau_coding/session.py` 里：

```python
async def _refresh_persisted_state(...):
    entries = await self._read_session_entries()
    self._state = SessionState.from_entries(entries)
    if self._config.session_id is not None and self._config.session_manager is not None:
        self._config.session_manager.touch_session(
            self._config.session_id,
            model=self.model,
            provider_name=self.provider_name,
        )
```

这意味着：

每次 session 持久化新消息并刷新 durable state 后，会顺手更新 metadata 的 `updated_at`。

测试：

```python
test_session_touches_session_manager_after_persisting_messages
```

验证 prompt 后 manager record 会被 touch。

## 25. pending session 第一次持久化后再 index

`CodingSession` 还有一段：

```python
async def _ensure_session_initialized(self) -> None:
    ...
    if self._config.index_on_first_persist:
        self._index_current_session()
```

`new_session()` 会用：

```python
manager.prepare_session(...)
index_on_first_persist=True
```

这表示：

新 session 一开始是 pending/unindexed。

用户第一次真正发送消息、写入 session 文件时，才加入 index。

这样可以避免 resume 列表里出现大量空 session。

## 26. CodingSession.resume()

源码主线：

```python
async def resume(self, session_id: str) -> str:
    manager = self._config.session_manager
    if manager is None:
        raise ValueError("Session manager is not available")
    record = manager.get_session(session_id)
    if record is None:
        raise ValueError(f"Unknown session: {session_id}")
    ...
    replacement = await type(self).load(
        CodingSessionConfig(
            provider=self._harness.config.provider,
            model=record.model or self.model,
            cwd=record.cwd,
            storage=jsonl_session_storage(record.path),
            session_id=record.id,
            session_manager=manager,
            ...
        )
    )
```

它不是简单改几个字段。

它会根据目标 record 重新 load 一个 `CodingSession`。

然后把当前对象内部字段替换成新 session 的字段。

这样 resume 后：

- cwd 变了
- storage 变了
- messages 变了
- skills/context 也按新 cwd 重新加载
- provider/model metadata 也跟随 record

## 27. 为什么 resume 要重建 session

因为 session 不是只有 transcript。

一个 session 还包括：

- cwd
- storage path
- system prompt
- tools
- resources
- provider/model
- thinking level
- command registry
- context files

如果只替换 `messages`，会漏掉很多环境状态。

所以当前设计是：

```text
找到 record
用 record 创建新的 CodingSessionConfig
调用 CodingSession.load()
把 replacement 的内部状态迁移过来
```

这比手动 patch 一堆字段更稳。

## 28. CodingSession.new_session()

`new_session()` 用于 TUI 里 `/new`。

源码主线：

```python
record = manager.prepare_session(
    cwd=self.cwd,
    model=model,
    provider_name=provider_name,
)
replacement = await type(self).load(
    replace(
        self._config,
        model=record.model or model,
        cwd=record.cwd,
        storage=jsonl_session_storage(record.path),
        session_id=record.id,
        index_on_first_persist=True,
    )
)
```

注意它用的是：

```python
prepare_session()
```

不是：

```python
create_session()
```

原因前面说过：

新 session 只有第一次持久化后才 index。

测试：

```python
test_session_new_session_is_indexed_after_first_message
```

验证 pending session 在第一条消息后才进入列表。

## 29. CLI 如何列 sessions

`tau sessions` 会调用：

```python
render_session_list(SessionManager().list_sessions())
```

测试：

```python
test_sessions_command_lists_indexed_sessions
```

验证输出里有：

```text
session-1
Test session
```

如果没有 session：

```python
test_sessions_command_handles_empty_index
```

验证输出：

```text
No sessions found.
```

## 30. TUI 如何接入 resume/new

TUI 中 `/resume <session-id>` 会走 command result：

```python
if command.resume_session_id is not None:
    await self._resume_session(command.resume_session_id)
```

`_resume_session()`：

```python
resume_message = await self.session.resume(session_id)
self.state.clear()
self.state.set_skills(self.session.skills)
self.state.load_messages(self.session.messages)
self._notify(resume_message)
```

这说明 resume 后，TUI 会清掉旧 visible state，再从新 session messages 重新加载。

`/new` 类似：

```python
await new_session()
self.state.clear()
self.state.set_skills(self.session.skills)
self.state.load_messages(self.session.messages)
```

## 31. tests/test_session_manager.py 怎么读

这个测试文件是 Phase 14 最核心的。

重点看：

- `test_session_manager_creates_and_lists_sessions`
- `test_session_manager_prepares_unindexed_session`
- `test_session_manager_filters_sessions_by_project_cwd`
- `test_session_manager_returns_latest_session_for_cwd`
- `test_session_manager_gets_or_creates_default_session`
- `test_session_manager_touch_updates_metadata`
- `test_session_manager_sorts_newest_updated_first`

它们覆盖：

```text
create / prepare / index / list / get / latest / touch / sort
```

这就是 manager 的完整基本能力。

## 32. tests/test_coding_session.py 的 Phase 14 重点

重点测试：

```text
test_session_touches_session_manager_after_persisting_messages
test_session_resumes_indexed_session
test_session_resume_preserves_shell_command_prefix
test_session_new_session_uses_default_provider_model
test_session_new_session_is_indexed_after_first_message
test_session_resume_uses_target_session_provider_model
test_session_context_usage_recalculates_after_resume
```

这些测试说明：

`SessionManager` 不是孤立的。

它已经和 `CodingSession` 的运行、resume、新 session、provider/model metadata 连接起来。

## 33. 初学者容易误解的点

### 误解 1：SessionManager 保存聊天内容

不是。

聊天内容仍然在 session JSONL transcript 里。

SessionManager 管的是 metadata index。

### 误解 2：prepare_session() 和 create_session() 一样

不一样。

`prepare_session()` 只准备 record，不写 index。

`create_session()` 会写 index。

### 误解 3：resume 只是换 messages

不是。

resume 会重新 `CodingSession.load()`，因为 cwd、storage、resources、model/provider 都可能变化。

### 误解 4：所有新 session 都应该立刻出现在列表

不一定。

TUI 的 pending new session 只有第一次持久化消息后才 index，避免空 session 污染列表。

## 34. Phase 14 用一句话总结

Phase 14 的价值是：在 `tau_coding` 中加入 `SessionManager` 和 `CodingSessionRecord`，把用户 home 下的 JSONL transcript 组织成可索引、可列出、可恢复、可更新 metadata 的 session 记录，并让 `CodingSession`、CLI 和 TUI 都能围绕 session id 工作，为 `/resume`、session picker、export 和后续 command registry 打基础。

## 35. 我的问题与推荐回答

问题：为什么 Tau 需要 `SessionManager` 的 metadata index，而不是直接扫描 `~/.tau/sessions/**/*.jsonl` 来恢复 session？

我的推荐回答：

因为 JSONL transcript 主要保存对话树和状态变化，不适合每次都完整扫描来得到用户界面需要的摘要信息。`SessionManager` 的 index record 直接保存 `id`、`path`、`cwd`、`model`、`provider_name`、`title`、`created_at`、`updated_at`，所以 CLI/TUI 可以快速列出、排序和按 id 查找 session。transcript 和 metadata 分开后，`tau_agent` 仍只关心 append-only session storage，`tau_coding` 则负责用户级 session 管理和 resume 体验。
