# OpenClaw 第五周开发计划：PublishScanner + Watchdog（最终阶段）

> 前置条件：阶段 4 终审通过（118 个测试全绿 + ruff/mypy 双清）
> 目标：完成发布执行链路 + 系统守护，全部 5 个调度任务正常运行
> 周期：7 天

---

## 一、本周总览

```
Day 1-3   PublishScanner    → 扫描待发布章节 → 调 DeviceController → 写发布记录
Day 4-6   Watchdog          → 存稿/故障/熔断/API 四项监控 → 运行日志告警
Day 7     全量联调 + 收尾   → 118 → 目标 140+
```

---

## 二、Day 1-3：PublishScanner — 发布执行器

### 2.1 背景

**现状：** `business/publish_scanner.py` 是 stub，`run_once()` raise NotImplementedError。

**业务链路：**
```
PublishScheduler → 章节.发布状态 = 待发布 + 计划发布时间
PublishScanner → 扫描 发布状态=待发布 且 计划发布时间 ≤ now
              → 调 DeviceController.publish_chapter()
              → 写发布记录表（成功/失败）
              → 更新章节.发布状态 = 发布成功/发布失败
```

**防重机制：** 发布前查发布记录表，同一章节已有成功记录则跳过。

### 2.2 实现

| # | 任务 | 文件 | 验收 |
|---|---|---|---|
| 1 | 实现 `PublishScanner.__init__`：注入 feishu_client + guard_layer + device_controller | `business/publish_scanner.py` | DI 完成 |
| 2 | 实现 `run_once()` 主逻辑：扫描 → 过滤到期 → 去重 → 执行 → 写结果 | 同上 | 端到端 |
| 3 | 扫描 `章节任务表`：发布状态=待发布 且 计划发布时间 ≤ now | 同上 | 只捞出到期章节 |
| 4 | 去重：查发布记录表，跳过已有成功记录的章节 | 同上 | 不重复发布 |
| 5 | 调 `DeviceController.publish_chapter(chapter_id, account_id)` | 同上 | 调用成功 |
| 6 | 成功 → GuardLayer.write(发布状态=发布成功) + 创建发布记录 | 同上 | 两步原子 |
| 7 | 失败 → GuardLayer.write(发布状态=发布失败, 错误信息) + 创建失败记录 | 同上 | 重试≤3 |
| 8 | 重试逻辑：流程重试次数 +1；≥3 → 发布失败 | 同上 | 永不死循环 |

### 2.3 核心代码结构

```python
class PublishScanner:
    def __init__(self, feishu_client, guard_layer, device_controller):
        self.feishu_client = feishu_client
        self.guard_layer = guard_layer
        self.device = device_controller

    async def run_once(self) -> list[str]:
        ready = await self._ready_chapters()
        if not ready:
            return []
        results = await asyncio.gather(
            *(self._publish_one(record) for record in ready),
            return_exceptions=True,
        )
        return [r for r in results if isinstance(r, str)]

    async def _ready_chapters(self) -> list[dict]:
        records = await self.feishu_client.list_records("章节任务表")
        now = datetime.now()
        ready = []
        for record in records:
            fields = record.get("fields", record)
            if fields.get("发布状态") in {"待发布/Pending Publish", "待发布"}:
                planned = self._parse_datetime(fields.get("计划发布时间"))
                if planned and planned <= now:
                    ready.append(record)
        return ready

    async def _publish_one(self, record) -> str | None:
        fields = record.get("fields", record)
        chapter_id = str(fields["章节ID"])
        # 1. 去重
        if await self._already_published(chapter_id):
            return None
        # 2. 调设备
        novel_id = str(fields.get("小说ID") or "")
        account_id = await self._resolve_account(novel_id)
        if not account_id:
            return None
        try:
            await self.device.publish_chapter(chapter_id, account_id)
            await self._mark_success(record)
        except Exception as exc:
            await self._mark_failure(record, exc)
        return chapter_id
```

### 2.4 测试（新增 10-12 个）

| 测试 | 覆盖 |
|---|---|
| `test_scanner_picks_ready_chapter` | 计划发布时间已到 → 被选中 |
| `test_scanner_skips_future_chapter` | 计划发布时间未到 → 跳过 |
| `test_scanner_skips_already_published` | 发布记录表已有成功记录 → 跳过 |
| `test_scanner_calls_device_controller` | DeviceController.publish_chapter 被调用 |
| `test_scanner_marks_success_on_device_ok` | 发布状态 → 发布成功 + 创建发布记录 |
| `test_scanner_marks_failure_on_device_error` | 发布状态 → 发布失败 + 错误信息 |
| `test_scanner_retries_up_to_max` | 重试次数递增；≥3 → 发布失败 |
| `test_scanner_handles_empty_queue` | 无待发布章节不抛错 |
| `test_scanner_resolves_account_from_novel` | account_id 从小说总览表/账号管理表查 |
| `test_scanner_guards_lock_timeout_on_publish` | 超时后释放锁 |

---

## 三、Day 4-6：Watchdog — 系统守护器

### 3.1 背景

**现状：** `business/watchdog.py` 是 stub，`run_once()` raise NotImplementedError。

**四项监控：**
1. **存稿水位** — 全局待发布+待人工审核章节数 < safety_threshold(6) → 告警
2. **故障章节** — 章节任务表有错误信息/流程重试≥3 的章节 → 汇总告警
3. **熔断状态** — 扫描所有 LLM Client 的 CircuitBreaker 状态 → OPEN 时告警
4. **Feishu 连通性** — 尝试 token 刷新 → 失败告警

### 3.2 实现

| # | 任务 | 验收 |
|---|---|---|
| 1 | 实现 `Watchdog.__init__`：注入 feishu_client + 可选 clients 引用 | DI 完成 |
| 2 | 实现存稿水位检查：`list_records(章节任务表)` → count 待人工审核+待发布 | 低于阈值写告警日志 |
| 3 | 实现故障章节扫描：查错误信息非空/重试次数≥3 的章节 | 汇总到日志 |
| 4 | 实现熔断状态检查：`clients` 中任一 `circuit_breaker.state == OPEN` → 告警 | 含模型名 + 剩余冷却时间 |
| 5 | 实现 Feishu 连通性：调 `tenant_access_token()` 看是否抛错 | 连通性异常告警 |
| 6 | 所有告警写运行日志表（节点名称=watchdog） | 日志可追溯 |
| 7 | 严重级别：存稿低于 pause_threshold(3) → 执行状态=严重告警 | 区分 warn/critical |

### 3.3 核心代码结构

```python
class Watchdog:
    def __init__(self, feishu_client, clients=None):
        self.feishu_client = feishu_client
        self.clients = clients or {}

    async def run_once(self) -> WatchdogReport:
        report = WatchdogReport()
        # 1. 存稿水位
        inventory = await self._check_inventory()
        if inventory <= self.pause_threshold:
            report.critical("inventory", f"存稿仅剩 {inventory} 章")
        elif inventory <= self.safety_threshold:
            report.warn("inventory", f"存稿不足 {inventory} 章")
        # 2. 故障章节
        failed = await self._check_failed_chapters()
        if failed:
            report.warn("failures", f"{len(failed)} 章有错误")
        # 3. 熔断
        for name, client in self.clients.items():
            breaker = getattr(client, "circuit_breaker", None)
            if breaker and breaker.state == "open":
                report.warn("circuit", f"{name} 已熔断")
        # 4. Feishu
        try:
            await self.feishu_client.tenant_access_token()
        except Exception as exc:
            report.critical("feishu", str(exc))
        # 5. 写日志
        await self._write_report(report)
        return report
```

### 3.4 测试（新增 10-12 个）

| 测试 | 覆盖 |
|---|---|
| `test_watchdog_detects_low_inventory` | 存稿 < safety → warn |
| `test_watchdog_detects_critical_inventory` | 存稿 < pause → critical |
| `test_watchdog_detects_failed_chapters` | 扫描到有错误信息的章节 |
| `test_watchdog_detects_circuit_open` | 任一 client 熔断 → warn |
| `test_watchdog_detects_feishu_connectivity_loss` | token 刷新失败 → critical |
| `test_watchdog_writes_report_to_log_table` | 运行日志表有 watchdog 记录 |
| `test_watchdog_healthy_when_all_ok` | 全部正常 → 无告警 |
| `test_watchdog_reports_critical_over_warning` | 严重 > 警告 |
| `test_watchdog_tracks_multiple_circuit_breakers` | 多个模型同时熔断 |
| `test_watchdog_handles_missing_clients` | 不传 clients → 不崩溃 |

---

## 四、集成：main.py 全量激活

阶段 5 完成后，`main.py` 的 5 个调度任务**全部自动生效**：

```python
scheduler.add_job(production_scanner.run_once, "interval", seconds=300)   # ✅ 阶段 3
scheduler.add_job(publish_scanner.run_once, "interval", seconds=300)      # ✅ 阶段 5 → 自动激活
scheduler.add_job(publish_scheduler.generate_daily_plan, "cron", ...)     # ✅ 阶段 4
scheduler.add_job(watchdog.run_once, "interval", seconds=60)              # ✅ 阶段 5 → 自动激活
```

`add_job_if_implemented` 检测到 `NotImplementedError` 已消失，自动恢复调度。无需改 `main.py`。

### 验证

```python
# test_main.py 新增
def test_create_scheduler_registers_all_five_jobs():
    scheduler = create_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {
        "production_scanner", "publish_scanner",
        "publish_plan_evening", "publish_plan_morning",
        "watchdog",
    }
```

---

## 五、目录变更

```
openclaw/
├── business/
│   ├── publish_scanner.py     ← 实现（从 stub 到完整）
│   └── watchdog.py            ← 实现（从 stub 到完整）
├── tests/
│   ├── test_publish_scanner.py   ← 新增：10-12 个测试
│   ├── test_watchdog.py          ← 新增：10-12 个测试
│   └── test_main.py              ← +1（五任务全量验证）
└── main.py                      ← 无需改动（自动激活）
```

---

## 六、第五周结束时的状态（项目收官）

```
✅ PublishScanner 完成：扫描到期章节 → 调 DeviceController → 写发布记录 → 更新状态
✅ Watchdog 完成：存稿/故障/熔断/API 四项监控告警
✅ main.py 5 个调度任务全部正常运行
✅ 20-23 个新测试（118 → 138-141）
✅ ruff / mypy clean
✅ 全部 6 个 stub 清零（无任何 NotImplementedError 残留）
🎉 OpenClaw 单进程编排出书服务全部完工
```

---

## 七、本周测试目标

| 文件 | 本周 | 累计 |
|---|---|---|
| 已有文件 | 118 | 118 |
| `test_publish_scanner.py` | 10-12 | 128-130 |
| `test_watchdog.py` | 10-12 | 138-142 |
| `test_main.py` | +1 | 139-143 |
| **总计** | **21-25** | **139-143** |
