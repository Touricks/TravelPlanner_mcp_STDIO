# 渐进式学习路径：从 SQLite 到 Agent 工作流

## 学习目标

把 `agent-prompt-template.md` 拆解为 5 个递进层级，每级 15-20 分钟。
完成全部 5 级后，你能独立构建指导 Agent 操作旅行 CLI 的 prompt。

## 路径地图

| 级别 | 主题 | 你会学到 | 风险等级 |
|------|------|----------|----------|
| L0 | 基础概念 | 数据架构、日编号、双语、style 分类 | 只读 |
| L1 | 查询状态 | trip status、sqlite3 视图查询 | 只读 |
| L2 | 单步写入 | add-place、schedule、confirm、drop | 仅创建 |
| L3 | 多步工作流 | QUERY→ASSESS→PROPOSE→EXECUTE→VERIFY | 修改数据 |
| L4 | Agent 设计 | prompt 模板结构、guardrails、manifest/sync | 仅规划 |

## 如何使用

1. 按 L0 → L4 顺序学习，不要跳级
2. 每级末尾有动手练习，使用真实的 `travel.db`
3. 完成练习后对照「通关标准」自评
4. 如果练习改了数据，随时可重置：
   ```bash
   python3 assets/database/seed/import_all.py
   ```

## 参考文档

| 文档 | 用途 |
|------|------|
| `design/core/db/schema-reference.md` | 表结构和视图详情 |
| `.claude/rules/cli-write-layer.md` | CLI 命令速查 |
| `design/core/agent-prompt-template.md` | 最终目标：Agent prompt 模板 |
