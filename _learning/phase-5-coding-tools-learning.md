# Phase 5 学习笔记：Built-in Coding Tools

对应架构文档：`dev-notes/architecture/phase-5-coding-tools.md`

对应源码：

- `src/tau_coding/tools.py`
- `tests/test_coding_tools.py`
- `src/tau_coding/__init__.py`

前置阶段：

- Phase 1：定义抽象工具类型 `AgentTool`、`AgentToolResult`
- Phase 3：`run_agent_loop()` 知道如何执行 `AgentTool`
- Phase 4：`AgentHarnessConfig` 可以接收工具列表

## 1. 这一阶段到底在做什么

Phase 5 第一次给 Tau 加入真实 coding agent 工具。

前面几阶段只有抽象：

```text
AgentTool:
  name
  description
  input_schema
  executor
```

Phase 5 开始提供具体工具：

- `read`：读取文件
- `write`：写入文件
- `edit`：精确文本替换
- `bash`：执行 shell 命令

这些工具都定义在：

```text
src/tau_coding/tools.py
```

一句话总结：Phase 5 把本地文件系统和 shell 能力包装成 `AgentTool`，让 Phase 3 的 agent loop 可以调用它们。

## 2. 为什么工具放在 `tau_coding`，不是 `tau_agent`

这是这一阶段最重要的架构边界。

`tau_agent` 是可复用 agent 大脑，它只知道：

```text
有一个 AgentTool 可以执行
执行后会返回 AgentToolResult
```

但它不应该知道：

- 文件路径如何解析
- 是否允许读写本地文件
- bash 命令怎么执行
- 超时后怎么杀进程
- 文件编辑怎么保留换行符和 BOM

这些都是 coding-agent 环境能力，所以放在 `tau_coding`。

边界是：

```text
tau_agent:
  knows how to execute an AgentTool

tau_coding:
  provides read/write/edit/bash tools for local coding work
```

这样以后如果有人想复用 `tau_agent` 做非 coding agent，也不会被本地文件系统和 shell 行为绑住。

## 3. `tools.py` 顶部导入怎么看

源码开头：

```python
import asyncio
import difflib
import json
import mimetypes
import os
import signal
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic
from typing import Any
```

这些基本都是 Python 标准库。

### 3.1 `asyncio`

用于异步执行。

这里主要用在：

- `asyncio.Lock()`：文件写入/编辑锁
- `asyncio.create_subprocess_shell()`：异步启动 shell 命令
- `asyncio.wait()`：等待命令完成、超时或取消
- `asyncio.create_task()`：创建后台任务
- `asyncio.sleep()`：轮询取消信号

### 3.2 `difflib`

用于生成文本 diff。

`edit` 工具修改文件后，会生成：

- `ndiff` 风格 diff
- unified patch
- first changed line

### 3.3 `json`

用于解析 edit 工具的兼容输入。

当前 edit 工具支持：

```python
"edits": "[{\"oldText\":\"a\",\"newText\":\"b\"}]"
```

这种 JSON 字符串形式，会用 `json.loads()` 转成 list。

### 3.4 `mimetypes`

用于根据文件名推测 MIME 类型。

read 工具会识别：

```python
{"image/jpeg", "image/png", "image/gif", "image/webp"}
```

如果是支持的图片，就不按文本读，而是返回 base64 metadata。

### 3.5 `os` 和 `signal`

用于 shell 进程控制。

bash 工具在 POSIX 系统上会启动新 session：

```python
start_new_session=True
```

超时或取消时用：

```python
os.killpg(process.pid, signal.SIGKILL)
```

杀掉整个进程组，避免 shell 子进程残留。

### 3.6 `tempfile`

用于写临时文件。

当 bash 输出太长被截断时，完整输出会写入临时 log 文件。

### 3.7 `Path`

`pathlib.Path` 是现代 Python 处理路径的推荐方式。

比字符串路径更清晰：

```python
path.exists()
path.is_dir()
path.parent.mkdir(...)
path.read_text(...)
path.write_text(...)
```

### 3.8 `monotonic`

用于计算命令耗时。

它比普通时间更适合做耗时测量，因为不会受系统时间调整影响。

## 4. 常量

源码：

```python
DEFAULT_MAX_OUTPUT_BYTES = 50 * 1024
DEFAULT_MAX_OUTPUT_LINES = 2_000
SUPPORTED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
UTF8_BOM = "\ufeff"
```

含义：

- 单次工具输出最多 50KB
- 单次工具输出最多 2000 行
- read 工具支持几种图片 MIME 类型
- `UTF8_BOM` 用于 edit 工具保留 UTF-8 BOM

### 4.1 为什么要限制输出

Agent 工具结果会进入 transcript。

如果 read 或 bash 一次返回几 MB 文本，会让模型上下文爆掉，也会让 UI 很难处理。

所以工具要做截断，并给 continuation hint。

## 5. `ToolInputError`

源码：

```python
class ToolInputError(ValueError):
    """Raised when a tool receives invalid structured arguments."""
```

这是工具参数错误。

它继承 `ValueError`，表示“值不合法”。

比如：

- `path` 不是字符串
- `limit` 小于 1
- edit 的 `oldText` 找不到
- bash 的 `timeout` 小于等于 0

这些错误会被 Phase 3 的 `_execute_tool()` 捕获，转换成失败的 `AgentToolResult`。

## 6. `TruncationResult`

源码：

```python
@dataclass(frozen=True, slots=True)
class TruncationResult:
    content: str
    truncated: bool
    truncated_by: str | None
    total_lines: int
    total_bytes: int
    output_lines: int
    output_bytes: int
    last_line_partial: bool
    first_line_exceeds_limit: bool
    max_lines: int
    max_bytes: int

    def to_json(self) -> dict[str, JSONValue]:
        return asdict(self)
```

它描述输出截断情况。

字段解释：

- `content`：实际返回给模型/用户的内容
- `truncated`：是否截断
- `truncated_by`：因为行数还是字节数截断
- `total_lines`：原始总行数
- `total_bytes`：原始总字节数
- `output_lines`：返回了多少行
- `output_bytes`：返回了多少字节
- `last_line_partial`：尾部截断时是否只返回了某行的一部分
- `first_line_exceeds_limit`：第一行是否就超过大小限制

### 6.1 `asdict(self)`

`asdict()` 是 dataclasses 提供的函数。

它可以把 dataclass 实例转成普通 dict。

这里用于把截断信息放进 `AgentToolResult.data`。

## 7. `ToolDefinition`

源码：

```python
@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    prompt_snippet: str
    prompt_guidelines: tuple[str, ...]
    input_schema: Mapping[str, JSONValue]
    executor: ToolExecutor

    def to_agent_tool(self) -> AgentTool:
        return AgentTool(...)
```

Phase 1 的 `AgentTool` 是 provider-neutral 的最小工具类型。

Phase 5 又加了更丰富的 `ToolDefinition`。

区别是：

```text
ToolDefinition:
  更完整，包含 prompt_snippet 和 prompt_guidelines，适合构建系统提示词

AgentTool:
  更小，agent loop 和 provider 只需要 name/description/schema/executor
```

所以每个工具都有两层 factory：

```python
create_read_tool_definition()
create_read_tool()
```

`create_read_tool()` 只是：

```python
return create_read_tool_definition(cwd=cwd).to_agent_tool()
```

## 8. `create_coding_tools()`

源码：

```python
def create_coding_tools(
    *,
    cwd: str | Path | None = None,
    shell_command_prefix: str | None = None,
) -> list[AgentTool]:
    root = Path.cwd() if cwd is None else Path(cwd)
    return [
        create_read_tool(cwd=root),
        create_write_tool(cwd=root),
        create_edit_tool(cwd=root),
        create_bash_tool(cwd=root, shell_command_prefix=shell_command_prefix),
    ]
```

这是创建默认工具组的入口。

返回顺序固定：

```text
read, write, edit, bash
```

测试里验证：

```python
assert [tool.name for tool in tools] == ["read", "write", "edit", "bash"]
```

### 8.1 `cwd` 的作用

工具使用相对路径时，会基于 `cwd` 解析。

例如：

```python
tools = create_coding_tools(cwd="/tmp/project")
```

模型调用：

```json
{"path": "README.md"}
```

实际路径是：

```text
/tmp/project/README.md
```

## 9. read 工具

创建入口：

```python
create_read_tool_definition()
create_read_tool()
```

read 工具做几件事：

1. 校验 `path`
2. 校验 `offset` 和 `limit`
3. 检查文件是否存在、是否目录
4. 如果是支持的图片，返回 base64 metadata
5. 如果是文本，按 UTF-8 读取
6. 根据 offset/limit 截取行
7. 再做最大行数/字节数截断
8. 返回 `AgentToolResult`

### 9.1 read 输入 schema

源码里 schema 是：

```python
{
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "offset": {"type": "integer"},
        "limit": {"type": "integer"},
    },
    "required": ["path"],
}
```

测试验证了 `offset` 和 `limit` 是 integer。

### 9.2 offset 是 1-indexed

架构文档写明：`offset` 是从 1 开始的行号。

源码：

```python
start_line = 0 if offset is None or offset == 0 else offset - 1
```

也就是说：

- `offset=None`：从第一行开始
- `offset=0`：也从第一行开始
- `offset=1`：第一行
- `offset=2`：第二行

测试里：

```python
result = await tool.execute({"path": "notes.txt", "offset": 2, "limit": 1})
assert result.content.startswith("two")
```

### 9.3 read 的 continuation hint

如果只读了一部分，会追加提示：

```text
[2 more lines in file. Use offset=3 to continue.]
```

这让模型知道下一次可以用什么 offset 继续读。

### 9.4 图片处理

源码：

```python
mime_type = _detect_supported_image_mime_type(path)
if mime_type is not None:
    data = path.read_bytes()
    return AgentToolResult(
        content=f"Read image file [{mime_type}]",
        data={
            "path": str(path),
            "mime_type": mime_type,
            "bytes": len(data),
            "image_base64": _base64_text(data),
        },
    )
```

图片不按 UTF-8 文本读取。

而是读取 bytes，并转成 base64 字符串放在 data 里。

## 10. write 工具

创建入口：

```python
create_write_tool_definition()
create_write_tool()
```

write 工具做几件事：

1. 校验 `path` 是字符串
2. 校验 `content` 是字符串
3. 解析路径
4. 获取文件锁
5. 创建父目录
6. 写入完整内容

核心源码：

```python
async with _file_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
```

### 10.1 为什么要文件锁

如果两个工具同时写同一个文件，内容可能交错。

所以 `_file_lock(path)` 对同一路径做序列化。

注意这是当前 Python 进程内的锁，不是跨进程全局锁。

### 10.2 `mkdir(parents=True, exist_ok=True)`

表示：

- `parents=True`：父目录不存在时一起创建
- `exist_ok=True`：目录已存在时不报错

测试里：

```python
await tool.execute({"path": "nested/file.txt", "content": "hello"})
```

即使 `nested/` 不存在，也会创建。

## 11. edit 工具

创建入口：

```python
create_edit_tool_definition()
create_edit_tool()
```

edit 是 Phase 5 最复杂的文件工具。

它不是“按行号编辑”，而是“精确文本替换”：

```json
{
  "path": "file.txt",
  "edits": [
    {"oldText": "alpha", "newText": "one"},
    {"oldText": "gamma", "newText": "three"}
  ]
}
```

### 11.1 edit 的关键规则

源码和文档强调：

- 每个 `oldText` 不能为空
- 每个 `oldText` 必须在原文件中精确匹配
- 每个 `oldText` 必须只出现一次
- 多个 edits 不能重叠
- 先全部校验成功，再写文件
- 任意一个 edit 失败，文件保持不变
- 保留 UTF-8 BOM
- 保留原文件主导换行符
- 返回 diff、patch、first_changed_line

### 11.2 为什么要求 oldText 唯一

如果文件里有：

```text
repeat
repeat
```

模型说：

```json
{"oldText": "repeat", "newText": "once"}
```

这到底改第一处还是第二处？

为了避免误改，工具直接报错：

```text
Found 2 occurrences ...
```

要求模型提供更多上下文，让 `oldText` 唯一。

### 11.3 失败时不写文件

测试里：

```python
edits = [
    {"oldText": "alpha", "newText": "one"},
    {"oldText": "missing", "newText": "nope"},
]
```

第二个找不到。

结果是抛错，并且文件仍然保持原样。

这是因为工具先在内存里调用：

```python
apply_edits_to_normalized_content(...)
```

等所有校验和替换都成功，才：

```python
path.write_text(final_content, encoding="utf-8")
```

### 11.4 为什么要 normalize line endings

不同系统换行不同：

- Linux/macOS 常见：`\n`
- Windows 常见：`\r\n`

源码先把文本转成 LF：

```python
normalized = normalize_to_lf(content)
```

匹配和替换都在 LF 上做。

最后再恢复原来的主导换行：

```python
final_content = bom + restore_line_endings(new_content, original_ending)
```

这样模型不用太纠结 CRLF，但文件格式能尽量保持。

### 11.5 为什么从后往前应用 edits

源码：

```python
for start, end, new_text in sorted(matches, reverse=True):
    new_content = f"{new_content[:start]}{new_text}{new_content[end:]}"
```

如果从前往后替换，前面的替换可能改变后面文本的位置。

从后往前替换可以避免前面的字符长度变化影响后面的 start/end。

## 12. bash 工具

创建入口：

```python
create_bash_tool_definition()
create_bash_tool()
```

bash 工具做几件事：

1. 校验 `command` 是字符串
2. 可选加 `shell_command_prefix`
3. 校验 timeout
4. 异步启动 shell 进程
5. 合并 stdout 和 stderr
6. 等待完成、超时或取消
7. 必要时杀进程组
8. 对输出做 tail 截断
9. 返回 exit_code、duration、timeout/cancel metadata

### 12.1 为什么 bash 输出用 tail 截断

read 工具通常返回文件开头，所以用 `truncate_head()`。

bash 命令输出通常最后几行最重要，比如测试结果、错误堆栈结尾。

所以 bash 用：

```python
truncate_tail(output)
```

返回尾部。

### 12.2 `create_subprocess_shell`

源码：

```python
process = await asyncio.create_subprocess_shell(
    shell_command,
    cwd=root,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.STDOUT,
    start_new_session=True,
    executable="bash" if prefix else None,
)
```

含义：

- `shell_command`：要执行的命令
- `cwd=root`：工作目录
- `stdout=PIPE`：捕获标准输出
- `stderr=STDOUT`：把 stderr 合并到 stdout
- `start_new_session=True`：POSIX 上创建新 session，方便杀整个进程组
- `executable="bash"`：有 prefix 时明确用 bash

### 12.3 timeout 和取消

核心在：

```python
_communicate_with_cancellation(...)
```

它同时等待：

- 进程正常结束
- timeout 到期
- cancellation token 变成 cancelled

如果 timeout 或 cancel 发生，就调用：

```python
_kill_process_tree(process)
```

测试里覆盖：

- `sleep 1` + `timeout=0.01` 会超时
- 后台子进程也会被杀掉
- cancellation token 取消后也会杀子进程

### 12.4 shell_command_prefix

有些 shell 环境需要先设置别名或初始化。

源码支持：

```python
shell_command_prefix="shopt -s expand_aliases\nalias greet='printf hi'"
```

最终命令会变成：

```text
shopt -s expand_aliases
alias greet='printf hi'
greet
```

测试里验证 `greet` 可以输出 alias 内容。

## 13. 公共参数解析函数

### 13.1 `_str_arg`

```python
def _str_arg(arguments, name):
    value = arguments.get(name)
    if not isinstance(value, str):
        raise ToolInputError(f"{name} must be a string")
    return value
```

读取字符串参数。

### 13.2 `_path_arg`

```python
path = Path(value).expanduser()
if not path.is_absolute():
    path = cwd / path
```

把字符串路径转成 `Path`。

如果是相对路径，就基于 `cwd` 解析。

### 13.3 `_optional_int_arg` 和 `_optional_float_arg`

读取可选数字参数。

如果参数不存在，返回 None。

如果类型不对，抛 `ToolInputError`。

## 14. 截断函数：`truncate_head()` 和 `truncate_tail()`

### 14.1 `truncate_head()`

用于 read 工具。

保留开头内容。

### 14.2 `truncate_tail()`

用于 bash 工具。

保留结尾内容。

### 14.3 为什么同时限制行数和字节数

只限制行数不够。

一行可能非常长。

只限制字节也不够。

几千行短文本也会让输出难读。

所以两个都限制：

```python
DEFAULT_MAX_OUTPUT_LINES = 2_000
DEFAULT_MAX_OUTPUT_BYTES = 50 * 1024
```

## 15. 文件锁：`_file_lock()`

源码：

```python
_file_locks: dict[Path, asyncio.Lock] = {}

class _FileLockContext:
    async def __aenter__(self) -> None:
        lock = _file_locks.setdefault(self._path, asyncio.Lock())
        self._lock = lock
        await lock.acquire()

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        if self._lock is not None:
            self._lock.release()
```

这是一个异步上下文管理器。

用法：

```python
async with _file_lock(path):
    ...
```

进入时获取锁。

离开时释放锁。

这样同一个进程里，对同一路径的 write/edit 不会同时进行。

## 16. `src/tau_coding/__init__.py`

Phase 5 的工具也从 `tau_coding` 包顶层导出。

所以外部可以写：

```python
from tau_coding import create_coding_tools
```

而不必写：

```python
from tau_coding.tools import create_coding_tools
```

`__all__` 里也包含：

- `ToolDefinition`
- `create_read_tool`
- `create_write_tool`
- `create_edit_tool`
- `create_bash_tool`
- `create_coding_tools`

## 17. tests/test_coding_tools.py 怎么读

这份测试是 Phase 5 最好的入口。

### 17.1 默认工具注册

```python
test_create_coding_tools_returns_initial_tool_set
```

验证默认工具顺序是：

```text
read, write, edit, bash
```

### 17.2 prompt metadata

```python
test_tool_definitions_expose_pi_style_prompt_metadata
```

验证 `ToolDefinition` 包含 prompt snippet 和 guidelines。

### 17.3 read

```python
test_read_tool_reads_file_with_offset_and_limit
test_read_tool_treats_zero_offset_as_start_of_file
```

验证 offset/limit 行切片和 continuation hint。

### 17.4 write

```python
test_write_tool_creates_parent_directories
```

验证父目录不存在时自动创建。

### 17.5 edit

```python
test_edit_tool_applies_multiple_exact_replacements
test_edit_tool_rolls_back_when_any_edit_fails
test_edit_tool_requires_unique_matches
```

验证多处替换、失败回滚、唯一匹配。

### 17.6 bash

```python
test_bash_tool_captures_stdout_and_exit_code
test_bash_tool_reports_timeout
test_bash_tool_timeout_kills_shell_children
test_bash_tool_cancellation_kills_shell_children
```

验证输出捕获、超时、杀子进程、取消。

## 18. Phase 5 的典型使用方式

```python
from tau_agent import AgentHarness, AgentHarnessConfig
from tau_ai import OpenAICompatibleProvider
from tau_coding import create_coding_tools

tools = create_coding_tools(cwd="/path/to/project")

harness = AgentHarness(
    AgentHarnessConfig(
        provider=provider,
        model="...",
        system="You are Tau.",
        tools=tools,
    )
)
```

当模型返回：

```python
ToolCall(name="read", arguments={"path": "README.md"})
```

Phase 3 的 loop 会找到 `read` 这个 `AgentTool`，执行它，然后把结果写成 `ToolResultMessage`。

## 19. 小白必须分清的几组概念

### 19.1 `ToolDefinition` 不是 `AgentTool`

`ToolDefinition` 更完整，用于工具文档和 prompt 构建。

`AgentTool` 是 agent loop 执行工具所需的最小结构。

### 19.2 `read` 不等于 shell 的 `cat`

read 工具有 offset/limit、截断、图片识别、metadata。

它比直接 `cat` 更适合 agent 上下文。

### 19.3 `write` 是完整覆盖

write 不是局部修改。

它会把整个文件内容写成给定 `content`。

局部修改应该用 edit。

### 19.4 `edit` 是精确替换，不是模糊搜索

`oldText` 必须精确、唯一、不重叠。

这是为了避免误改文件。

### 19.5 `bash` 可以失败但仍返回结构化结果

bash 命令 exit code 非 0、timeout 或 cancelled 时：

```python
result.ok is False
```

但仍然会返回 output、exit_code、duration、timeout metadata。

## 20. Phase 5 里用到的 Python 语法和包

### 20.1 异步上下文管理器

```python
async with _file_lock(path):
    ...
```

进入时 await 获取锁，退出时释放锁。

### 20.2 `asyncio.create_subprocess_shell`

异步执行 shell 命令并捕获输出。

### 20.3 `asyncio.wait(..., return_when=asyncio.FIRST_COMPLETED)`

等待多个任务中任意一个先完成。

这里用于同时等待：

- 命令完成
- 取消信号
- timeout

### 20.4 `pathlib.Path`

面向对象地操作路径和文件。

### 20.5 `difflib.ndiff` 和 `difflib.unified_diff`

生成文件修改前后的差异。

### 20.6 `dataclasses.asdict`

把 dataclass 转成 dict，方便放入 JSON-like `data`。

### 20.7 `mimetypes.guess_type`

根据文件扩展名推测 MIME 类型。

### 20.8 `tempfile.NamedTemporaryFile(delete=False)`

创建临时文件，并且关闭后不删除。

bash 输出太长时，完整输出会保存在这里。

## 21. 运行测试

Phase 5 最相关测试：

```text
tests/test_coding_tools.py
```

运行：

```bash
uv run pytest tests/test_coding_tools.py
```

这组测试覆盖：

- 默认工具集合
- prompt metadata
- read offset/limit
- write 创建父目录
- edit 多处替换
- edit 失败回滚
- edit 唯一匹配要求
- bash stdout/exit code
- bash shell prefix
- bash timeout
- bash 取消和子进程清理

## 22. 用一句话总结 Phase 5

Phase 5 的价值是：在不污染 `tau_agent` 核心大脑的前提下，把本地 coding agent 需要的文件读取、文件写入、精确编辑和 shell 执行能力封装成标准 `AgentTool`，让已有的 agent loop/harness 能直接调用真实环境能力。

## 23. 我的问题与推荐回答

问题：为什么 `edit` 工具要求 `oldText` 必须精确且唯一匹配，而不是找到第一个就替换？

我的推荐回答：

因为 coding agent 修改文件时最怕误改。模型给出的 `oldText` 如果在文件里出现多次，工具无法知道模型真正想改哪一处；如果直接替换第一个，很可能破坏错误位置。要求精确且唯一，可以迫使模型提供足够上下文，让修改位置明确。再加上“全部校验成功后才写文件”，可以保证某个 edit 失败时不会留下半改状态。
