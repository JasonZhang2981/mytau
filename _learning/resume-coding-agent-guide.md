# Tau Coding Agent Resume Guide

这份文档把 Tau 整理成一个可以写进简历、也能在面试中讲清楚的
coding agent 开发项目。写简历时重点不是把它说成普通聊天工具，而是说清楚：
你理解并实现了一个 coding agent 从模型流式输出、工具调用、会话持久化到终端
交互界面的核心工程链路。

## 项目定位

推荐定位：

```text
Tau: Python 实现的 Pi-style coding agent harness
```

更适合简历的一句话：

```text
基于 Python 构建一个面向代码任务的 coding agent 框架，拆分模型接入、Agent
循环、工具调用、会话持久化、上下文压缩和 TUI 前端层，形成可测试、可扩展的
终端智能编码助手原型。
```

不要只写成：

```text
做了一个调用大模型的聊天机器人。
```

这个项目真正有价值的地方在于：它把 coding agent 的内部结构拆开了，而不是只
把一个 prompt 发给模型。

## 简历主标题

可以使用下面任意一个标题：

- `Tau: Python Coding Agent Harness`
- `Python 终端 Coding Agent 框架`
- `Pi-style Coding Agent 学习型实现`
- `基于 Python 的智能编码 Agent 原型系统`

如果这是你基于开源项目学习和二次开发的经历，建议标题里保留边界：

```text
Python Coding Agent Harness 二次实现与架构学习项目
```

如果你确实主导实现了仓库中的主要代码，可以写得更主动：

```text
Python Coding Agent Harness 设计与实现
```

## 技术栈写法

推荐写法：

```text
Python 3.14, asyncio, Pydantic, Typer, Rich, Textual, httpx, pytest, mypy, ruff, uv
```

按能力归类时可以这样写：

- Agent 架构：provider-neutral event stream, agent loop, tool calling, session tree
- 模型接入：OpenAI-compatible provider, Anthropic provider, OpenAI Codex subscription provider
- 终端应用：Typer CLI, Rich renderer, Textual TUI
- 工程质量：pytest, strict mypy, ruff, uv, MkDocs

## 简历 Bullet 模板

### 推荐版本

适合放在项目经历里，控制在 4-6 条：

```text
- 设计并实现 Python 版 coding agent harness，将系统拆分为 tau_ai、tau_agent、
  tau_coding 三层，分别负责模型流式接入、可复用 Agent 循环/工具事件、以及
  CLI/TUI/资源加载等应用层能力，避免核心 Agent 依赖具体前端框架。
- 实现 provider-neutral AgentEvent 事件模型和异步 agent loop，支持模型文本流、
  thinking/reasoning delta、工具调用、工具结果回写、重试事件、取消和多轮执行。
- 构建 read/write/edit/bash 等本地编码工具，使用结构化 JSON schema 和统一
  AgentToolResult 返回工具执行结果，并在工具层处理路径解析、输出截断、编辑
  diff 和错误信息。
- 实现 CodingSession 会话层，将 AgentHarness 与项目 cwd、系统提示词、技能、
  prompt 模板、slash command、会话树和 JSONL 持久化组合起来，支持恢复、分支、
  导出和上下文压缩。
- 基于 Textual 构建交互式终端 TUI，并通过 TuiEventAdapter 消费 AgentEvent，
  实现模型/会话选择、命令补全、工具结果展示、thinking token 开关、排队追问和
  取消等 coding agent 交互能力。
- 为核心循环、工具、会话、资源发现、TUI adapter、provider 配置和上下文管理
  编写单元测试，并使用 uv run pytest、ruff、mypy 维护可验证的工程质量。
```

### 更短版本

适合简历空间不够时：

```text
- 构建 Python 终端 coding agent 框架，拆分模型 provider、Agent loop、工具调用、
  会话持久化和 TUI 前端层，保持核心 harness 与 CLI/Textual 解耦。
- 实现 provider-neutral 事件流和工具执行链路，支持流式回复、tool call/result、
  retry、cancellation、queued follow-up、session replay 和 context compaction。
- 基于 Textual/Typer/Rich 完成交互式 TUI 与 print-mode CLI，并配套 pytest、
  strict mypy、ruff 测试与质量检查。
```

### 英文简历版本

```text
- Built a Python Pi-style coding agent harness with clear separation between
  model streaming, reusable agent loop/tool orchestration, coding-session
  resources, and terminal UI frontends.
- Implemented provider-neutral event streaming for assistant deltas, reasoning
  deltas, retries, tool calls, tool results, cancellation, queued follow-ups,
  session replay, and context compaction.
- Developed local coding tools, durable JSONL session trees, slash commands,
  resource discovery, and a Textual-based TUI while keeping the reusable agent
  core independent from Rich/Textual/CLI policy.
```

## 项目讲解主线

面试时建议按这条线讲：

```text
普通 LLM CLI
    ↓
需要工具调用和多轮状态
    ↓
抽出 provider-neutral messages/tools/events
    ↓
实现纯 agent loop
    ↓
用 AgentHarness 管 transcript、取消、排队消息
    ↓
用 CodingSession 加入 cwd、工具、资源、命令、会话持久化
    ↓
让 CLI/Rich/Textual 只消费事件，不污染核心 agent 包
```

一句话版本：

```text
我没有把大模型输出直接绑死在终端 UI 上，而是先定义 provider-neutral 的消息、
工具和事件协议，再用 AgentHarness 管理可复用的 agent 状态，最后由 CodingSession
和 TUI adapter 把它接到真实的本地编码环境中。
```

## 代码证据

写简历前，建议你能说出这些文件分别证明什么：

| 能力 | 代码/文档位置 | 可以怎么讲 |
| --- | --- | --- |
| 分层架构 | `docs/01-architecture.md`, `docs/00-roadmap.md` | 三层职责和依赖方向 |
| Agent loop | `src/tau_agent/loop.py` | 模型事件、工具执行、多轮循环 |
| Harness | `src/tau_agent/harness.py` | transcript、取消、steering/follow-up queue |
| 事件协议 | `src/tau_agent/events.py` | UI 和核心之间的稳定契约 |
| 工具抽象 | `src/tau_agent/tools.py` | provider-neutral tool schema/result |
| 本地编码工具 | `src/tau_coding/tools.py` | read/write/edit/bash、截断、错误处理 |
| CodingSession | `src/tau_coding/session.py` | 会话、命令、资源、上下文压缩的组合层 |
| TUI adapter | `src/tau_coding/tui/adapter.py` | Textual 只消费事件，不进入核心层 |
| 上下文发现 | `src/tau_coding/context.py` | 自动发现 AGENTS.md 等项目指令 |
| 质量验证 | `tests/` | 核心模块有可重复测试 |

## 不要过度包装

这些边界要主动说清楚，反而更可信：

- Tau 是 Pi-style coding agent harness 的 Python 实现，不是 Pi 的逐行移植。
- `tau_agent` 是可复用 Agent 核心，但当前重点仍是本地终端 coding agent，不是
  企业级云端多租户平台。
- Phase 21 extensions 在 roadmap 中明确 deferred，所以不要写“已完成插件生态”。
- 可以写 provider 配置和多 provider 支持，但不要写成已经覆盖所有大模型平台。
- 如果你只是基于项目学习和改造，不要写“独立从零完成全部架构”，可以写
  “围绕开源 coding agent 架构进行分层阅读、二次实现和功能扩展”。

## 简单指导

根据岗位选择强调点：

- 投 AI Agent / LLM 应用岗位：强调 agent loop、tool calling、context compaction、
  provider-neutral event stream。
- 投 Python 后端岗位：强调分层架构、异步流式处理、Pydantic schema、持久化、
  测试和类型检查。
- 投工具链 / 开发者工具岗位：强调 CLI/TUI、slash commands、session resume、
  resource discovery、local coding tools。
- 投前端偏终端交互岗位：强调 Textual adapter、状态管理、命令补全、会话选择、
  工具结果展示。

简历里不要塞太多功能名。最好的结构是：

```text
项目目标 + 架构拆分 + 你实现的关键链路 + 可验证结果
```

例如：

```text
我负责将 coding agent 拆成 provider、agent loop、coding session 和 TUI adapter
几层，并围绕工具调用、会话恢复和上下文管理补齐测试。
```

## 面试常见问题

### 为什么要拆 `tau_ai`、`tau_agent`、`tau_coding`？

因为 coding agent 同时包含模型接入、agent 决策循环、本地编码环境和用户界面。
如果都写在 CLI 里，后续换 provider、换 TUI、加 session 或测试 agent loop 都会
互相影响。三层拆开后，`tau_agent` 可以只关心消息、工具、事件和循环，`tau_coding`
再处理 cwd、资源、命令、持久化和 UI 策略。

### AgentHarness 和 CodingSession 有什么区别？

`AgentHarness` 是可复用 brain，负责 transcript、agent loop、取消和排队消息。
它不知道本地文件放在哪里，也不知道 slash command 或 Textual。`CodingSession`
是 coding-agent environment，负责把 harness 接入真实项目目录、编码工具、系统
提示词、资源发现、session storage、命令和上下文压缩。

### 为什么用事件流？

事件流是核心和 UI 的契约。模型可能流式输出文本、发出 thinking delta、请求工具、
产生 retry、被取消或结束一轮。把这些都转成 provider-neutral `AgentEvent` 后，
print renderer、JSON renderer、transcript renderer 和 Textual TUI 都可以复用同一套
核心行为。

### 这个项目和普通 ChatGPT API 封装有什么区别？

普通封装通常是 prompt in / text out。Tau 关注的是 coding agent 的完整运行时：
多轮 agent loop、工具调用、工具结果回填、会话树、资源发现、上下文压缩、命令系统
和 TUI 事件消费。这些才是 coding agent 工程复杂度主要来源。

### 你会怎么继续扩展？

优先做 roadmap 中 deferred 的 Phase 21 extensions：让外部扩展贡献工具、命令、
prompt snippets 和事件订阅。但要保持原则：扩展只能接入 `tau_coding` 的应用层，
不能让 `tau_agent` 依赖具体插件加载、Textual 或本地配置策略。

## 可替换成果指标

如果你后续实际验证了数字，可以把下面占位符替换掉：

```text
- 覆盖 [N]+ 个核心模块测试，围绕 agent loop、tool execution、session replay、
  context compaction 和 TUI adapter 建立回归测试。
- 支持 [M] 类 provider 配置和 [K] 个本地 coding tools，完成从 prompt 到 tool
  result 再到 session persistence 的闭环。
- 将核心 agent 包与 UI/app policy 解耦，使同一事件流可被 print/json/transcript/TUI
  多种前端复用。
```

不要编造没有验证过的量化指标。没有数字时，宁愿写“建立回归测试”“支持多种渲染
路径”“保持核心层与 UI 解耦”，也不要写虚假的性能提升。

## 最终推荐简历片段

如果只能放一段，建议用这一版：

```text
Python Coding Agent Harness | Python, asyncio, Pydantic, Typer, Rich, Textual
- 构建 Pi-style coding agent 框架，将模型 provider、Agent loop、工具调用、
  coding session 和 TUI 前端分层解耦，保持核心 agent harness 不依赖 CLI/Rich/Textual。
- 实现 provider-neutral 事件流与异步 agent loop，支持流式回复、thinking delta、
  tool call/result、retry、cancellation、queued follow-up 和多轮执行。
- 构建本地编码工具、JSONL session tree、slash command、资源发现、上下文压缩和
  Textual TUI，并通过 pytest、strict mypy、ruff 覆盖核心行为。
```
