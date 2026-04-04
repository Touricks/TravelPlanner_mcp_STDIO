# L1: 查询状态 — 先看清全局再动手

> 本级目标：掌握两种查询工具，能快速定位任何行程信息。

## 工具 1: trip status（仪表盘）

```bash
python3 -m assets.database.cli.trip --db assets/database/travel.db status
python3 -m assets.database.cli.trip --db assets/database/travel.db status --verbose
```

输出包含：
- **table_counts** — 各表行数（places, itinerary_items, hotels...）
- **sync_pending** — 等待推送 Notion 的实体数
- **alerts** — open_risks / incomplete_todos / unscheduled places
- `--verbose` 额外显示每天的景点明细

## 工具 2: sqlite3 直接查视图

视图是预定义的"快捷查询"，不用自己写 JOIN。

### 关键视图速查表

| 视图 | 用途 | 关键列 |
|------|------|--------|
| `v_full_itinerary` | 完整行程（最常用） | item_id, day_num, time_start, name_en, name_cn, style, decision |
| `day_summary` | 每天概览 | day_num, date, group_region, stop_count, route |
| `v_hotels` | 住宿链 | city, check_in, check_out, nights, day_num_in |
| `v_foods` | 美食清单 | name_en, time_start, city, day_num |
| `open_risks` | 待解决风险 | category, risk, action_required |
| `unscheduled_places` | 未排入行程 | name_en, style, city |
| `incomplete_todos` | 未完成待办 | task, priority, category |

### 常用查询模式

```bash
# 模式 1: 按天查行程
sqlite3 assets/database/travel.db \
  "SELECT time_start, time_end, name_en, name_cn, style
   FROM v_full_itinerary WHERE day_num = 1 ORDER BY sort_order;"

# 模式 2: 按名字搜索（LIKE 模糊匹配）
sqlite3 assets/database/travel.db \
  "SELECT item_id, day_num, time_start, name_en
   FROM v_full_itinerary WHERE name_en LIKE '%Coffee%';"

# 模式 3: 找出超载的天（stop_count > 6）
sqlite3 assets/database/travel.db \
  "SELECT day_num, stop_count, group_region FROM day_summary WHERE stop_count > 6;"

# 模式 4: 查酒店链是否连续
sqlite3 assets/database/travel.db \
  "SELECT city, check_in, check_out, nights FROM v_hotels ORDER BY check_in;"
```

> 完整视图定义见 `design/core/db/schema-reference.md`

---

## 练习：侦查任务

不修改任何数据，回答这 5 个问题（每个用一条 SQL）：

**Q1**: 运行 `trip status` —— 有多少 open risks？多少 unscheduled places？

**Q2**: Day 2 (Highway 1 North) 的第一个 stop 是什么？几点开始？
```bash
sqlite3 assets/database/travel.db \
  "SELECT time_start, name_en FROM v_full_itinerary WHERE day_num = 2 ORDER BY sort_order LIMIT 1;"
```

**Q3**: 所有 coffee 类型的地点有哪些？分布在哪几天？
```bash
sqlite3 assets/database/travel.db \
  "SELECT day_num, name_en, city FROM v_foods WHERE style = 'coffee' ORDER BY day_num;"
```

**Q4**: 哪个酒店住两晚？在哪个城市？

**Q5**: 有没有 unscheduled 的 food 类地点？叫什么名字？
```bash
sqlite3 assets/database/travel.db \
  "SELECT name_en, style, city FROM unscheduled_places WHERE style = 'food';"
```

---

## 通关标准

- [ ] 不用翻文档就能写出 `v_full_itinerary` 的 WHERE day_num = N 查询
- [ ] 知道 `trip status` 和 sqlite3 查询的区别（仪表盘 vs 精确查询）
- [ ] 能看懂 `day_summary` 里的 stop_count 和 group_region 含义
- [ ] 知道至少 4 个视图的名字和用途
