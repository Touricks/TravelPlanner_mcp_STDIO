# L2: 单步写入 — 一次改一个东西

> 本级目标：掌握 5 个写命令，理解每个命令对数据库的影响。

## 写之前必读的规则

1. **写命令只接受 ID 或 UUID**，不接受名字（防止 agent 误操作）
2. **每次写入自动记录 audit_log**（不需要手动，service layer 帮你做了）
3. **drop ≠ remove-place**：drop 拒绝某次安排，place 还在；remove-place 软删地点本身

> 完整命令签名见 `.claude/rules/cli-write-layer.md`

## 命令速览

以下所有命令前缀为：
```bash
python3 -m assets.database.cli.trip --db assets/database/travel.db
```

### 1. add-place（新建地点）

```bash
trip add-place "Tartine Bakery" --style food --cn "塔汀面包店" \
  --city "San Francisco" --address "600 Guerrero St, San Francisco, CA 94110"
```

数据库变化：places 表 +1 行，audit_log +1 行
验证：`sqlite3 ... "SELECT id, name_en, style FROM places ORDER BY id DESC LIMIT 1;"`

### 2. schedule（排入行程）

```bash
trip schedule <place_id> --day 9 --time 10:00 --duration 60 --region "San Francisco"
```

- `<place_id>` 是 add-place 返回的数字 ID
- `--day` 是 1-based 日编号（Day 1 = 出发日）
- 数据库变化：itinerary_items +1 行，date 自动从 day 计算

### 3. confirm（确认行程项）

```bash
trip confirm <item_id>
```

- decision: pending → confirmed
- 如果已经是 confirmed，不会报错（no-op）

### 4. drop（放弃行程项）

```bash
trip drop <item_id> --reason "太远了"
```

- decision: pending → rejected
- `--reason` 会追加到 notes 字段（不会覆盖原有内容）
- **place 仍然存在**，可以重新 schedule

### 5. reschedule（改时间/改天）

```bash
trip reschedule <item_id> --day 3 --time 15:00 --duration 120
```

- 至少提供 `--day`、`--time`、`--duration` 之一
- 未指定的字段保持原值
- sort_order 自动重算

---

## 练习：给 Day 9 加一家午餐店

### 背景

Day 9 目前的行程：
```
08:00  Yosemite Morning (镜湖+半穹顶)
15:00  Chinatown San Francisco
15:30  R/SF dim sum (龙凤酒楼)
18:30  Z & Y Restaurant (东来顺)
```

12:00 有一个空档（从 Yosemite 开车回 SF 的时间）。

### 任务

1. **查** Day 9 现有行程，记下所有 item_id：
   ```bash
   sqlite3 assets/database/travel.db \
     "SELECT item_id, time_start, name_en FROM v_full_itinerary WHERE day_num = 9 ORDER BY sort_order;"
   ```

2. **创建**地点：
   ```bash
   trip add-place "Mama's on Washington Square" --style food \
     --cn "华盛顿广场妈妈餐厅" --city "San Francisco" \
     --address "1701 Stockton St, San Francisco, CA 94133"
   ```
   → 记下返回的 place_id

3. **排入行程**：
   ```bash
   trip schedule <place_id> --day 9 --time 12:30 --duration 60 --region "San Francisco"
   ```

4. **确认**这个新 item：
   ```bash
   trip confirm <item_id>
   ```

5. **验证** Day 9 行程（应该多了 12:30 的一条）

6. **查看操作历史**：
   ```bash
   sqlite3 assets/database/travel.db \
     "SELECT action, target_type, actor FROM audit_log ORDER BY created_at DESC LIMIT 5;"
   ```
   → 应该看到 3 条记录：add_place, schedule_visit, confirm

---

## 通关标准

- [ ] 能区分 place_id（地点编号）和 item_id（行程项编号）的用途
- [ ] 知道 add-place 不会自动排入行程（需要单独 schedule）
- [ ] 理解 drop（拒绝安排）和 remove-place（删地点）的区别
- [ ] 能用 audit_log 查看操作历史
- [ ] 完成了 Day 9 加餐厅的练习
