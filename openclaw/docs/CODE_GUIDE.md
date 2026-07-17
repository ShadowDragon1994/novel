# OpenClaw 代码说明文档

> 版本：V1.1
> 更新：2026-05-24

---

## 一、项目概述

OpenClaw（小龙虾）是一个单进程 Python 异步编排服务，用 4 个国产中文 LLM（DeepSeek/豆包/千问/文心）自动化生成、审查、润色、发布多本网文小说。所有业务数据以飞书 Bitable 为唯一数据源，SQLite 只用于瞬态缓存和任务锁。

**核心链路：**

```
章节卡 → [细纲→初稿→一致性→合规→润色→校对] → 待人工审核
       ↘ SettingsExtractor(提取人物/设定/势力/伏笔)
       → PublishScheduler(排期) → PublishScanner(发布) → DeviceController(红手指)
       ↗ Watchdog(存稿/故障/熔断/API 监控)
```

---

## 二、目录结构

```
openclaw/
├── main.py                         # 入口：APScheduler 调度 5 个定时任务
├── pyproject.toml                  # pytest / ruff / mypy 配置
│
├── core/                           # 底层积木（接口化，可复用）
│   ├── config.py                   # load_settings(): yaml + .env 单例加载
│   ├── feishu_client.py            # 飞书 Bitable CRUD + Token 缓存 + 限流 + 重试
│   ├── read_cache.py               # SQLite TTL 缓存（60s 默认）
│   ├── rate_limiter.py             # 令牌桶限流器（asyncio.Lock）
│   ├── circuit_breaker.py          # 三态熔断器（CLOSED→OPEN→HALF_OPEN）
│   ├── task_lock.py                # SQLite INSERT OR IGNORE 原子任务锁
│   └── logger.py                   # loguru 本地 + 飞书运行日志表双写
│
├── llm/                            # LLM 客户端（7 行子类 + 统一基类）
│   ├── base.py                     # ChatCompletionClient: OpenAI 兼容格式 + 断路器/限流
│   ├── deepseek.py                 # DeepSeekClient
│   ├── doubao.py                   # DoubaoClient (火山引擎 Ark)
│   ├── qwen.py                     # QwenClient (阿里云 DashScope)
│   └── wenxin.py                   # WenxinClient (百度千帆)
│
├── business/                       # 上层直写（小说领域专用）
│   ├── llm_pipeline.py             # 6 步链路 + 断点续跑 + Jinja2 Prompt
│   ├── production_scanner.py       # 扫描待生产章节 → 并发执行
│   ├── guard_layer.py              # 写权限门禁（内容锁 + 核心记录保护）
│   ├── settings_extractor.py       # 校对稿 → 提取 4 类世界观信息
│   ├── publish_scheduler.py        # 23:00/08:10 双批发布排期
│   ├── publish_scanner.py          # 扫描到期章节 → 调 DeviceController
│   ├── device_controller.py        # HTTP 调红手指/ADB 执行发布
│   └── watchdog.py                 # 存稿/故障/熔断/API 四项监控
│
├── prompts/                        # Jinja2 模板（6 个已填充 + 1 个提取专用）
│   ├── outline.j2 / draft.j2 / consistency.j2 / compliance.j2
│   ├── polish.j2 / proofread.j2 / extract.j2
│
├── config/
│   ├── .env                        # 敏感信息（API Key 等，不入库）
│   ├── .env.example                # 环境变量模板
│   ├── config.yaml                 # 可调节参数
│   └── field_mapping.yaml          # 飞书 16 表字段映射（table_id + field_id）
│
├── scripts/
│   ├── bootstrap_feishu.py         # 批量初始化测试数据
│   ├── healthcheck.py              # 4 项启动前健康检查
│   ├── acceptance_test.py          # 验收测试脚本
│   ├── diagnose_apis.py            # LLM API 诊断
│   └── test_pipeline_ds_qwen.py    # 真实 API 6 步链路测试
│
├── tests/                          # 140 个单元测试
└── docs/                           # 计划、审查、验收文档
```

---

## 三、架构分层

```
┌─────────────────────────────────────────────┐
│ main.py          APScheduler 5 任务         │
├─────────────────────────────────────────────┤
│ business/        ProductionScanner          │
│                   LLMPipeline               │
│                   SettingsExtractor          │
│                   PublishScheduler           │
│                   PublishScanner             │
│                   GuardLayer                │
│                   Watchdog                  │
├─────────────────────────────────────────────┤
│ llm/             ChatCompletionClient       │
│                   DeepSeek/Doubao/Qwen/Wenxin│
├─────────────────────────────────────────────┤
│ core/            FeishuClient  ReadCache    │
│                   RateLimiter  CircuitBreaker│
│                   TaskLock     Logger       │
│                   Config                    │
├─────────────────────────────────────────────┤
│ 外部系统         飞书 Bitable (数据源)       │
│                   4 LLM API                 │
│                   SQLite (缓存+锁)           │
└─────────────────────────────────────────────┘
```

**"底层积木 + 上层直写"** 原则：
- `core/`：接口化、可独立复用的基础能力，不引用 `business/`
- `business/`：直接写小说领域逻辑，引用 `core/` 和 `llm/`
- `llm/`：LLM 客户端，7 行子类 + 统一基类，引用 `core/`

---

## 四、核心模块详解

### 4.1 FeishuClient (`core/feishu_client.py`)

飞书 Bitable 的唯一读写入口。写操作必须经过 GuardLayer。

```python
class FeishuClient:
    # CRUD 5 方法
    list_records(table_name, **params)    # 列表查询 + 自动翻页 + 缓存
    get_record(table_name, record_id)     # 单条查询 + 缓存
    create_record(table_name, fields)     # 插入 + 缓存失效
    update_record(table_name, id, fields) # 更新 + 缓存失效
    delete_record(table_name, id)         # 删除 + 缓存失效

    # 内部机制
    tenant_access_token()                 # Token 缓存 (asyncio.Lock + 5min 提前刷新)
    _request_json()                       # tenacity 重试 3 次 (exp backoff 0.2~2s)
                                          # 仅 retryable error (429/5xx/999) 重试
```

**限流**：读 3QPS / 写 2QPS（令牌桶，config.yaml 可调）
**缓存**：可选 ReadCache 注入，list_records/get_record 命中即返回，写操作自动失效

### 4.2 LLM Pipeline (`business/llm_pipeline.py`)

6 步串行生成链路，每步完成后立即持久化到飞书正文版本表。

```
STEP_ORDER = [细纲稿 → 初稿 → 一致性稿 → 合规稿 → 润色稿 → 校对稿]
```

```
run_chapter(chapter):
  1. latest_step = VersionStore.latest_step(chapter_id)
  2. start = index_of(latest_step) + 1      # 断点续跑
  3. for step in STEPS[start:]:
       prompt = jinja.render(template, context)
       content = client.generate(prompt)
       VersionStore.save_step(chapter_id, step, content)  # 每步立即保存
```

**断点机制**：进程在第 N 步崩溃 → 重启后从第 N+1 步继续，已完成的步骤不重复执行。

### 4.3 GuardLayer (`business/guard_layer.py`)

所有写入飞书的操作必须经过 GuardLayer（唯一的 update_record 入口）。

**规则 1 — 内容锁定保护**：
- 章节的 `内容锁定状态 ∈ {是/Yes/True}` 时
- 禁止写入 8 个字段：章节名、章节卡内容、当前版本、最终字数、最终评分、上下文哈希、人工审核结果、人工审核意见
- 允许写入其余字段（如发布状态、计划发布时间）

**规则 2 — 核心记录保护**：
- 5 个 Guard 表（人物档案/世界观设定/势力组织/伏笔追踪/长期记忆）
- `来源状态=人工创建` 且 `是否核心=是` 时
- 只允许写 4 个字段：确认状态、来源状态、最后更新时间、最近出场章节
- 其余字段：拒绝直接覆盖，只能追加 "AI建议更新-待确认"

### 4.4 SettingsExtractor (`business/settings_extractor.py`)

校对稿完成后，用千问提取 4 类世界观信息：

| 实体类型 | 目标表 | 新实体行为 | 已有实体行为 |
|---------|--------|-----------|-------------|
| 角色 (characters) | 人物档案表 | 创建（来源=AI, 待确认） | GuardLayer 追加变化记录 |
| 设定 (settings) | 世界观设定表 | 创建 | 追加冲突处理 |
| 势力 (factions) | 势力组织表 | 创建 | 追加回写规则 |
| 伏笔 (foreshadows) | 伏笔追踪表 | 创建 | 追加识别提醒 |

- 幂等：`_already_extracted()` 查运行日志表，同一章节不重复提取
- 实体 ID：`{prefix}-{chapter_id}-{index:02d}` 格式自动生成
- 容错：PermissionError（核心记录被 Guard 拒绝）被 try/except 包裹，跳过该条继续处理后续实体

### 4.5 PublishScheduler (`business/publish_scheduler.py`)

两批次生成发布计划：

| 批次 | 触发时间 | 排期目标 |
|------|---------|---------|
| 晚班 | 23:00 | 次日 (tomorrow) |
| 早班 | 08:10 | 当日 (today) |

- 时间槽：08:30-22:00 内按 `slot_gap_hours=3` 生成 5 个槽位
- 间隔约束：同一小说相邻章节 ≥6h（实际比对的间隔时间含 jitter 偏移）
- 日更上限：从小说总览表读取 `日更目标`
- jitter：固定 5min 偏移，让不同小说略微错开

### 4.6 ProductionScanner (`business/production_scanner.py`)

每 5min 触发一次：

```
run_once():
  list_records(章节任务表) → 过滤 生产状态∈{待生成细纲, 待创作/Pending}
  → 按 优先级(高>中>低) + 章节号 排序
  → 取前 global_max(默认5) 章
  → asyncio.gather 并发执行 (Semaphore 限流)
     → TaskLock.acquire
     → LLMPipeline.run_chapter (6 步链路)
     → GuardLayer.write(生产状态=待人工审核)
     → SettingsExtractor.extract_after_final (可选，失败不影响主流程)
     → TaskLock.release (finally)
```

---

## 五、数据流

### 5.1 生产链路

```
章节任务表 (生产状态=待生成细纲)
  ↓ ProductionScanner
TaskLock.acquire
  ↓ LLMPipeline (6 步，每步写 正文版本表)
GuardLayer.write(生产状态=待人工审核)
  ↓ SettingsExtractor (可选)
GuardLayer.write(人物档案表/世界观设定表/势力组织表/伏笔追踪表)
  ↓
TaskLock.release
  ↓ 人工审核
生产状态=已定稿/Finalized
```

### 5.2 发布链路

```
章节任务表 (生产状态=待人工审核/已定稿, 发布状态=未排期)
  ↓ PublishScheduler (23:00 + 08:10)
GuardLayer.write(计划发布时间 + 发布状态=待发布)
  ↓
章节任务表 (发布状态=待发布, 计划发布时间 ≤ now)
  ↓ PublishScanner
DeviceController.publish_chapter()
  ↓
GuardLayer.write(发布状态=发布成功/失败)
写 发布记录表
```

---

## 六、关键设计决策

| 决策 | 选型 | 理由 |
|------|------|------|
| 数据源 | 飞书 Bitable | 非技术人员可操作、手机端可审核 |
| 数据库 | 无独立 DB | SQLite 仅用于缓存(60s TTL)+任务锁 |
| 调度 | APScheduler (AsyncIOScheduler) | asyncio 原生调度，不引入 Redis/Celery |
| 并发模型 | asyncio + asyncio.gather + Semaphore | 单进程内异步并发，无 GIL 竞争 |
| LLM 调用格式 | OpenAI 兼容 POST + Bearer Token | httpx 统一处理，不引入各厂商 SDK |
| Prompt 模板 | Jinja2 (StrictUndefined) | 变量缺失时报错不静默 |
| 断路机制 | 每模型独立 CircuitBreaker | 5 次失败熔断 10min，单模型故障不拖垮整条链路 |
| 写保护 | GuardLayer 两条规则 | 所有写操作走同一门禁 |
| 测试策略 | 每模块 Fake 类 + pytest-asyncio | 不引入 mock 库，Fake 即文档 |
