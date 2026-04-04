# L4: Agent 设计 — 从手动到自动

> 本级目标：理解 agent-prompt-template 的每一段为什么这么写，
> 能独立设计指导 Agent 的 prompt。

## 回顾：你已经学会了

| 层级 | 学到的能力 |
|------|----------|
| L0 | 数据架构（SQLite → Notion 单向流，places/items 分离） |
| L1 | 查询（trip status + 7 个视图） |
| L2 | 写入（add-place, schedule, confirm, drop, reschedule） |
| L3 | 工作流（QAEPV 五步法 + gap 标记 + 地理推理） |

## 模板解剖

打开 `design/core/agent-prompt-template.md`，每一段都对应你学过的内容：

| 模板段落 | 对应层级 | 为什么需要 |
|---------|---------|----------|
| `# Database` | L0 | Agent 需要知道 db 路径和数据架构 |
| `## Read / ## Query` | L1 | Agent 必须先查后改 |
| `## Write (create)` | L2 | 创建命令签名 |
| `## Write (mutate)` | L2 | 修改命令签名 |
| `# Workflow Pattern` | L3 | QAEPV 五步法 |
| `# Rules` | L2+L3 | 写入规则 + gap 标记 |
| `# Architecture Gaps` | L3 | 哪些实体没有写命令 |
| `# Trip Context` | L0 | Day-region 映射 |

**现在你能看懂模板的每一行了。**

## Agent 设计的 4 个原则

### 原则 1: 查询优先

Agent 必须先查后改。为什么？
- item_id 是数字，猜错会改错条目
- 行程可能已经被别的操作改过了
- 模板里的 QUERY 步骤不是建议，是**强制要求**

### 原则 2: 命令示例 > 文字描述

模板不解释"add-place 用于添加地点"，而是直接给完整命令样例：
```bash
trip add-place "Name" --style food --cn "中文名" --city "City" --address "..."
```
LLM 从范例学习比从描述学习更可靠——这叫 **show don't tell**。

### 原则 3: 不编码领域知识

模板不包含：餐厅推荐、驾驶距离、风景评分。
只给 day-region 映射（6 行），其余交给 LLM 的世界知识。

为什么？这些知识 LLM 已经有了。Prompt 只需要提供**工具和操作模式**，
不需要重复 LLM 已经知道的东西。

### 原则 4: 显式标记 Gap

告诉 Agent "这些实体类型没有写命令"比什么都不说好得多：
- 如果不说 → Agent 可能尝试 `trip update-hotel`，报错，用户困惑
- 如果说了 → Agent 主动告知用户"酒店变更需要手动处理"

## Manifest/Sync 概念

### push-notion 三步握手

```
1. CLI 生成 JSON manifest      ← 待推送内容清单
2. Agent 读 manifest，调 MCP    ← 在 Notion 创建/更新页面
3. Agent 调 mark-synced 确认    ← 每条记录标记为 synced
```

### 为什么用 manifest 模式？

- CLI 不能直接调 Notion MCP（MCP 是 Claude Code 插件，CLI 是 Python 脚本）
- Manifest 是**结构化契约**：CLI 产出数据，Agent 负责执行，职责清晰
- 如果中途失败，manifest 里记录了哪些已完成、哪些未完成，可以断点续传

> 详细设计见 `design/core/notion-v2-sync-plan.md`

## 三种使用方式

### 方式 1: 写入 `.claude/rules/`（持久化）

把模板的命令参考和工作流模式写入 `.claude/rules/trip-agent.md`，
所有 Claude Code session 自动加载。

### 方式 2: one-shot 任务提示

```
{模板内容}

# Task
用户想要：把 Day 3 的 Big Sur Bakery 换成 Nepenthe 餐厅
请执行 QUERY → ASSESS → PROPOSE → EXECUTE → VERIFY 工作流。
```

### 方式 3: Agent SDK system prompt

你正在学的 Claude SDK 就是用这种方式——
把模板作为 system prompt，接收用户消息作为 task，
Agent 自主执行 QAEPV 循环。

---

## 练习：角色扮演 Agent

### 场景

用户说：「Day 2 行程太满了（10 个 stops），帮我精简到 6 个，保留最值得去的」

### 要求（先写计划，可选执行）

1. **QUERY**: 写出查询 Day 2 全部 items 的 SQL

2. **ASSESS**: 10 个 stops 里哪些可以 drop？考虑：
   - 哪些是核心景点（不能砍）？
   - 哪些是顺路的咖啡/餐厅（可以砍）？
   - 时间上有没有冲突？

3. **PROPOSE**: 写出保留 6 个、drop 4 个的方案，每个给出理由

4. **EXECUTE**: 列出需要执行的 `trip drop` 命令序列

5. **VERIFY**: 写出验证命令

6. **GAP 检查**: Day 2 的酒店是 Carmel-by-the-Sea，
   drop 的地点有没有关联预订？用什么 SQL 检查？

### 提示

Day 2 当前行程（10 stops）：
```
08:00  Anthropic HQ
09:00  Half Moon Bay
09:30  Verve Coffee (Santa Cruz)
10:00  Computer History Museum
12:00  Stanford University
13:30  Chef Chu's
14:00  Monterey Bay Whale Watch
14:30  Monterey
17:30  Carmel-by-the-Sea
17:30  China Village (Monterey)
```

---

## 通关标准

- [ ] 打开 agent-prompt-template.md，每一段都能对应到 L0-L3 学的内容
- [ ] 能解释为什么模板不包含餐厅推荐或地理知识
- [ ] 理解 manifest/sync 三步握手的设计动机
- [ ] 能写出一个完整的 agent 计划（QAEPV + gap 标记）
- [ ] 知道模板的三种使用方式（rules / one-shot / SDK）
