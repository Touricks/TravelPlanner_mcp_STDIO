# L0: 基础概念 — 数据从哪来，到哪去

> 本级目标：建立数据架构的心智模型，不运行任何写命令。

## 概念 1: 数据流方向（单向）

```
SQLite (travel.db)  ──→  CLI 命令  ──→  Notion 页面
     唯一真相源            操作接口         展示层（只读）
```

- 所有数据修改通过 CLI 命令，**不要**直接写 SQL
- Notion 是"发布目标"，永远不从 Notion 拉数据回 SQLite
- 这个单向性是刻意的——防止两边数据不一致

## 概念 2: 核心表关系

```
places (地点档案)          itinerary_items (行程安排)
┌─────────────────┐       ┌──────────────────────┐
│ id: 21          │       │ id: 21               │
│ name_en: 水族馆  │◄──────│ place_id: 21         │
│ style: nature   │  1:N  │ date: 2026-04-18     │
│ city: Monterey  │       │ time_start: 14:30    │
│ address: ...    │       │ decision: pending    │
└─────────────────┘       └──────────────────────┘
```

- **places** = 地点本身（存在一次，不管去几次）
- **itinerary_items** = 某次到访安排（「几号几点去哪」）
- 一个 place 可以有 0 个 item（还没排入行程）或多个 item（多次到访）

## 概念 3: 日编号与分类

**日编号** 从不存储在表里，是视图动态计算的：
```sql
CAST(julianday(date) - julianday(trip.start_date) + 1 AS INTEGER)
-- 例: 2026-04-18 - 2026-04-17 + 1 = Day 2
```

**Style 分类**（6 种）：
| style | 含义 | Notion 映射 |
|-------|------|------------|
| nature | 自然景观 | Attractions |
| tech | 科技 | Attractions |
| culture | 人文 | Attractions |
| landmark | 地标 | Attractions |
| food | 餐饮 | Food |
| coffee | 咖啡 | Food |

**双语要求**：每个地点必须有 `name_en` + `name_cn`（中英文名称）。

## 概念 4: sync_status 生命周期

```
pending ──→ synced ──→ modified ──→ synced ──→ ...
 从没推过    推送成功    推后又改了    再次推送
```

- CLI 写入后，sync_status 自动变为 `modified`（如果之前是 synced）
- 这靠数据库触发器实现，不需要手动管理

## 概念 5: 软删除

两种"删除"，效果不同：

| 操作 | 做了什么 | place 还在吗 | 可恢复吗 |
|------|---------|-------------|---------|
| `trip drop` | 拒绝某次安排 (decision→rejected) | 在 | 是（confirm 即可） |
| `trip remove-place` | 软删地点 (deleted_at 打时间戳) | 不可见 | 数据库层面在 |

> 详细表结构参考 `design/core/db/schema-reference.md`

---

## 练习：读懂数据库

运行这 3 条 SQL（只读，零风险），回答问题：

```bash
# 问题 1: 数据库里有多少个地点？
sqlite3 assets/database/travel.db "SELECT count(*) FROM places;"

# 问题 2: Day 5 去的是哪个城市/区域？
sqlite3 assets/database/travel.db "SELECT day_num, group_region FROM day_summary WHERE day_num = 5;"

# 问题 3: 哪个 style 的地点最多？food 有几个？
sqlite3 assets/database/travel.db "SELECT style, count(*) as cnt FROM places GROUP BY style ORDER BY cnt DESC;"
```

## 通关标准

- [ ] 能画出 SQLite → CLI → Notion 的数据流箭头
- [ ] 能解释 places 和 itinerary_items 的 1:N 关系
- [ ] 知道 day_num 是怎么算出来的（不是存的）
- [ ] 能说出 drop 和 remove-place 的区别
