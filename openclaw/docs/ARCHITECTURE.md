# OpenClaw 系统架构图

> 版本：V1.1 | 更新：2026-05-28

---

## 一、整体架构

```mermaid
graph TB
    subgraph 外部服务
        FS[飞书 Bitable<br/>16张表，唯一数据源]
        DS[DeepSeek API<br/>deepseek-chat]
        DB[豆包 API<br/>doubao-seed-2.0-pro]
        QW[千问 API<br/>qwen-plus]
        WX[文心 API<br/>ernie-4.0-turbo-128k]
        HS[红手指云手机<br/>DeviceController]
    end

    subgraph 调度层
        MAIN[main.py<br/>APScheduler<br/>5个定时任务]
    end

    subgraph 业务层 business/
        PS[ProductionScanner<br/>生产扫描器<br/>每5min触发]
        LP[LLMPipeline<br/>6步生成链路<br/>断点续跑]
        SE[SettingsExtractor<br/>世界观提取器<br/>校对后自动触发]
        GL[GuardLayer<br/>写权限门禁<br/>双规则保护]
        SCH[PublishScheduler<br/>发布排期器<br/>23:00 + 08:10]
        PUB[PublishScanner<br/>发布执行器<br/>每5min触发]
        DC[DeviceController<br/>设备控制器<br/>HTTP → 红手指]
        WD[Watchdog<br/>系统守护器<br/>每1min触发]
    end

    subgraph LLM层 llm/
        BASE[ChatCompletionClient<br/>OpenAI兼容基类<br/>断路器+限流+3路fallback]
        DEEP[DeepSeekClient 7行]
        DOU[DoubaoClient 7行<br/>timeout=300s]
        QWE[QwenClient 7行]
        WEN[WenxinClient 7行]
    end

    subgraph 基础设施 core/
        FC[FeishuClient<br/>CRUD+Token缓存<br/>tenacity重试3次]
        RC[ReadCache<br/>SQLite TTL缓存<br/>60s过期]
        RL[RateLimiter<br/>令牌桶<br/>读3QPS/写2QPS]
        CB[CircuitBreaker<br/>三态熔断器<br/>5次失败→冷却10min]
        TL[TaskLock<br/>SQLite原子锁<br/>30min超时释放]
        LOG[Logger<br/>loguru本地<br/>+飞书双写]
    end

    MAIN --> PS
    MAIN --> PUB
    MAIN --> SCH
    MAIN --> WD
    PS --> LP
    PS --> SE
    LP --> BASE
    PS --> GL
    PUB --> DC
    PUB --> GL
    SCH --> GL
    SE --> GL
    SE --> BASE
    BASE --> DEEP
    BASE --> DOU
    BASE --> QWE
    BASE --> WEN
    DEEP --> DS
    DOU --> DB
    QWE --> QW
    WEN --> WX
    DC --> HS
    FC --> FS
    GL --> FC
    PS --> FC
    PUB --> FC
    SCH --> FC
    SE --> FC
    WD --> FC
```

---

## 二、调度层 — 5个定时任务

```mermaid
graph TD
    MAIN["main.py 启动"]
    MAIN --> J1["production_scanner<br/>interval=300s"]
    MAIN --> J2["publish_scanner<br/>interval=300s"]
    MAIN --> J3["publish_plan_evening<br/>cron 23:00"]
    MAIN --> J4["publish_plan_morning<br/>cron 08:10"]
    MAIN --> J5["watchdog<br/>interval=60s"]

    J1 -->|"每5分钟"| SCAN["扫描章节任务表<br/>→ 过滤守卫条件<br/>→ 排序取前N章<br/>→ 并发执行"]
    J2 -->|"每5分钟"| PUB_SCAN["扫描到期章节<br/>→ 6道守卫检查<br/>→ DeviceController<br/>→ 写发布记录"]
    J3 -->|"每晚23:00"| EVE["为次日生成排班<br/>→ 选已定稿章节<br/>→ 分配时间槽<br/>→ 写计划发布时间"]
    J4 -->|"每早08:10"| MOR["调整当日排班<br/>→ 补排新定稿章节"]
    J5 -->|"每分钟"| WD_CHK["四项检查<br/>→ 存稿水位<br/>→ 故障章节<br/>→ 熔断状态<br/>→ 飞书连通"]
```

---

## 三、生产链路 — 一条章节的旅程

```mermaid
sequenceDiagram
    participant B as 飞书Bitable
    participant S as ProductionScanner
    participant L as TaskLock
    participant P as LLMPipeline
    participant M1 as DeepSeek
    participant M2 as 豆包Seed2.0
    participant M3 as 千问
    participant M4 as 文心4.0
    participant G as GuardLayer
    participant E as SettingsExtractor

    S->>B: list_records(章节任务表)
    B-->>S: 返回5条章节
    S->>S: 过滤: 内容锁定=否<br/>重试<3 返工<3<br/>状态∈{待生成细纲...返工中}
    S->>S: 排序: 优先级+章节号<br/>限流: per_novel≤2 global≤5
    S->>L: acquire(chapter_id)
    L-->>S: 加锁成功

    Note over S,P: 并发执行 (Semaphore)

    S->>P: run_chapter(chapter)
    P->>P: latest_step() → 断点检查
    P->>M1: Step1 细纲稿 prompt
    M1-->>P: 细纲 1500字
    P->>B: save_step → 正文版本表

    P->>M2: Step2 初稿 prompt+细纲
    M2-->>P: 初稿 2200字
    P->>B: save_step

    P->>M3: Step3 一致性检查 prompt+初稿
    M3-->>P: 一致性稿 3300字
    P->>B: save_step

    P->>M4: Step4 合规检查 prompt+一致性稿
    M4-->>P: 合规稿 3300字
    P->>B: save_step

    P->>M2: Step5 润色 prompt+合规稿
    M2-->>P: 润色稿 3900字
    P->>B: save_step

    P->>M3: Step6 校对 prompt+润色稿
    M3-->>P: 校对稿 3800字 ★终稿
    P->>B: save_step

    P-->>S: PipelineResult

    S->>G: write(生产状态=待人工审核)
    G->>B: update_record

    S->>E: extract_after_final(chapter_id)
    E->>M3: 提取 prompt+校对稿
    M3-->>E: JSON{人物/设定/势力/伏笔}
    E->>G: write(人物档案表...)
    G->>B: create_record × N

    S->>L: release(chapter_id)
```

---

## 四、发布链路 — 从审核到发布

```mermaid
sequenceDiagram
    participant H as 人工(飞书)
    participant B as 飞书Bitable
    participant SCH as PublishScheduler
    participant PUB as PublishScanner
    participant DC as DeviceController
    participant HS as 红手指云手机

    Note over H: 晚班审核
    H->>B: 审核通过<br/>生产状态=已完成<br/>内容锁定=人工锁定<br/>发布状态=未排期

    Note over SCH: 23:00 触发排班
    SCH->>B: list_records(章节任务表)
    B-->>SCH: 已定稿+已锁定+未排期
    SCH->>SCH: 过滤守卫条件<br/>生成时间槽(08:30~22:00)<br/>每章+5min jitter<br/>同本间隔≥6h<br/>不超日更上限
    SCH->>B: GuardLayer.write<br/>计划发布时间<br/>发布状态=待发布<br/>排班批次

    Note over PUB: 每5min扫描
    PUB->>B: list_records(章节任务表)
    B-->>PUB: 待发布章节列表
    PUB->>PUB: 6道守卫检查:<br/>①生产状态∈{已定稿,已完成}<br/>②内容锁定∈{是,人工锁定}<br/>③当前版本不为空<br/>④小说自动发布开关<br/>⑤账号健康状态<br/>⑥计划时间≤now
    PUB->>B: _already_published → 去重
    PUB->>DC: publish_chapter(cid, aid)
    DC->>HS: HTTP POST /publish
    HS-->>DC: 200 OK
    DC-->>PUB: 成功
    PUB->>B: create_record 发布记录(成功)
    PUB->>B: GuardLayer.write 发布状态=发布成功
```

---

## 五、GuardLayer — 写保护双规则

```mermaid
graph TD
    WRITE["业务层调用<br/>guard_layer.write(table, record_id, fields)"]
    WRITE --> CHK1{"表=章节任务表<br/>且内容锁定=是?"}
    CHK1 -->|是| BLOCK1["遍历fields<br/>检查是否在8个禁止字段中<br/>章节名/章节卡内容/当前版本<br/>最终字数/评分/上下文哈希<br/>人工审核结果/意见"]
    BLOCK1 -->|"包含禁止字段"| REJECT["抛出 PermissionError<br/>内容已锁定"]
    BLOCK1 -->|"不包含"| PASS1["允许写入"]
    CHK1 -->|否| CHK2{"表∈5个Guard表<br/>且来源=人工创建<br/>且是否核心=是?"}
    CHK2 -->|是| BLOCK2["遍历fields<br/>检查是否在4个白名单中<br/>确认状态/来源状态<br/>最后更新时间/最近出场章节"]
    BLOCK2 -->|"不在白名单"| REJECT2["抛出 PermissionError<br/>核心记录不可覆盖<br/>请使用追加建议方式"]
    BLOCK2 -->|"在白名单"| PASS2["允许写入"]
    CHK2 -->|否| PASS3["直接放行"]
    PASS1 --> UPDATE["feishu_client.update_record"]
    PASS2 --> UPDATE
    PASS3 --> UPDATE
    UPDATE --> FEISHU["飞书 Bitable"]
```

---

## 六、熔断与限流机制

```mermaid
stateDiagram-v2
    [*] --> CLOSED: 初始状态
    CLOSED --> CLOSED: 请求成功<br/>failure_count=0
    CLOSED --> OPEN: 连续失败≥5次<br/>记录opened_at
    OPEN --> OPEN: 拒绝所有请求<br/>抛出CircuitOpenError
    OPEN --> HALF_OPEN: 冷却时间到<br/>≥600秒
    HALF_OPEN --> CLOSED: 试探请求成功<br/>重置计数器
    HALF_OPEN --> OPEN: 试探请求失败<br/>重新计时冷却

    note right of OPEN
        每个LLM客户端独立熔断
        DeepSeek熔断 ≠ 豆包熔断
        不影响其他模型步骤
    end note
```

```mermaid
graph LR
    subgraph 限流器
        REQ[请求到达] --> BUCKET{令牌桶<br/>有可用令牌?}
        BUCKET -->|有| CONSUME[消费1个令牌<br/>立即执行]
        BUCKET -->|无| SLEEP[asyncio.sleep<br/>等待令牌补充]
        SLEEP --> BUCKET
    end
    subgraph 配置
        QPS["飞书读: 3 QPS<br/>飞书写: 2 QPS<br/>LLM调用: 2 QPS"]
    end
```

---

## 七、SettingsExtractor — 世界观提取与分级

```mermaid
graph TD
    TRIGGER["ProductionScanner<br/>pipeline完成后触发"]
    TRIGGER --> IDEM["_already_extracted?<br/>查运行日志表"]
    IDEM -->|已提取| SKIP["跳过"]
    IDEM -->|未提取| LOAD["读取校对稿<br/>+章节卡+短期记忆"]
    LOAD --> LLM["千问提取<br/>→ JSON with Schema"]
    LLM --> PARSE["_parse_entities<br/>json.loads + 正则兜底"]
    PARSE --> LOOP["遍历4类实体"]

    LOOP --> MATCH["_find_match<br/>名称+别名匹配已有人物"]
    MATCH -->|"已有匹配"| APPEND["_append_suggestion<br/>GuardLayer.write<br/>追加到人物变化记录<br/>被核心记录拒绝→跳过"]
    MATCH -->|"无匹配"| CORE{"LLM判断<br/>是否核心?"}
    CORE -->|核心| PENDING["create_record<br/>来源=AI建议新增-待确认<br/>确认=待确认<br/>是否核心=True"]
    CORE -->|非核心| AUTO["create_record<br/>来源=AI自动新增<br/>确认=已确认<br/>是否核心=False"]

    APPEND --> NEXT["下一个实体"]
    PENDING --> NEXT
    AUTO --> NEXT
    NEXT --> LOOP
    LOOP --> DONE["写运行日志表<br/>返回 ExtractResult"]
```

---

## 八、断点续跑机制

```mermaid
sequenceDiagram
    participant P as LLMPipeline
    participant V as FeishuVersionStore
    participant B as 飞书正文版本表

    Note over P: 进程启动
    P->>V: latest_step(chapter_id)
    V->>B: list_records(正文版本表)
    B-->>V: 所有版本记录
    V->>V: 筛选该章节+已知步骤<br/>按STEP_ORDER排序<br/>取最高步骤

    alt 无历史记录
        V-->>P: None → 从Step1开始
    else 已有细纲稿
        V-->>P: OUTLINE → 从DRAFT开始
    else 已有润色稿
        V-->>P: POLISH → 从PROOFREAD开始
    else 已有校对稿
        V-->>P: PROOFREAD → 跳过(已完成)
    end

    Note over P: 每步执行
    P->>P: 渲染Jinja2 prompt
    P->>P: LLM.generate()
    P->>V: save_step(step, content)
    V->>B: create_record(版本内容)

    Note over B: 进程在第4步崩溃<br/>重新启动后
    P->>V: latest_step() → COMPLIANCE
    P->>P: 从POLISH继续<br/>前4步不重复执行
```

---

## 九、10本并发模型

```mermaid
graph TD
    SCAN["ProductionScanner.run_once()"]
    SCAN --> FILTER["过滤出4章待生产"]
    FILTER --> SORT["排序: 优先级+章节号"]
    SORT --> LIMIT["_select_with_limits()"]

    LIMIT --> CHK_NOVEL{"同本小说<br/>已选≥2章?"}
    CHK_NOVEL -->|"是"| SKIP_NOVEL["跳过该本章节"]
    CHK_NOVEL -->|"否"| ADD["加入执行队列"]
    ADD --> CHK_GLOBAL{"全局已选≥5章?"}
    CHK_GLOBAL -->|"是"| STOP["停止选取"]
    CHK_GLOBAL -->|"否"| NEXT["继续下一章"]
    NEXT --> CHK_NOVEL

    ADD --> GATHER["asyncio.gather()<br/>Semaphore(5)"]
    GATHER --> C1["Task CH-002"]
    GATHER --> C2["Task CH-003"]
    GATHER --> C3["Task CH-004"]
    GATHER --> C4["Task CH-005"]

    C1 --> LOCK1["TaskLock.acquire"]
    C2 --> LOCK2["TaskLock.acquire"]
    C3 --> LOCK3["TaskLock.acquire"]
    C4 --> LOCK4["TaskLock.acquire"]

    LOCK1 --> PIPE1["6步Pipeline<br/>~120s/章"]
    LOCK2 --> PIPE2["6步Pipeline<br/>~120s/章"]
    LOCK3 --> PIPE3["6步Pipeline<br/>~120s/章"]
    LOCK4 --> PIPE4["6步Pipeline<br/>~120s/章"]

    PIPE1 --> REL1["TaskLock.release"]
    PIPE2 --> REL2["TaskLock.release"]
    PIPE3 --> REL3["TaskLock.release"]
    PIPE4 --> REL4["TaskLock.release"]
```

---

## 十、完整24小时时间线

```mermaid
gantt
    title OpenClaw 每日运行周期
    dateFormat HH:mm
    axisFormat %H:%M

    section 早班
    启动检查(人工)           :crit, 08:00, 30min
    早班排班(Scheduler)       :active, 08:10, 5min

    section 白天自动运行
    生产扫描(每5min)          :active, 08:30, 810min
    发布扫描(每5min)          :active, 08:30, 810min
    Watchdog监控(每1min)      :done, 08:30, 810min

    section 晚班
    晚班审核(人工)            :crit, 22:30, 75min
    晚班排班(Scheduler)       :active, 23:00, 5min
    夜间可关机               :23:05, 525min
```

---

## 十一、数据存储架构

```mermaid
graph LR
    subgraph 飞书Bitable_唯一数据源
        T1[小说总览表]
        T2[账号管理表]
        T3[分卷大纲表]
        T4[章节任务表]
        T5[人物档案表]
        T6[世界观设定表]
        T7[势力组织表]
        T8[伏笔追踪表]
        T9[长期记忆表]
        T10[中期记忆表]
        T11[短期记忆表]
        T12[正文版本表]
        T13[质量检查表]
        T14[发布记录表]
        T15[数据反馈表]
        T16[运行日志表]
    end

    subgraph SQLite_辅助存储
        CACHE["read_cache<br/>60s TTL<br/>feishu:list:*<br/>feishu:record:*"]
        LOCK["task_lock<br/>chapter_id<br/>locked_at<br/>lock_step<br/>process_pid"]
    end

    subgraph 本地文件
        ENV[".env<br/>API Keys"]
        YAML["config.yaml<br/>field_mapping.yaml"]
        LOGS["logs/openclaw.log<br/>loguru滚动日志"]
        OUTPUT["output/<br/>导出的小说正文"]
    end

    T4 -.->|"读缓存"| CACHE
    T12 -.->|"读缓存"| CACHE
    T4 -.->|"任务锁"| LOCK
```

---

## 十二、错误处理层级

```mermaid
graph TD
    ERR[错误发生] --> L1{哪一层?}
    L1 -->|"LLM API"| LLM_ERR["CircuitBreaker.record_failure<br/>连续5次→熔断10min<br/>→ 跳过该步骤<br/>→ 下次扫描重试"]
    L1 -->|"飞书API"| FS_ERR["is_retryable?<br/>429/5xx/999 → tenacity重试3次<br/>401/403 → 立即失败<br/>→ 写错误信息到章节"]
    L1 -->|"Pipeline"| PIPE_ERR["每步save_step已保存<br/>→ 断点续跑恢复<br/>→ TaskLock.finally释放"]
    L1 -->|"发布"| PUB_ERR["重试次数+1<br/>→ <3次: 保持待发布<br/>→ ≥3次: 发布失败+账号观察"]
    L1 -->|"SettingsExtractor"| EXT_ERR["try/except包裹<br/>→ PermissionError跳过该实体<br/>→ 其他异常写错误信息<br/>→ 不阻塞审核流程"]
    L1 -->|"系统级"| SYS_ERR["Watchdog检测<br/>→ 存稿<3→critical<br/>→ 熔断→warn<br/>→ 飞书断连→critical"]
```

---

## 十三、代码规模

| 层 | 文件数 | Python行数 | 测试数 |
|----|--------|-----------|--------|
| core/ | 7 | ~650 | 33 |
| llm/ | 5 | ~180 | 17 |
| business/ | 8 | ~1400 | 67 |
| main.py | 1 | ~90 | 5 |
| scripts/ | 5 | ~400 | — |
| tests/ | 18 | ~2800 | — |
| prompts/ | 7 | ~200 | — |
| config/ | 3 | ~50 | — |
| **合计** | **54** | **~5,800** | **162** |
