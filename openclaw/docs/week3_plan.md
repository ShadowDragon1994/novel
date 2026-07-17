# OpenClaw 第三周开发计划：LLM Pipeline + ProductionScanner

> 前置条件：阶段 2 已通过审查（59 个测试全绿 + ruff/mypy 双清 + GuardLayer 落地）
> 目标：单章从"待生成细纲"跑到"待人工审核"
> 周期：2 周（14 天）

---

## 一、本周总览

```
Week 3-1（Day 1-7）：LLM 客户端 + 6 步 Pipeline + Prompts
Week 3-2（Day 8-14）：ProductionScanner + 状态机 + 联调测试
```

---

## 二、Week 3-1：LLM Pipeline 链路（Day 1-7）

### Day 1-2：LLM 模型客户端实现

**现状：** 4 个客户端都只 `raise NotImplementedError`，`llm/base.py` 定义了接口。

**改造目标：** 每个客户端实现真实的 API 调用。

```python
# llm/base.py
class LLMClient(ABC):
    @abstractmethod
    async def generate(self, prompt: str, *, model: str | None = None) -> str:
        """调用 API 生成文本"""
        raise NotImplementedError
```

| # | 任务 | 文件 | 验收 |
|---|---|---|---|
| 1 | `DeepSeekClient` 实现：调 DeepSeek Chat API，支持流式/非流式，含重试 + 超时 | `llm/deepseek.py` | 单测：mock API 返回有效文本 |
| 2 | `DoubaoClient` 实现：调豆包 API（火山引擎） | `llm/doubao.py` | 同上 |
| 3 | `QwenClient` 实现：调千问 API（阿里云 DashScope） | `llm/qwen.py` | 同上 |
| 4 | `WenxinClient` 实现：调文心 API（百度千帆） | `llm/wenxin.py` | 同上 |
| 5 | 所有客户端接入 `CircuitBreaker` 和 `RateLimiter` | 各文件 | 连续失败 5 次熔断 10 分钟 |
| 6 | 每个客户端写 2 个测试：正常返回 + API 失败熔断 | `tests/test_llm_clients.py` | pytest 通过 |

**技术决策说明：**

| 决策 | 选型 | 理由 |
|---|---|---|
| 库 | httpx（已有） | 与 FeishuClient 保持一致，不引入第三方 SDK |
| 流式 | 非流式 | 6 步链路串行，SSE 无收益 |
| API Key | 走 `.env` | 与现有配置体系一致 |
| 重试 | tenacity（已有） | 复用现有 `is_retryable_error` 模式 |
| 超时 | 30s | 国内模型响应通常在 5-15s |

### Day 3-5：LLMPipeline 状态机 + 断点续跑

**现状：** `PipelineStep` 枚举已定义，`LLMPipeline` 骨架已有。

**实现目标：**

```python
class LLMPipeline:
    steps: list[tuple[PipelineStep, LLMClient, str]] = [
        (PipelineStep.OUTLINE,      deepseek, "outline.j2"),
        (PipelineStep.DRAFT,        doubao,   "draft.j2"),
        (PipelineStep.CONSISTENCY,  qwen,     "consistency.j2"),
        (PipelineStep.COMPLIANCE,   wenxin,   "compliance.j2"),
        (PipelineStep.POLISH,       doubao,   "polish.j2"),
        (PipelineStep.PROOFREAD,    qwen,     "proofread.j2"),
    ]

    async def run_chapter(self, chapter_id: str, context: ChapterContext) -> str:
        # 1. 查断点：正文版本表里最新已完成步骤
        # 2. 从该步骤 +1 继续
        # 3. 每步：渲染 Prompt → 调 LLM → 解析结果 → 持久化 → 写运行日志
        # 4. 最后更新章节任务表生产状态 = "待人工审核"
```

| # | 任务 | 验收 |
|---|---|---|
| 1 | 实现 `ChapterContext` 数据类：章节卡 + 卷大纲 + 长期记忆 + 前 10 章摘要 | 字段完整 |
| 2 | 实现 `_render_prompt(step_name, context)`：用 Jinja2 渲染 prompt | 输出含上下文 |
| 3 | 实现 `run_chapter` 主循环：遍历 steps，每步完成写正文版本表 | 6 步串行，中间断点可恢复 |
| 4 | 实现断点恢复：`_latest_step(chapter_id)` 读正文版本表最新版本类型 | 崩溃重启后跳过已完成步骤 |
| 5 | 每步写质量检查表 + 运行日志表 | QA 表有评分和问题列表 |
| 6 | `run_chapter` 过程中持有 TaskLock，完成后释放 | 锁超时 30min 自动释放 |

**断点续跑状态图：**

```
进程启动 → run_chapter(id)
  → 读正文版本表，找最新版本类型
  → 最近 = 细纲稿 → 从"初稿"开始
  → 最近 = 校对稿 → 已完成，跳过
  → 没有记录 → 从"细纲"开始

每步执行：
  LLM 调用 → 解析结果
    → 写正文版本表（版本类型=当前步骤名）
    → 写质量检查表（如适用）
    → 写运行日志表
    → 更新章节任务表生产状态
```

### Day 6-7：Prompt 模板填充

**现状：** 6 个 `*.j2` 文件都是 `# TODO`。

| 文件 | 模板用途 | 输入 | 输出 |
|---|---|---|---|
| `outline.j2` | 生成细纲 | 章节卡、卷主线、前情摘要 | 详细章节大纲 |
| `draft.j2` | 生成初稿 | 细纲 + 人物设定 + 记忆 | 3000-4000 字正文 |
| `consistency.j2` | 一致性检查 | 初稿 + 人物/设定/伏笔追踪表 | 检查报告（冲突标记） |
| `compliance.j2` | 合规检查 | 初稿 + 平台规则 | 合规评分 + 修改建议 |
| `polish.j2` | 文学润色 | 初稿 + 检查报告 | 润色后正文 |
| `proofread.j2` | 校对终稿 | 润色稿 | 终稿（修正错别字/语病） |

**每个 Prompt 模板结构：**

```jinja
# outline.j2 示例
## 任务：生成章节细纲

### 小说信息
- 书名：{{ context.title }}
- 题材：{{ context.genre }}

### 卷信息
- 卷名：{{ context.volume_name }}
- 本卷主线：{{ context.main_plot }}

### 章节卡
- 章节号：{{ context.chapter_number }}
- 章节卡内容：{{ context.chapter_card }}
{% if context.foreshadow_hints %}
### 需要铺设的伏笔
{% for hint in context.foreshadow_hints %}
- {{ hint }}
{% endfor %}
{% endif %}

### 输出要求
生成该章节的详细大纲，包含：开头钩子、3-5 个情节段落、结尾悬念。
字数：500-800 字。
```

| # | 任务 | 验收 |
|---|---|---|
| 1 | 补全 `outline.j2` | 包含小说/卷/章节/伏笔上下文 |
| 2 | 补全 `draft.j2` | 引用细纲 + 人物设定 + 记忆 |
| 3 | 补全 `consistency.j2` | 检查人物 OOC、设定冲突、伏笔一致性 |
| 4 | 补全 `compliance.j2` | 检查敏感词/违规内容（只提示不修改） |
| 5 | 补全 `polish.j2` | 给出润色要求（节奏/氛围/对话） |
| 6 | 补全 `proofread.j2` | 错别字/语病/标点修复 |
| 7 | 写 1 个测试验证每个模板能正常渲染 | `test_prompt_templates.py` |

---

## 三、Week 3-2：ProductionScanner + 联调（Day 8-14）

### Day 8-9：ProductionScanner 实现

**现状：** `ProductionScanner.run_once()` 是 `NotImplementedError`。

**实现目标：**

```python
class ProductionScanner:
    async def run_once(self) -> None:
        # 1. 查 ReadCache（或飞书）获取可生产章节
        # 2. 过滤：TaskLock 未锁、重试次数 < 3、内容返工 < 3
        # 3. 按优先级排序（存稿少优先、发布日期近优先、章节号小优先）
        # 4. 取全局最多 5 章
        # 5. 提交到 asyncio.gather() 并发执行
        # 6. 每章启动前写 TaskLock + 写运行日志表
```

| # | 任务 | 验收 |
|---|---|---|
| 1 | 实现 `_fetch_producible_chapters()`：查章节任务表 | 返回可生产的章节列表（含完整字段） |
| 2 | 实现 `_priority_sort()`：按 3 级排序 | 存稿不足的排在前面 |
| 3 | 实现 `run_once()` 主逻辑：限并发 + 并发执行 | 全局 ≤5，单本 ≤2 |
| 4 | 异常处理：单个章节失败不影响其它 | 错误写运行日志，不抛到循环外 |
| 5 | 写测试：Mock FeishuClient 返回待生产章节 | 验证功能正常 |

### Day 10-11：状态机粘连

**把 Pipeline + Scanner + 状态机 串起来：**

```
[Scanner 取任务]
  → res = FeishuClient.list_records(filter={生产状态∈[待生成细纲, ...], ...})
  → 过滤 TaskLock
  → sort & limit

[对每章]
  → TaskLock.acquire(chapter_id, step, pid)
  → LLMPipeline.run_chapter(chapter_id, context)
      → 步骤1: 细纲稿 → 步骤2: 初稿 → ... → 步骤6: 校对稿
      → 每步：GuardLayer.write(正文版本表), GuardLayer.write(质量检查表)
  → 推进生产状态 = 待人工审核
  → TaskLock.release(chapter_id)
  → 异常时：写错误信息、更新流程重试次数
      重试≥3 → 生产状态 = 失败
```

**状态机验证：**

```python
assert 状态转移图：
  待生成细纲 → 待人工审核    # 正常链路
  待生成细纲 → 失败          # 重试超限
  待生成初稿 → 待人工审核    # 返工后重跑
  返工中 → 待人工审核        # 人工标记返工后
```

| # | 任务 | 验收 |
|---|---|---|
| 1 | 把关 GuardLayer 接入 Pipeline：每步写入必经 GuardLayer | GuardLayer.write(正文版本表) |
| 2 | 严格的生产状态枚举：`待生成细纲 → 待生成初稿 → 待一致性检查 → 待辅助检查 → 待润色 → 待校对 → 待人工审核` | 所有转移合法 |

### Day 12-14：联调测试 + 收尾

#### 12.1 本地 Mock 联调

```
模拟数据流：
  bootstrap_feishu.py --count 1        → 创建 NOVEL-01
  人工在飞书填入 1 条章节卡（生产状态=待生成细纲）
  ProductionScanner.run_once() 触发     → 自动执行 6 步链路
  → 验证：正文版本表 6 条记录
  → 验证：质量检查表 1-2 条
  → 验证：章节任务表生产状态=待人工审核
  → 验证：运行日志表对应记录完整
  → 验证：TaskLock 已释放
```

#### 12.2 测试清单

| # | 测试 | 文件 | 目标 |
|---|---|---|---|
| 1 | LLMPipeline 6 步端到端（Mock LLM） | `test_llm_pipeline.py` | 6 步全部执行，结果写入 |
| 2 | LLMPipeline 断点续跑（第 3 步中断） | `test_llm_pipeline.py` | 重启后从第 4 步开始 |
| 3 | LLMPipeline 全部失败（6 步报错） | `test_llm_pipeline.py` | 流程图到 3 次重试后失败 |
| 4 | ProductionScanner 空列表 | `test_production_scanner.py` | 不抛错 |
| 5 | ProductionScanner 锁冲突 | `test_production_scanner.py` | 跳过已锁章节 |
| 6 | ProductionScanner 并发上限 | `test_production_scanner.py` | 全局 ≤5 |
| 7 | 状态机转移合法 | `test_state_machine.py` | 不合法的转移抛错 |
| 8 | 各 Prompt 模板可渲染 | `test_prompt_templates.py` | 填入数据后正确输出 |

**预期测试总数：** 59 + 25+ = **84+**

---

## 四、目录变更

```
openclaw/
├── llm/
│   ├── base.py           ← 已有，加 model 参数
│   ├── deepseek.py       ← 实现 API 调用 + 断路器
│   ├── doubao.py         ← 实现 API 调用
│   ├── qwen.py           ← 实现 API 调用
│   └── wenxin.py         ← 实现 API 调用
├── prompts/
│   ├── outline.j2        ← 填充完整
│   ├── draft.j2          ← 填充完整
│   ├── consistency.j2    ← 填充完整
│   ├── compliance.j2     ← 填充完整
│   ├── polish.j2         ← 填充完整
│   └── proofread.j2      ← 填充完整
├── business/
│   ├── llm_pipeline.py   ← 实现完整 6 步链路
│   ├── production_scanner.py  ← 实现 Scanner
│   └── state_machine.py  ← 新增：生产状态枚举 + 转移表
├── core/
│   └── llm_rate_limiter.py ← 可选项：LLM 独立限流桶管理
├── tests/
│   ├── test_llm_clients.py    ← 新增
│   ├── test_llm_pipeline.py   ← 新增
│   ├── test_production_scanner.py  ← 新增
│   ├── test_state_machine.py  ← 新增
│   └── test_prompt_templates.py  ← 新增
└── config/
    └── .env              ← 加 4 个 LLM API key
```

---

## 五、可配置参数（config.yaml 新增）

```yaml
llm:
  deepseek_model: "deepseek-chat"         # 默认模型名
  doubao_model: "doubao-pro-32k"
  qwen_model: "qwen-max"
  wenxin_model: "ERNIE-4.0"
  
  timeout_seconds: 30                      # LLM 调用超时
  
  rate_limits:
    deepseek_qps: 2
    doubao_qps: 2
    qwen_qps: 2
    wenxin_qps: 1
```

---

## 六、第三周结束时的状态

```
✅ LLM 4 个客户端全部实现 + 接入断路器/限流器
✅ LLMPipeline 6 步串行 + 断点续跑
✅ ProductionScanner 定时扫描 + 并发控制 + TaskLock
✅ 6 个 Prompt 模板全部填充
✅ 25+ 个新测试
✅ ruff / mypy / pyproject 保持
✅ 本地 Mock 联调：1 章从"待生成细纲"到"待人工审核"
❌ 未接入真实 LLM API（需联调当天再接入真实 key）
❌ SettingsExtractor / PublishScheduler / PublishScanner 留到阶段 4
```

---

## 七、下周开始前确定

- 4 个模型 API Key 是否就绪？
- DeepSeek / 豆包 / 千问 / 文心的 API 调用方式（OpenAI 兼容 SDK 还是原生 API）？
- Prompt 模板的语言偏好（中文为主，英文字段名？）
