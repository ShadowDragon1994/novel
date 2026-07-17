# OpenClaw 第四周代码审查报告

> 审查对象：`C:\Users\xingyu.zhang\Documents\novel\openclaw`
> 审查时间：2026-05-23
> 审查依据：第四周计划 `docs/week4_plan.md`
> 实际测试数：**118 个**（计划 112-117）
> 测试结果：**118/118 通过，✅ ruff clean，✅ mypy clean**
> 审查轮次：初评（116 tests）→ 修复 3 处问题 → 终审（118 tests）
> 上轮基数：92

---

## 一、总体结论：阶段 4 全部达标 ✅

| 维度 | 目标 | 实际 |
|---|---|---|
| SettingsExtractor | 校对稿 → 提取 4 类实体 → 写入 Guard 表 | ✅ 千问提取 JSON + 匹配已有/新建 + GuardLayer + 实体 ID + PermissionError 容错 |
| PublishScheduler | 23:00 + 08:10 双批发布计划 | ✅ 高密度槽位（3h）+ 6h 间隔 + jitter + 日更上限 |
| ProductionScanner 集成 | Pipeline 完成后自动提取 | ✅ `_run_one` 链入，失败不阻塞审核 |
| 测试数量 | 112-117 | ✅ **118** |
| ruff / mypy | 通过 | ✅ mypy 24 文件无问题 |

> **终审确认：** 初评发现 3 处问题（6.1/6.2/6.3）已全部修复并通过新增测试验证。

---

## 二、新增文件审阅

### 2.1 `business/settings_extractor.py` — 信息提取器

**核心设计：**

```
extract_after_final(chapter_id):
  1. _already_extracted() → 幂等跳过
  2. _load_proofread() → 读校对稿
  3. _render_extract_prompt() → Jinja2 渲染提取模板
  4. llm_client.generate() → 千问返回 JSON
  5. _parse_entities() → JSON 解析（兼容裸 JSON + Markdown 包裹）
  6. 逐实体遍历（try/except PermissionError 包裹每个实体）：
     - _find_match() → 名称/别名匹配已有记录
     - 已有：_append_suggestion() → GuardLayer.write(追加字段)
     - 新：_create_pending(item, index) → 生成 entity_id + create_record(来源=AI)
  7. 写运行日志表
```

**亮点：**
- `_parse_entities` 双层提取：优先 `json.loads`，失败时正则捞 `{.*}` — 容错 LLM 在 JSON 外包裹 Markdown 解释文字
- `_already_extracted` 幂等检查：运行日志表里查 `extract-{chapter_id}` 是否已成功
- `_find_match` 别名匹配：查 `人物别名` 字段，处理同一角色有多个称谓的场景
- `ENTITY_SPECS` 数据驱动：新增 `id_field` / `id_prefix`，4 类实体完整配置集中定义
- `_entity_id()`：生成 `{prefix}-{safe_chapter_id}-{index:02d}` 格式唯一 ID，自动 strip 特殊字符
- **终审修复：** PermissionError 被 try/except 包裹（`extract_after_final:111,119-120`），单条被拒不影响后续实体

### 2.2 `business/publish_scheduler.py` — 发布排期器

**核心设计：**

```
generate_daily_plan():
  1. _target_date(now) → 23:00 后排次日，08:10 排当日
  2. _pending_chapters() → 扫描 待人工审核 + 未排期 + 无计划时间
  3. _scheduled_chapters() + _used_slots_by_novel() → 读已排期情况
  4. _time_slots() → 生成 08:30-22:00 内 3h 间隔时间槽（5 个）
  5. 按小说分组 → 逐章 _pick_slot()（jitter 后比对 6h 间隔）→ _assign()
```

**亮点：**
- `_target_date` 实现了双批次语义：晚班（≥23:00）排次日，早班（08:10）排当日
- `_pending_chapters` 三条件过滤：生产状态 + 发布状态 + 计划发布时间为空
- **终审修复：** `_time_slots` 改用 `slot_gap_hours=3`（独立于 `min_gap_hours`），生成 5 个槽位（08:30/11:30/14:30/17:30/20:30），支持最多 3 章/本/天
- **终审修复：** `_pick_slot` 先计算 `candidate = slot + jitter`，再以 candidate 与已用时间比对间隔，消除原始槽位偏移导致的假冲突
- **终审修复：** `_jitter` 简化为固定偏移 `int(jitter[0])`（5min），确定性且语义明确

### 2.3 `business/production_scanner.py` — SettingsExtractor 集成

```python
async def _run_one(self, record, semaphore):
    ...
    await self.guard_layer.write(..., {"生产状态": "待人工审核"})
    if self.settings_extractor:           # ← 可选注入
        try:
            await self.settings_extractor.extract_after_final(chapter_id)
        except Exception as exc:
            await self.guard_layer.write(  # ← 失败不阻塞
                ..., {"错误信息": f"SettingsExtractor failed: {exc}"}
            )
```

- SettingsExtractor 注入为可选参数，不传时行为不变（向后兼容）
- try/except 包裹确保提取失败不影响已完成的审核流程
- 错误信息写回章节任务表，方便排查

### 2.4 `prompts/extract.j2` — 提取 Prompt 模板

12 行严格 JSON Schema 约束，要求 LLM 只输出 JSON 对象、无内容时返回空数组、字段用中文。

### 2.5 测试文件

| 文件 | 测试数 | 覆盖 |
|---|---|---|
| `test_settings_extractor.py` | **10** | JSON 解析/新人物/已有追加/幂等跳过/新设定/新势力/伏笔/空结果/嵌入文本解析/无校对稿跳过 |
| `test_publish_scheduler.py` | **12** | 扫描过滤/日更上限/6h 间隔/时间窗口/发布状态/空列表/已排满/早班新章节/晚班次日/打散/防重复/时间槽范围 |
| `test_production_scanner.py` | +2（现 12） | extractor 调用/extractor 失败不阻塞 |

---

## 三、测试分布（92 → 116 → 118）

| 文件 | 阶段 3 终审 | 阶段 4 初评 | 阶段 4 终审 | 后审新增 |
|---|---|---|---|---|
| `test_settings_extractor.py` | 0 | 10 | **11** | +1（PermissionError 容错后继续） |
| `test_publish_scheduler.py` | 0 | 12 | **13** | +1（日更 3 章密集槽位） |
| `test_production_scanner.py` | 10 | 12 | 12 | — |
| 其余文件 | 82 | 82 | 82 | — |

**合计：118 passed in 7.25s**

---

## 四、code quality

| 检查 | 结果 |
|---|---|
| `python -m pytest tests/ -v` | ✅ 118 passed |
| `mypy core/ business/ llm/ main.py` | ✅ Success: no issues in 24 files |

---

## 五、与第四周计划对照

| 计划任务 | 交付 |
|---|---|
| 🔵 Day 1-3: SettingsExtractor 实现 | ✅ 提取 4 类实体 + 匹配已有 + GuardLayer 写入 + 幂等 |
| 🔵 Day 4-6: PublishScheduler 实现 | ✅ 双批次 + 时间槽 + 6h 间隔 + jitter + 日更上限 |
| 🔵 Day 7: 测试加固 + 联调 | ✅ **26 个新增测试，118 个总计** |
| 🔵 ProductionScanner 集成 | ✅ Pipeline 完成后自动触发 SettingsExtractor |
| 🔵 优化：PublishScheduler 替换 main.py stub | ✅ `add_job_if_implemented` 自动生效 |

---

## 六、初评问题 → 终审修复验证（3 处全部 FIXED ✅）

| # | 问题 | 修复 | 验证 |
|---|---|---|---|
| 6.1 | `_append_suggestion` PermissionError 未捕获 | `extract_after_final:111,119-120` — try/except PermissionError 包裹每个实体 | `test_extract_permission_error_skips_one_entity_and_continues` |
| 6.2 | 时间槽容量仅 2 章/本/天 | `_time_slots` 改用 `slot_gap_hours=3`（5 槽位）；`_pick_slot` 用 jittered candidate 比对 | `test_scheduler_can_assign_three_chapters_with_dense_slots` |
| 6.3 | 新建实体缺少唯一 ID | `EntitySpec` 加 `id_field`/`id_prefix`；新增 `_entity_id()` 方法 | 3 个测试验证 char/setting/faction/foreshadow ID |

### 修复详情

**6.1 PermissionError 容错**

```python
# settings_extractor.py:109-120
for index, item in enumerate(entities.get(key, []), start=1):
    try:
        existing = await self._find_match(spec, item)
        if existing:
            await self._append_suggestion(spec, existing, item)
        else:
            await self._create_pending(spec, item, index)
    except PermissionError:
        continue  # 核心记录不可写，跳过该条继续处理后续实体
```

测试 `test_extract_permission_error_skips_one_entity_and_continues`：FakeGuard 对人物写入抛 PermissionError，设定写入正常完成。验证 `result.updated=0, result.created=1`，世界观设定表的记录被创建。

**6.2 高密度槽位**

```python
# publish_scheduler.py:112 — 槽位间隔独立于发布时间间隔
min_gap = max(int(config.get("slot_gap_hours", 3)), 1)  # 3h → 5 个槽

# publish_scheduler.py:124-126 — 以 jittered 时间比对
candidate = slot + self._jitter(slot)
if all(abs(candidate - used_slot) >= min_gap for used_slot in used):
    return candidate
```

测试 `test_scheduler_can_assign_three_chapters_with_dense_slots`：日更上限=3，验证 3 章全部排入，且两两间距 ≥6h。

**6.3 实体 ID 生成**

```python
# settings_extractor.py:199-201
def _entity_id(self, spec: EntitySpec, index: int) -> str:
    safe_chapter_id = re.sub(r"[^0-9A-Za-z_-]+", "-", self._current_chapter_id).strip("-") or "chapter"
    return f"{spec.id_prefix}-{safe_chapter_id}-{index:02d}"
```

格式：`char-c1-01` / `setting-c1-01` / `faction-c1-01` / `foreshadow-c1-01`。特殊字符自动替换为连字符。

---

## 七、阶段 5 可以开工 ✅

阶段 4 终审通过，3 处初评问题全部修复。剩余的 2 个业务模块（阶段 5）：

| 模块 | 计划阶段 | 当前状态 |
|---|---|---|
| `PublishScanner` | 阶段 5 | `NotImplementedError` |
| `Watchdog` | 阶段 5 | `NotImplementedError` |

需要我给出阶段 5 的开发计划吗？
