# OpenClaw 第六周开发计划：SOP 全合规收尾

> 前置条件：阶段 5 终审通过（140 测试 + 全部模块实现）
> 目标：修复 SOP 合规偏移项，达到完整验收标准
> 周期：5 天

---

## 一、总览

```
Day 1-2   生产/发布守卫条件补齐   → 10 项 SOP 偏移修复
Day 3-4   SettingsExtractor 分级  → 核心/非核心分路径 + 伏笔回收 + 记忆读取
Day 5     测试 + 全量验收         → 140 → 目标 160+
```

---

## 二、Day 1-2：生产/发布守卫条件补齐

### 2.1 ProductionScanner — 补齐 5 项

```python
# production_scanner.py — _pending_tasks() 重构
PENDING_PRODUCTION_STATUSES = {
    "待生成细纲", "待生成细纲/Pending Outline", "待创作/Pending",
    # 补全中间态（返工流程需要）
    "待生成初稿/Pending Draft", "待一致性检查/Pending Consistency",
    "待辅助检查/Pending Compliance", "待润色/Pending Polish",
    "待校对/Pending Proofread", "返工中/Reworking",
}

async def _pending_tasks(self):
    for record in records:
        fields = record.get("fields", record)
        # 新增 3 项过滤
        if fields.get("内容锁定状态") in {"是", "是/Yes", True}:
            continue
        if int(fields.get("流程重试次数") or 0) >= 3:
            continue
        if int(fields.get("内容返工次数") or 0) >= 3:
            continue
        if fields.get("生产状态") in PENDING_PRODUCTION_STATUSES:
            pending.append(record)
```

```python
# 新增 per_novel 并发限制
async def run_once(self):
    selected = tasks[:self.global_max]
    # per_novel_max 检查：同一小说最多 2 章并发
    ...
```

| # | 修复 | 文件 | 测试 |
|---|------|------|------|
| 1 | 过滤 `内容锁定状态=是` | `production_scanner.py` | `test_scanner_skips_locked_content` |
| 2 | 过滤 `流程重试次数>=3` | 同上 | `test_scanner_skips_max_retries` |
| 3 | 过滤 `内容返工次数>=3` | 同上 | `test_scanner_skips_max_revisions` |
| 4 | 补全 `PENDING_PRODUCTION_STATUSES` (3→9) | 同上 | `@parametrize` 9 个状态 |
| 5 | 实现 `per_novel_max` 并发限制 | 同上 | `test_scanner_respects_per_novel_max` |

### 2.2 PublishScanner — 补齐 6 项

```python
# publish_scanner.py — _ready_chapters() 增加守卫
async def _ready_chapters(self, now):
    for record in records:
        fields = record.get("fields", record)
        novel_id = str(fields.get("小说ID") or "")
        # 新增：检查小说自动发布开关
        if not self._novel_auto_publish_enabled(novel_id):
            continue
        # 新增：检查生产状态=已定稿
        if fields.get("生产状态") not in {"已定稿", "已定稿/Finalized"}:
            continue
        # 新增：检查内容锁定状态=是
        if fields.get("内容锁定状态") not in {"是", "是/Yes", True}:
            continue
        # 新增：检查当前版本不为空
        if not fields.get("当前版本"):
            continue
        # 原有：发布状态 + 计划时间
        if fields.get("发布状态") in READY_PUBLISH_STATUS and planned_at <= now:
            ready.append(record)
```

```python
# 连续失败 3 次 → 账号健康状态=观察
async def _mark_failure(self, record, exc):
    ...
    if attempts >= self.max_attempts:
        await self._set_account_health(account_id, "观察/Under Observation")
```

| # | 修复 | 文件 | 测试 |
|---|------|------|------|
| 6 | 检查 `小说自动发布开关=开启` | `publish_scanner.py` | `test_scanner_skips_when_novel_auto_publish_off` |
| 7 | 检查 `生产状态=已定稿` | 同上 | `test_scanner_skips_non_finalized` |
| 8 | 检查 `内容锁定状态=是` | 同上 | `test_scanner_skips_unlocked_content` |
| 9 | 检查 `当前版本不为空` | 同上 | `test_scanner_skips_empty_version` |
| 10 | 检查 `账号健康状态=正常` | 同上 | `test_scanner_skips_unhealthy_account` |
| 11 | 连续失败 3 次 → 写 `账号健康状态=观察` | 同上 | `test_scanner_sets_account_unhealthy_after_max_failures` |

### 2.3 PublishScheduler — 补齐 4 项

| # | 修复 | 文件 | 测试 |
|---|------|------|------|
| 12 | `READY_PRODUCTION_STATUS` 移除 `待人工审核` | `publish_scheduler.py` | 已有测试自动覆盖 |
| 13 | 排班前检查 `内容锁定状态=是` | 同上 | `test_scheduler_skips_unlocked` |
| 14 | 排班前检查 `当前版本不为空` | 同上 | `test_scheduler_skips_empty_version` |
| 15 | 补充写 `排班批次` + `排班生成时间` | 同上 | `test_scheduler_writes_batch_fields` |

---

## 三、Day 3-4：SettingsExtractor 分级 + 增强

### 3.1 核心/非核心分路径创建

当前：新建实体一律 `来源状态=AI自动新增/AI Auto`，核心记录由 GuardLayer 被动拦截。

修改后：LLM prompt 增加"核心判断"输出字段，SettingsExtractor 根据判断走不同路径：

```python
# extract.j2 增加输出字段
{
  "characters": [{
    "人物名称": "", "性格": "", "角色定位": "",
    "是否核心": "否",  # ← 新增：LLM 自行判断
    ...
  }],
  ...
}
```

```python
# settings_extractor.py — _create_pending 分路径
async def _create_pending(self, spec, item, index):
    is_core = str(item.get("是否核心", "")).startswith("是")
    fields = {...}
    if is_core:
        fields["来源状态"] = "AI建议新增-待确认/AI Pending Confirmation"
        fields["确认状态"] = "待确认/Pending"
        fields["是否核心"] = "是/Yes"
    else:
        fields["来源状态"] = "AI自动新增/AI Auto"
        fields["确认状态"] = "已确认/Confirmed"
        fields["是否核心"] = "否/No"
    await self.feishu_client.create_record(spec.table, fields)
```

### 3.2 读取对象增强

```python
# 新增：读取章节任务卡（获取原始意图对比）
async def _load_chapter_card(self, chapter_id: str) -> dict:
    records = await self.feishu_client.list_records("章节任务表")
    for r in records:
        if r.get("fields", {}).get("章节ID") == chapter_id:
            return r.get("fields", r)
    return {}

# 新增：读取前 10 章短期记忆（获取上下文）
async def _load_recent_memories(self, novel_id: str, limit=10):
    ...
```

### 3.3 伏笔回收检测

```python
# extract.j2 — prompt 增加伏笔回收要求
# "检查本章是否回收（解释/兑现/废弃）了伏笔追踪表中铺设章节 < 本章章号的已有伏笔"
# 设置输出字段: foreshadows_resolved: [{伏笔ID, 回收方式}]
```

### 3.4 任务表

| # | 修复 | 文件 | 测试 |
|---|------|------|------|
| 16 | LLM prompt 增加 `是否核心` 判断 | `prompts/extract.j2` | — |
| 17 | `_create_pending` 分核心/非核心路径 | `settings_extractor.py` | `test_extract_creates_core_character_as_pending_confirmation` |
| 18 | 读取章节任务卡 + 短期记忆 | 同上 | `test_extract_reads_chapter_card_and_memory` |
| 19 | 伏笔回收检测 | 同上 + `extract.j2` | `test_extract_detects_foreshadow_resolution` |
| 20 | `_already_extracted` 改为查章节确认状态 | 同上 | 幂等逻辑不变 |

---

## 四、Day 5：测试 + 全量验收

### 4.1 新增测试预估

| 文件 | 当前 | 新增 | 目标 |
|------|------|------|------|
| `test_production_scanner.py` | 13 | +5 | 18 |
| `test_publish_scanner.py` | 11 | +6 | 17 |
| `test_publish_scheduler.py` | 13 | +3 | 16 |
| `test_settings_extractor.py` | 11 | +4 | 15 |
| 其余 | 92 | — | 92 |
| **合计** | 140 | **+18** | **158** |

### 4.2 最终全量验收

```bash
python scripts/acceptance_test.py   # 模块导入 + 无 stub + 5 任务
python -m pytest tests/ -v           # 158 tests all pass
python -m mypy core/ business/ llm/ main.py  # 0 errors
```

---

## 五、阶段 6 结束状态

```
✅ SOP §4   写入权限与防覆盖   5/5 完全符合
✅ SOP §6   自动生产扫描        8/8 完全符合
✅ SOP §7   自动发布与排班     18/18 完全符合
✅ SOP §8   设定识别与回写      9/9 完全符合
✅ SOP §11  技术部署 10 项     10/10 完全符合
✅ SOP §12  验收标准 10 项     10/10 完全符合
─────────────────────────────────────────
🎉 SOP V1.1 全合规 — OpenClaw 交付完成
```

---

## 六、目录变更

```
openclaw/
├── business/
│   ├── production_scanner.py    ← 守卫条件 + per_novel_max
│   ├── publish_scanner.py       ← 6 项守卫条件
│   ├── publish_scheduler.py     ← 状态/锁/排班字段
│   └── settings_extractor.py   ← 核心分级 + 伏笔回收
├── prompts/
│   └── extract.j2               ← 增加是否核心/伏笔回收字段
├── tests/
│   ├── test_production_scanner.py  ← +5
│   ├── test_publish_scanner.py     ← +6
│   ├── test_publish_scheduler.py   ← +3
│   └── test_settings_extractor.py  ← +4
└── docs/
    └── SOP_COMPLIANCE.md        ← 合规报告（阶段 5 核验结果）
```
