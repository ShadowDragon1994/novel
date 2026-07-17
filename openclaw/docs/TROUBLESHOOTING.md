# OpenClaw 常见问题解决指导书

> 版本：V1.1
> 更新：2026-05-24

---

## 目录

1. [启动问题](#一启动问题)
2. [LLM API 问题](#二llm-api-问题)
3. [飞书问题](#三飞书问题)
4. [Pipeline 问题](#四pipeline-问题)
5. [发布问题](#五发布问题)
6. [性能问题](#六性能问题)
7. [数据一致性问题](#七数据一致性问题)

---

## 一、启动问题

### Q1: `ModuleNotFoundError: No module named 'xxx'`

**现象**：运行 `python main.py` 时报缺少依赖。

**解决**：
```bash
pip install httpx pyyaml pydantic python-dotenv jinja2 tenacity loguru apscheduler
```

**验证**：`python scripts/acceptance_test.py` 应该全部通过。

---

### Q2: `FeishuConfigError: FEISHU_APP_ID and FEISHU_APP_SECRET are required`

**原因**：`.env` 文件未创建或环境变量未加载。

**解决**：
```bash
# 确认 config/.env 存在且格式正确
cat config/.env
# FEISHU_APP_ID=cli_xxxxxxxxxxxx
# FEISHU_APP_SECRET=xxxxxxxxxxxx

# 确认 python-dotenv 已安装
pip install python-dotenv
```

---

### Q3: `SchedulerNotRunningError` 或 APScheduler 任务未注册

**原因**：运行 `main.py` 多次或 scheduler 被提前 shutdown。

**解决**：
- 单进程运行，不要同时启动多个 `main.py` 实例
- 如果测试中遇到此错误，使用 `acceptance_test.py` 代替手动调度器测试
- 在生产环境中使用 systemd/NSSM 管理单实例

---

### Q4: 某个 APScheduler 任务报错但不影响进程

**原因**：stub 模块的方法仍为 `NotImplementedError`。APScheduler 会捕获异常但不会终止进程。

**诊断**：
```bash
python scripts/acceptance_test.py  # 查看 "NotImplementedError Audit" 部分
```

**解决**：确保所有 business/llm 模块均已实现。当任务从 stub 变为真实实现后，`add_job_if_implemented` 会自动激活调度。

---

## 二、LLM API 问题

### Q5: DeepSeek 返回 `401 Authorization Required`

**检查**：
```bash
python scripts/diagnose_apis.py
```

**可能原因**：
1. API Key 过期 → 去 [platform.deepseek.com](https://platform.deepseek.com) 重新生成
2. `.env` 文件未加载 → 确认 `config/.env` 存在且 `DEEPSEEK_API_KEY=sk-xxx`

---

### Q6: 豆包 (Doubao) 返回 `404 ModelNotOpen`

**现象**：`Your account has not activated the model doubao-seed-1-6`

**解决**：
1. 登录 [火山引擎 Ark 控制台](https://console.volcengine.com/ark)
2. 左侧菜单 → 模型推理 → 开通 `doubao-seed-1-6`（免费开通）
3. 确认 API Key 有效（`DOUBAO_API_KEY`）

---

### Q7: 文心 (Wenxin) 返回 `401 invalid_model`

**现象**：`The model does not exist or you do not have access to it`

**原因**：百度千帆的鉴权方式有两种：
- **IAM Key 格式** (`bce-v3/ALTAK-xxx/xxx`)：用于 `client_credentials` OAuth 流获取 `access_token`
- **千帆 API Key**：用于 OpenAI 兼容的 Bearer Token 方式

当前 `llm/wenxin.py` 使用 Bearer Token 方式。如果你持有的是 IAM Key，需要：
1. 去千帆控制台申请 API Key（非 IAM 类型的 Key）
2. 或改造 `llm/wenxin.py` 为 access_token 鉴权（POST to `https://aip.baidubce.com/oauth/2.0/token`）

---

### Q8: LLM 调用超时或长时间无响应

**检查**：
```bash
python scripts/diagnose_apis.py
```

**可能原因**：
1. 网络问题 — 确认能访问对应域名（api.deepseek.com / ark.cn-beijing.volces.com / dashscope.aliyuncs.com / qianfan.baidubce.com）
2. 免费额度耗尽 — 各方平台查看余额
3. 模型被限频 — 检查 `config.yaml` 中 `rate_limit.llm_qps`，默认 2 QPS

---

### Q9: 某个模型的熔断器处于 OPEN 状态

**现象**：日志中出现 `CircuitOpenError`，某个步骤被跳过。

**原因**：该模型连续失败 5 次（默认 `circuit_breaker.failure_threshold`）。

**解决**：
1. 等待 10 分钟（`circuit_breaker.cooldown_seconds`）自动冷却恢复
2. 或调熔断阈值：修改 `config.yaml` 中的 `circuit_breaker.failure_threshold` 和 `cooldown_seconds`
3. 排查根本原因：运行 `scripts/diagnose_apis.py` 确认该 API 是否可用

---

## 三、飞书问题

### Q10: `FeishuAPIError: code=99991672, ...app ticket is not ready`

**原因**：飞书应用未发布或未安装到目标多维表格空间。

**解决**：
1. 飞书开放平台 → 应用发布 → 发布应用
2. 管理员审批通过
3. 将应用安装到 Bitable 所在的空间

---

### Q11: `FeishuConfigError: Unknown Feishu table: xxx`

**原因**：代码中引用的表名与 `field_mapping.yaml` 中的键不匹配。

**解决**：
1. 检查代码中使用的表名（如 `"章节任务表"`）
2. 确认 `config/field_mapping.yaml` 中有同名条目且 `table_id` 不为空
3. 运行 `python scripts/healthcheck.py` 验证

---

### Q12: 飞书 API 返回限流错误 (429)

**现象**：`FeishuAPIError: code=429`。

**当前限流配置**：读 3 QPS / 写 2 QPS（`config.yaml`）。

**解决**：
1. 降低 `config.yaml` 中的 `feishu_read_qps` / `feishu_write_qps`
2. 增加 `feishu_read_bucket_capacity` / `feishu_write_bucket_capacity` 提高突发容忍

**注意**：飞书开放平台有自身限流规则（通常 10-100 QPS），如果系统限流低于飞书阈值，优先调整系统限流参数。

---

### Q13: `FeishuConfigError: FEISHU_APP_TOKEN is required`

**原因**：未配置多维表格 App Token。

**解决**：在 `.env` 中设置 `FEISHU_APP_TOKEN`。获取方式：打开飞书多维表格 → URL 中 `/base/` 后的字符串即为 App Token。

---

## 四、Pipeline 问题

### Q14: Pipeline 在中途失败后，重新启动如何恢复？

**答**：LLMPipeline 每步完成后立即调用 `version_store.save_step()` 写入正文版本表。重新启动后：
1. `latest_step(chapter_id)` 读取已完成的最高步骤
2. `run_chapter` 从下一步继续执行
3. 已完成的步骤不会被重复执行

**验证**：`test_pipeline_resumes_from_next_step` 测试覆盖了此场景。

---

### Q15: 同一章节被重复处理

**原因**：
1. TaskLock 获取失败 — 检查 `data/openclaw.sqlite` 中 task_lock 表是否有该章节的锁
2. TaskLock 超时（30 分钟）后自动释放，下一个扫描周期会重新获取

**排查**：
```sql
sqlite3 data/openclaw.sqlite "SELECT * FROM task_lock WHERE chapter_id='xxx';"
```

**解决**：
- 如果锁超时：等待 30 分钟自动释放，或手动删除 `DELETE FROM task_lock WHERE chapter_id='xxx';`
- 如果 pipeline 执行时间 > 30 分钟：增加 `config.yaml` 中的 `task_lock.lock_timeout_minutes`

---

### Q16: 生成的章节内容质量不佳

**因素**：
1. Prompt 模板 — 检查 `prompts/*.j2` 是否表达了期望的输出格式和质量要求
2. 模型选择 — 不同步骤对模型能力要求不同（细纲需要结构能力、润色需要文笔）
3. 章节卡质量 — 章节卡是唯一输入源，如果章节卡过于简单，输出质量受限

**调试方法**：运行 `python scripts/test_pipeline_ds_qwen.py` 查看每步输出（输出保存到 `scripts/e2e_steps/`），定位是哪个步骤质量不好。

---

## 五、发布问题

### Q17: 章节一直处于"待人工审核"状态

**原因**：
1. 人工尚未在飞书审核（需要手动将生产状态改为 `已定稿/Finalized`）
2. PublishScheduler 的扫描条件：`生产状态 ∈ {待人工审核, 已定稿}` 且 `发布状态 ∈ {未排期, 空}`

**解决**：
- 审核人登录飞书 → 章节任务表 → 审核章节 → 将 `生产状态` 改为 `已定稿/Finalized`
- 下一个 PublishScheduler 批次的 cron 时间会扫描到

---

### Q18: 已排期的章节未按计划时间发布

**检查**：
1. PublishScanner 是否在运行（`main.py` 日志中检查 `publish_scanner` 是否正常调度）
2. 计划发布时间是否已到（`计划发布时间 ≤ datetime.now()`）
3. 发布状态是否为 `待发布/Pending Publish`

---

### Q19: 发布失败 (Publish Failed)

**原因**：
1. `DeviceController` 调红手指 API 失败（网络/endpoint 不可达）
2. 重试次数达到 `publish_max_attempts`（默认 3）

**排查**：
1. 检查 `HONGSHOUZHI_ENDPOINT` 是否可达：`curl http://192.168.x.x:8080/publish`
2. 查看飞书运行日志表，搜索 `publish_scanner` 节点的错误信息
3. 查看章节任务表中该章的 `错误信息` 和 `流程重试次数`

---

### Q20: DeviceController 静默跳过发布

**现象**：章节标记成功，但实际未发布。

**原因**：`HONGSHOUZHI_ENDPOINT` 为空时，`DeviceController.publish_chapter()` 直接返回，不抛错。这是设计行为（支持 dry-run 模式）。

**验证**：
```bash
echo $HONGSHOUZHI_ENDPOINT  # 或 Windows: echo %HONGSHOUZHI_ENDPOINT%
```

---

## 六、性能问题

### Q21: SQLite 数据库被锁 (database is locked)

**原因**：多个并发操作同时写 SQLite。

**OpenClaw 中的 SQLite 使用**：
- `ReadCache`：每次操作打开/关闭连接
- `TaskLock`：每次 acquire/release 打开/关闭连接

**解决**：
- 在生产环境中通常不是问题（单线程 asyncio，GIL 保护）
- 如果确实出现：增加 `sqlite3.connect(timeout=10)` 参数

---

### Q22: 飞书 API 调用过多导致限流

**已知全量拉取点**：
- `FeishuVersionStore._latest_record` — 每次查最新版本时全量拉正文版本表
- `SettingsExtractor._find_match` — 每次匹配时全量拉对应实体表
- `Watchdog` 四项检查 — 每次全量拉章节任务表

**缓解措施**：
- 为 FeishuClient 注入 `ReadCache`，缓存 TTL 内重复查询不调 API
- 数据量大时（>1 万条），在 `list_records` 层加飞书 filter 参数按章节 ID 过滤

---

### Q23: 内存占用增长

**可能原因**：
- `list_records` 全量拉取导致内存中持有大量记录
- httpx.AsyncClient 连接池未关闭

**检查**：
- `ProductionScanner.close()` 在 shutdown 时被调用
- 生产环境使用 systemd 的 `Restart=always` 定期回收

---

## 七、数据一致性问题

### Q24: GuardLayer 阻止了正常的写入

**现象**：`PermissionError: content locked; forbidden fields: ...`

**解决**：
1. 如果确实需要在内容锁定时修改章节内容：在飞书将 `内容锁定状态` 改为 `否/No`
2. 如果需要在核心人物上修改非白名单字段：在飞书将 `来源状态` 改为非 `人工创建`，或将 `是否核心` 改为 `否`

---

### Q25: SettingsExtractor 没有生成任何实体

**检查**：
1. 校对稿是否存在（正文版本表中有 `版本类型=校对稿` 的记录）
2. 是否已经提取过（运行日志表中有 `extract-{chapter_id}` 且状态=成功/Success）
3. LLM 返回的 JSON 是否为空数组（正常 — 章节可能没有新实体）

---

### Q26: PublishScheduler 日更上限未生效

**原因**：小说总览表中 `日更目标` 字段为空或为 0。

**解决**：在飞书小说总览表中为每本小说设置 `日更目标`（数字类型），默认值为 1。

---

## 八、快速诊断命令参考

```bash
# 环境检查
python scripts/healthcheck.py                      # 飞书 + 表映射 + 权限
python scripts/acceptance_test.py                  # 模块导入 + 无 stub

# API 诊断
python scripts/diagnose_apis.py                    # 4 个 LLM API 逐一测试

# Pipeline 诊断
python scripts/test_pipeline_ds_qwen.py             # 真实 API 6 步链路
# 输出在 scripts/test_pipeline_ds_qwen_output.txt
# 每步正文在 scripts/e2e_steps/

# 测试运行
python -m pytest tests/ -v                          # 140 个单元测试
python -m pytest tests/ -v -k "publish"             # 只跑发布相关测试
python -m pytest tests/ -v -k "watchdog"            # 只跑 Watchdog 测试

# 类型检查
python -m mypy core/ business/ llm/ main.py

# 查看日志
tail -f logs/openclaw.log                           # 本地日志

# 查看 SQLite 状态
sqlite3 data/openclaw.sqlite ".tables"              # 列出所有表
sqlite3 data/openclaw.sqlite "SELECT COUNT(*) FROM task_lock;"  # 当前锁数量
sqlite3 data/openclaw.sqlite "SELECT * FROM task_lock;"          # 查看所有锁
```
