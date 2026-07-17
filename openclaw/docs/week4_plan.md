# OpenClaw 第四周开发计划：SettingsExtractor + PublishScheduler

> 前置条件：阶段 3 已通过终审（92 个测试全绿 + ruff/mypy 双清 + main.py 可运行）
> 目标：章节生成后自动提取世界观信息 + 每日定时生成发布计划
> 周期：7 天

---

## 一、本周总览

```
Day 1-3   SettingsExtractor          → 校对稿 → 提取人物/设定/势力/伏笔
Day 4-6   PublishScheduler           → 23:00 + 08:10 两批发布计划
Day 7     测试加固 + 联调验收         → 92 → 目标 115+
```

---

## 二、Day 1-3：SettingsExtractor

### 2.1 背景

**现状：** `business/settings_extractor.py` 是 stub，`extract_after_final()` raise NotImplementedError。

**业务链路（SOP §8）：** 章节校对完成后 → 用千问模型分析校对稿 → 提取：
- 新角色（人物名称、性格、角色定位、关系）
- 新设定（世界观规则、冲突处理原则）
- 势力变动（势力出镜、资源变化、掌权人变更）
- 伏笔（铺设的可回收线索）

写入规则（依赖 GuardLayer）：
- 全新人物/设定/势力 → 创建记录，`来源状态=AI自动新增`，`确认状态=待确认`
- 已有匹配项 → 追加到"人物变化记录/设定冲突"字段，不覆盖已确认的核心字段
- 核心人物/设定不允许直接改写，只追加 `AI建议更新-待确认`

### 2.2 实现

| # | 任务 | 文件 | 验收 |
|---|---|---|---|
| 1 | 实现 `SettingsExtractor.__init__`：注入 `feishu_client` + `guard_layer` + LLM 客户端（千问） | `business/settings_extractor.py` | DI 完成 |
| 2 | 实现 `extract_after_final(chapter_id)`：读取校对稿 → 调 LLM 提取结构化 JSON → 解析为 4 类实体 | 同上 | 返回 4 个列表 |
| 3 | 实现实体匹配逻辑：名称/别名模糊匹配已有记录 | 同上 | 同名字段匹配，别名走 LINESTRING LIKE |
| 4 | 实现写入逻辑：新实体 `create_record` + 已有实体通过 GuardLayer 追加建议 | 同上 | 不覆盖核心字段 |
| 5 | 创建提取 prompt 模板 `extract.j2` | `prompts/extract.j2` | 输出 JSON Schema 约束 |
| 6 | 每章最多提取一次：检查确认状态，避免重复抽取 | `business/settings_extractor.py` | 幂等 |

### 2.3 核心代码结构

```python
class SettingsExtractor:
    def __init__(self, feishu_client, guard_layer, llm_client):
        self.feishu_client = feishu_client
        self.guard_layer = guard_layer
        self.llm_client = llm_client  # 千问

    async def extract_after_final(self, chapter_id: str) -> ExtractResult:
        # 1. 读校对稿（正文版本表，版本类型=校对稿）
        proofread = await self._load_proofread(chapter_id)
        # 2. 调 LLM 提取 → JSON
        raw = await self.llm_client.generate(self._render_extract_prompt(proofread))
        entities = self._parse_entities(raw)  # → dict[EntityType, list[dict]]
        # 3. 逐实体匹配 + 写入
        for entity_type, items in entities.items():
            for item in items:
                existing = await self._find_match(entity_type, item)
                if existing:
                    await self._append_suggestion(entity_type, existing, item)
                else:
                    await self._create_pending(entity_type, item)
        return ExtractResult(...)
```

### 2.4 提取目标表

| 表 | 新实体字段 | 已有实体追加字段 |
|---|---|---|
| 人物档案表 | 人物名称、性格、角色定位、关系、来源状态=AI自动新增、确认状态=待确认 | 人物变化记录（追加） |
| 世界观设定表 | 设定名称、设定类型、设定内容、来源状态、确认状态 | 冲突处理原则（追加） |
| 势力组织表 | 势力名称、势力类型、核心资源、来源状态、确认状态 | 势力回写规则（追加） |
| 伏笔追踪表 | 伏笔内容、铺设章节、重要等级、来源状态、确认状态 | 伏笔识别提醒逻辑（追加） |

### 2.5 测试（新增 8-10 个）

| 测试 | 覆盖 |
|---|---|
| `test_extract_parses_json_from_llm` | JSON 解析正常/异常 |
| `test_extract_new_character_creates_pending_record` | 新人物 → create_record |
| `test_extract_existing_character_appends_suggestion` | 已有人物 → 追加变化记录 |
| `test_extract_respects_guard_layer_on_core_record` | 核心人物不被覆盖 |
| `test_extract_skips_if_already_extracted` | 幂等检查 |
| `test_extract_new_setting_creates_pending` | 新设定 |
| `test_extract_new_faction_creates_pending` | 新势力 |
| `test_extract_foreshadow_with_chapter_reference` | 伏笔铺设 |
| `test_extract_empty_result_does_nothing` | LLM 返回空 |

---

## 三、Day 4-6：PublishScheduler

### 3.1 背景

**现状：** `business/publish_scheduler.py` 是 stub，`generate_daily_plan()` raise NotImplementedError。

**业务规则（SOP §7.2）：**
- 两次触发：每晚 23:00（为次日排班）+ 早 08:10（调整早班）
- 时间窗口：08:30-22:00 内分发
- 间隔：同一本小说相邻两章 ≥6h
- 日更量：每本每日最多发布 N 章（从小说总览表读取日更目标）
- 偏移：每本加 0-37min 随机 jitter 避免流量挤兑
- 发布状态：`未排期 → 待发布`

### 3.2 实现

| # | 任务 | 文件 | 验收 |
|---|---|---|---|
| 1 | 实现 `generate_daily_plan()` 主逻辑 | `business/publish_scheduler.py` | 两次调用产生不同的发布计划 |
| 2 | 扫描章节任务表：`生产状态=待人工审核` 且 `发布状态∈{未排期, 待发布}` | 同上 | 按审核时间排序 |
| 3 | 按小说分组，每本读取日更目标和当日已排期数 | 同上 | 不超日更上限 |
| 4 | 时间分配算法：早班（08:30-12:00）+ 下午班（12:00-18:00）+ 晚班（18:00-22:00） | 同上 | 6h 间隔满足 |
| 5 | 每章写入计划发布时间 + 将发布状态改为 `待发布` | 同上 | GuardLayer 允许写入 |
| 6 | 处理边缘：无待发章节、全部排满、跨日 | 同上 | 不抛错，日志记录 |

### 3.3 核心算法

```python
class PublishScheduler:
    def __init__(self, feishu_client, guard_layer):
        self.feishu_client = feishu_client
        self.guard_layer = guard_layer

    async def generate_daily_plan(self) -> ScheduleResult:
        # 1. 扫描待发布章节
        pending = await self._pending_chapters()
        # 2. 按小说分组
        by_novel = self._group_by_novel(pending)
        # 3. 时间槽分配
        slots = self._time_slots()  # → [08:30, 12:40, 16:50, ...]
        assigned = []
        for novel_id, chapters in by_novel.items():
            config = await self._novel_config(novel_id)  # 日更目标、当前存稿
            for chapter in chapters[:config.daily_max]:
                slot = self._pick_slot(slots, config, chapter)
                if not slot:
                    break
                await self._assign(chapter, slot)  # 写计划发布时间 + 发布状态=待发布
                assigned.append(chapter)
        return ScheduleResult(assigned=assigned, skipped=...)

    def _time_slots(self) -> list[datetime]:
        """生成当日 08:30-22:00 内的发布槽位"""
        ...

    def _pick_slot(self, slots, novel_config, chapter) -> datetime | None:
        """选槽：距该小说上次发布时间 ≥6h，加随机 jitter"""
        ...
```

### 3.4 配置补全（config.yaml）

```yaml
publish_window:
  earliest: 08:30
  latest: "22:00"
  min_gap_hours: 6
  jitter_minutes: [5, 15]     # 已有
  evening_batch: 23:00         # 新增
  morning_batch: 08:10         # 新增
```

### 3.5 测试（新增 12-15 个）

| 测试 | 覆盖 |
|---|---|
| `test_scheduler_scans_pending_chapters` | 扫描待人工审核章节 |
| `test_scheduler_respects_daily_max_per_novel` | 单本不超日更上限 |
| `test_scheduler_enforces_6h_gap` | 同一小说相邻章 ≥6h |
| `test_scheduler_distributes_across_time_window` | 章节分布在 08:30-22:00 |
| `test_scheduler_skips_over_limit_chapters` | 第 N+1 章被跳过 |
| `test_scheduler_updates_publish_status` | 发布状态 → 待发布 |
| `test_scheduler_handles_no_pending_chapters` | 空列表不抛错 |
| `test_scheduler_handles_already_fully_scheduled` | 全天已排满 |
| `test_scheduler_morning_batch_only_new_chapters` | 早班只排新进入的章节 |
| `test_scheduler_evening_batch_schedules_next_day` | 23:00 排次日 |
| `test_scheduler_applies_jitter` | 两本不同小说发布时间不同 |
| `test_scheduler_guards_against_duplicate_assignment` | 同章不排两次 |

---

## 四、ProductionScanner 集成 SettingsExtractor

阶段 4 需要把 SettingsExtractor 接到 ProductionScanner 链路中：

```
ProductionScanner._run_one(chapter):
    ...
    await self.guard_layer.write("章节任务表", record_id, {"生产状态": "待人工审核"})
    # ↓ 新增 ↓
    await self.settings_extractor.extract_after_final(chapter_id)
```

| # | 任务 | 文件 |
|---|---|---|
| 1 | `ProductionScanner.__init__` 增加 `settings_extractor` 参数 | `business/production_scanner.py` |
| 2 | `_run_one` 在 GuardLayer.write 之后调用 `extract_after_final` | 同上 |
| 3 | 提取失败不阻塞审核流程（写日志 + 标记错误信息） | 同上 |

---

## 五、阶段 4 优化项

| 优化 | 文件 | 说明 |
|---|---|---|
| `FeishuVersionStore._latest_record` 加 filter | `business/llm_pipeline.py` | `list_records` 传 `filter` 参数按章节ID过滤，避免全量拉取 |
| PublishScheduler 替换 main.py 中 stub | `main.py` | `add_job_if_implemented` 自动生效 |

---

## 六、目录变更

```
openclaw/
├── business/
│   ├── settings_extractor.py    ← 实现（从 stub 到完整）
│   ├── publish_scheduler.py     ← 实现（从 stub 到完整）
│   └── production_scanner.py    ← 集成 SettingsExtractor 调用
├── prompts/
│   └── extract.j2               ← 新增：信息提取 prompt 模板
├── tests/
│   ├── test_settings_extractor.py  ← 新增：8-10 个测试
│   └── test_publish_scheduler.py   ← 新增：12-15 个测试
└── config/
    └── config.yaml              ← publish_window 字段补全
```

---

## 七、第四周结束时的状态

```
✅ SettingsExtractor 完成：校对稿 → 提取 4 类实体 → 写入 Guard 表
✅ PublishScheduler 完成：23:00 + 08:10 两批发布计划
✅ ProductionScanner 集成 SettingsExtractor
✅ 20-25 个新测试（92 → 112-117）
✅ ruff / mypy clean
✅ main.py 三个 job 全部正常调度（ProductionScanner + PublishScheduler ×2）
❌ PublishScanner / Watchdog 留到阶段 5
```

---

## 八、本周测试目标

| 文件 | 本周 | 累计 |
|---|---|---|
| 已有文件 | 92 | 92 |
| `test_settings_extractor.py` | 8-10 | 100-102 |
| `test_publish_scheduler.py` | 12-15 | 112-117 |
| **总计** | **20-25** | **112-117** |
