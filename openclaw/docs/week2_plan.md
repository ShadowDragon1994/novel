# OpenClaw 第二周开发计划：积木粘合 + 硬化

> 前置条件：阶段 1 已通过审查（38 个测试全绿、配置完整、基础模块就绪）
> 目标：把独立的积木模块接入 FeishuClient 形成通路，补全集成测试和 GuardLayer 基础规则
> 周期：7 天

---

## 一、本周总览

```
Day 1-2   ReadCache 接入 FeishuClient        → 缓存通路跑通
Day 3-4   测试全面加固（集成测试 + 边界条件）  → 38 → 55+ 条测试
Day 5-6   GuardLayer 基础规则 + 批量初始化脚本  → 防覆盖规则落地
Day 7     代码质量 + 整体验收                  → 可以进入业务阶段
```

---

## 二、每日计划

### Day 1-2：ReadCache 接入 FeishuClient

**现状：** `ReadCache` 是独立模块，FeishuClient 直接调飞书 API，没有走缓存。

**改造点：**

```python
# feishu_client.py 新增缓存钩子

class FeishuClient:
    def __init__(self, ..., cache: ReadCache | None = None):
        self.cache = cache   # ← 可选注入
```

| # | 任务 | 验收 |
|---|---|---|
| 1 | FeishuClient 构造接收可选的 `ReadCache` 参数 | 不传 cache= 时行为完全不变 |
| 2 | `list_records(table_name, ...)` 先查缓存：key=`{table_name}:{hash(params)}` | 命中直接返回，不调飞书 |
| 3 | `get_record(table_name, record_id)` 先查缓存：key=`{table_name}:{record_id}` | 命中直接返回 |
| 4 | `create_record / update_record / delete_record` 成功后 invalidate 该表缓存 | 用 `cache.invalidate_table(table_name)` 批量失效 |
| 5 | `cache.invalidate_table(table_name)` 方法：删除所有 `{table_name}:*` 前缀 | 单元测试覆盖 |
| 6 | 集成测试：Mock 验证首次未命中调 API、第二次命中不走 API | 见 `test_cache_integration.py` |

**验收标准：**
- `list_records` 首次调用调 1 次 API，同一参数第二次调用调 0 次 API
- `create_record` 成功后使该表缓存失效，下次 `list_records` 重新调 API

---

### Day 3-4：测试全面加固（38 → 55+）

**目标：** 每一层都有错误路径测试。

#### 3.1 新增测试（17 个）

| 文件 | 新增 | 覆盖场景 |
|---|---|---|
| `test_feishu_client.py` | +4 | 无 env 时 `FeishuConfigError`、未知表名、飞书返回 `has_more` 分页合并、token 过期自动续 |
| `test_rate_limiter.py` | +2 | 大容量突发放行不延迟、多个并发竞速（`asyncio.gather` 10 个，验证总耗时 ≥ 容量/qps） |
| `test_circuit_breaker.py` | +1 | 多次成功重置计数（`record_success` 后 failure_count 归零） |
| `test_task_lock.py` | +2 | acquire 后进程 PID 写入正确、release 在未锁记录上不抛错 |
| `test_read_cache.py` | +4 | 无 cache key 返回 None、set 后立即 expire 的边界、同一个 key 重复 set 覆盖、invalidate_table 前缀匹配删除 |
| `test_guard_layer.py` | +4 | **新测试覆盖 GuardLayer 规则（见 3.2）** |

#### 3.2 GuardLayer 测试先行（TDD）

在实现 GuardLayer 规则前先写测试，定义契约：

```python
# test_guard_layer.py 新增
async def test_rejects_write_when_content_locked():
    # 给定记录内容锁定状态=是
    # 写"章节名" → raised

async def test_allow_write_to_noncore_field():
    # 给定内容锁定状态=是
    # 写"发布记录" → allowed

async def test_allow_add_pending_for_core_character():
    # 给定核心人物，写"AI建议新增-待确认" → allowed
    # 直接覆盖原内容 → rejected

async def test_version_table_only_new_version():
    # 写"长期记忆"时，旧版本不会被覆盖
    # 只能创建新版本
```

#### 3.3 测试基础设施

| # | 任务 | 验收 |
|---|---|---|
| 1 | 在 `tests/conftest.py` 提取 `make_feishu_client(handler)` 到全局 fixture | 所有 feishu 测试复用同一 fixture |
| 2 | 新增 `tests/data/` 目录，预置 16 表 `field_id` 到 YAML fixture | 测试不依赖真实配置 |
| 3 | 确保 `pytest --cov=core tests/` 能跑（加 `pytest-cov` 到依赖） | ✅ |

**验收标准：** 38 → 55+，覆盖率 `core/` ≥85%。

---

### Day 5-6：GuardLayer 基础规则 + 批量初始化

#### 5.1 GuardLayer 基础规则实现

**现状：** `GuardLayer.check_write()` 只校验了空字段。

**本周实现两条规则：**

```
规则 1：内容锁定保护
  条件：记录的内容锁定状态 = 是
  行为：
    - 禁止字段集合：章节名、章节卡内容、当前版本对应正文、人工审核意见
    - 允许字段集合：发布记录、数据反馈、运行日志、短期记忆、发布状态
  配置化：从 field_mapping.yaml 读取锁定字段白名单

规则 2：核心对象保护
  条件：记录的是否核心 = 是 且 来源状态 = 人工创建
  行为：
    - 禁止：直接覆盖原内容
    - 允许：在"人物变化记录/备注"字段写"AI建议更新-待确认"
```

**代码结构：**

```python
class GuardLayer:
    def __init__(self, feishu_client, *, locked_deny_fields: set[str] | None = None):
        self.locked_deny_fields = locked_deny_fields or DEFAULT_LOCKED_DENY_FIELDS

    async def write(self, table, record_id, fields):
        # 1. 空字段检查
        # 2. 先读当前记录
        # 3. 内容锁定检查
        # 4. 核心对象检查
        # 5. 白名单字段检查
        # → 全部通过才调 feishu_client.update_record
```

**验收标准：**
- 内容锁定章节无法写入禁止字段
- 核心人物无法直接覆盖
- 非核心/未锁定的章节正常读写
- 所有规则可配置（从 field_mapping 读取）

#### 5.2 bootstrap_feishu.py 实现

```python
# scripts/bootstrap_feishu.py
async def main():
    """批量初始化测试数据：
    - 10 本小说（novel-001 ~ novel-010）
    - 10 个账号（每个绑定 1 本）
    - 每本 30 条章节卡（不同状态混合）
    - 每本至少 6 条已定稿章节（满足存稿安全线）
    - 3-5 个核心人物 + 基础世界观 + 势力 + 伏笔
    """
```

**验收标准：** `python -m scripts.bootstrap_feishu` 一键完成初始化，`healthcheck.py` 全绿。

---

### Day 7：代码质量 + 整体验收

| # | 任务 | 验收 |
|---|---|---|
| 1 | 加 `.flake8` 或 `ruff` 配置 + pre-commit hook | `ruff check .` 无报错 |
| 2 | `mypy core/ --strict` 通过（至少 `core/` 无类型错误） | `# type: ignore` 只允许在必要处 |
| 3 | 跑一轮全量测试 | `pytest tests/ -v` → 55+ all pass |
| 4 | 跑一轮 `scripts/healthcheck.py` | 全绿 |
| 5 | 更新 README.md：加上第二周完成后的使用说明 | README 完整 |

---

## 三、本周交付物清单

| 交付物 | 说明 |
|---|---|
| FeishuClient + ReadCache 集成 | `list_records` / `get_record` 走缓存，写入后自动失效 |
| 55+ 条自动测试 | 覆盖每一层的正常 + 错误路径 |
| 测试覆盖率报告 | `pytest --cov=core` ≥85% |
| GuardLayer 两条基础规则 | 内容锁定保护 + 核心对象保护 |
| `bootstrap_feishu.py` | 一键初始化 10 本测试数据 |
| 完整的 `.flake8` / `mypy` 配置 | 代码风格 + 类型检查 |

---

## 四、时间承诺

| Day | 交付内容 | 预估工时 |
|---|---|---|
| 1-2 | ReadCache 接入 FeishuClient + 集成测试 | 8h |
| 3-4 | 17 个新测试 + conftest + pytest-cov | 10h |
| 5-6 | GuardLayer 规则 + bootstrap_feishu.py | 10h |
| 7 | lint/type/README/验收 | 4h |
| **总计** | | **32h** |
