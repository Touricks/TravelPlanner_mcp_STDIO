# L3: 多步工作流 — QUERY → ASSESS → PROPOSE → EXECUTE → VERIFY

> 本级目标：掌握五步操作模式，学会处理级联影响和标记架构缺口。

## 为什么需要这个模式？

单步写入很简单，但真实需求通常是：
> "把 Day 5 的鼎泰丰换成泰国菜"

这需要：查找旧的 → 评估影响 → 提出方案 → 执行替换 → 验证结果。
如果跳过"查找"直接写，可能改错 item_id。如果跳过"评估"，可能塞进一个地理上不合理的餐厅。

## QAEPV 五步法

### Step 1: QUERY — 查数据库确认

永远不要凭记忆操作。先查：

```bash
sqlite3 assets/database/travel.db \
  "SELECT item_id, day_num, time_start, time_end, name_en, group_region
   FROM v_full_itinerary WHERE name_en LIKE '%Sichuan%';"
```

记下：item_id、day_num、time_start、duration_minutes、group_region

### Step 2: ASSESS — 评估上下文

问自己三个问题：
1. **这天的路线是什么？** 查 `day_summary` 的 `group_region`
2. **前后有什么活动？** 查同天全部 items，看时间冲突
3. **新地点在地理上合理吗？** SF 的餐厅不该放在 LA 日

```bash
sqlite3 assets/database/travel.db \
  "SELECT time_start, time_end, name_en FROM v_full_itinerary
   WHERE day_num = 5 ORDER BY sort_order;"
```

### Step 3: PROPOSE — 说出计划

在执行前先说清楚你要做什么：
> "鼎泰丰在 Day 5 12:00-13:30，90分钟。我打算：
> 1. drop 鼎泰丰 (item #34)
> 2. add-place Jitlada Thai
> 3. schedule 到 Day 5 12:00, 90分钟
> 这样不影响 Day 5 其他活动的时间。"

### Step 4: EXECUTE — 按顺序执行

**顺序很重要**：先 drop 旧的 → 再 add 新地点 → 再 schedule

```bash
trip drop 34 --reason "换成泰国菜"
trip add-place "Jitlada Thai" --style food --cn "Jitlada泰餐" \
  --city "Los Angeles" --address "5233 W Sunset Blvd, Los Angeles, CA 90027"
trip schedule <new_place_id> --day 5 --time 12:00 --duration 90 --region "Los Angeles"
```

### Step 5: VERIFY — 查看结果

```bash
sqlite3 assets/database/travel.db \
  "SELECT time_start, time_end, name_en, decision
   FROM v_full_itinerary WHERE day_num = 5 ORDER BY sort_order;"
```

确认：旧的不再出现（decision=rejected 的会被视图过滤），新的在 12:00。

---

## 进阶概念

### 级联影响

替换一个活动可能波及其他表：
- **酒店** — 如果改的活动影响了过夜地点（但 CLI 没有 `update-hotel` 命令）
- **预订** — 被 drop 的活动可能有 reservations 记录（但 CLI 没有 `cancel-reservation` 命令）

**怎么办？标记 gap，不要假装问题不存在**：
```bash
# 检查被替换的项目有没有关联预订
sqlite3 assets/database/travel.db \
  "SELECT attraction, cost_per_person FROM reservations
   WHERE attraction LIKE '%Din Tai%';"
```

### 地理推理

通过 `group_region` 检查地理一致性：

```bash
sqlite3 assets/database/travel.db \
  "SELECT day_num, group_region FROM day_summary;"
```

```
Day 1, 9: San Francisco
Day 2:    Highway 1 North
Day 3:    Big Sur & Coast
Day 4:    Central Coast
Day 5:    Los Angeles
Day 6-8:  Sequoia / Yosemite
```

如果用户想把一个 SF 餐厅加到 Day 5（LA），你应该标记这个不一致。

### Gap 标记

这些实体类型目前没有 CLI 写命令，遇到时要告知用户：
- **hotels** → 标记并建议 `design/backlog/hotel-management-cli.md`
- **reservations** → drop 后检查孤儿记录
- **risks** → 只读，从导入获得
- **todos** → 只读，从导入获得

---

## 练习：替换 Day 5 午餐

### 场景

用户说：「Day 5 的鼎泰丰换成 Jitlada Thai（泰国菜）」

### 要求：完整走一遍 QAEPV

1. **QUERY**: 查出 Din Tai Fung 的 item_id
   （提示：item_id = 34, Day 5, 12:00）

2. **ASSESS**: 查 Day 5 完整行程，确认 12:00 前后没有冲突

3. **PROPOSE**: 写出你的替换计划（参考 Step 3 的格式）

4. **EXECUTE**: 依次执行 drop → add-place → schedule

5. **VERIFY**: 查看 Day 5 更新后的行程

6. **思考题**: 检查 reservations 表 —— 鼎泰丰有没有关联的预订记录？
   如果有，你应该怎么处理？

---

## 通关标准

- [ ] 能不看提示独立走完 QAEPV 五步
- [ ] 知道什么时候需要标记 gap（hotels, reservations）
- [ ] 理解 drop + add-place + schedule 的「替换模式」
- [ ] 能用 group_region 检查地理一致性
- [ ] 完成了 Day 5 替换练习
