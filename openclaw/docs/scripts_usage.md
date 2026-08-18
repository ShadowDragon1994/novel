# 脚本使用说明文档

本文档说明 `D:\WorkSpace\Code\novel\openclaw\scripts` 目录下脚本的用途、调用方式和适用场景。

## 0. 通用运行环境

在项目根目录执行：

```powershell
cd D:\WorkSpace\Code\novel\openclaw
```

推荐使用项目虚拟环境：

```powershell
.\.venv\Scripts\python.exe <脚本路径> <参数>
```

ADB 路径建议配置：

```powershell
$env:ADB_PATH="C:\Users\Administrator\AppData\Local\Android\Sdk\platform-tools\adb.exe"
```

云手机连接示例：

```powershell
& $env:ADB_PATH connect 127.0.0.1:61489
```

---

# 一、主流程脚本

## 1. run_full_flow_once.py

统一完整流程入口。推荐优先使用这个脚本。

路径：

```text
scripts\run_full_flow_once.py
```

### 适用场景

- 新书开题完整流程。
- 旧书续写下一章。
- 自动判断新书/旧书。
- 从生成七稿到 ADB 发布。

### 支持模式

```text
auto            自动判断
new-book        强制新书开题
continue-book   强制旧书续写
```

### 自动判断逻辑

```text
1. 指定 --mode new-book，则走新书流程。
2. 指定 --mode continue-book，则走续写流程。
3. 指定 --plan-path 且 plan 已立项通过，则走续写流程。
4. 本地存在最新已立项 plan，则走续写流程。
5. 番茄当前作品已有章节，则走续写流程。
6. 否则走新书流程。
```

### 新书流程命令

```powershell
.\.venv\Scripts\python.exe scripts\run_full_flow_once.py --device-id 127.0.0.1:61489 --mode new-book
```

### 旧书续写命令

```powershell
.\.venv\Scripts\python.exe scripts\run_full_flow_once.py --device-id 127.0.0.1:61489 --mode continue-book --plan-path output\topic_development\topic_development_20260817-121402.json
```

### 自动模式命令

```powershell
.\.venv\Scripts\python.exe scripts\run_full_flow_once.py --device-id 127.0.0.1:61489 --mode auto
```

### Dry-run 验证

只验证参数和模式判断，不执行真实发布：

```powershell
.\.venv\Scripts\python.exe scripts\run_full_flow_once.py --device-id 127.0.0.1:61489 --mode continue-book --plan-path output\topic_development\topic_development_20260817-121402.json --dry-run
```

### 常用参数

| 参数 | 说明 |
|---|---|
| `--device-id` | ADB 设备 ID，例如 `127.0.0.1:61489` |
| `--mode` | `auto` / `new-book` / `continue-book` |
| `--plan-path` | 已立项 plan 文件路径，续写模式推荐填写 |
| `--chapter-number` | 手动指定章节号，不填则自动读取当前最新章节 + 1 |
| `--chapter-title` | 手动指定章节标题 |
| `--topic-index` | 新书模式下选择第几个候选选题，默认 0 |
| `--chapter-count` | 新书模式下生成多少章大纲，默认 12 |
| `--max-scrolls` | 开书灵感采集滚动次数 |
| `--topic-limit` | 选题候选数量 |
| `--dry-run` | 只测试流程判断，不实际执行 |

### 输出

脚本会输出 JSON 报告，并生成报告文件：

```text
output\full_flow_reports\full_flow_report_*.json
```

报告包含：

```text
执行模式
设备 ID
发布状态
流程节点
中间产物路径
运行时间
```

---

# 二、分段流程脚本

这些脚本用于单独执行某个阶段，适合调试或人工验收。

## 2. collect_fanqie_inspiration.py

采集番茄开书灵感、榜单、热词，并生成选题候选。

路径：

```text
scripts\collect_fanqie_inspiration.py
```

### ADB 实时采集

```powershell
.\.venv\Scripts\python.exe scripts\collect_fanqie_inspiration.py --device-id 127.0.0.1:61489 --max-scrolls 2 --limit 10
```

### 使用已有快照分析

```powershell
.\.venv\Scripts\python.exe scripts\collect_fanqie_inspiration.py --analyze-snapshot output\topic_discovery\fanqie_inspiration_snapshot_xxx.json --limit 10
```

### 输出

```text
output\topic_discovery\fanqie_inspiration_snapshot_*.json
output\topic_discovery\topic_candidates_*.json
```

---

## 3. develop_topic_plan.py

执行市场验证、立项打分、世界观构建、章节大纲生成。

路径：

```text
scripts\develop_topic_plan.py
```

### 命令

```powershell
.\.venv\Scripts\python.exe scripts\develop_topic_plan.py --topics-path output\topic_discovery\topic_candidates_20260817-121351.json --topic-index 0 --chapter-count 12
```

### 输出

```text
output\topic_development\topic_development_*.json
```

该文件包含：

```text
market_validation       市场验证
worldview               世界观
chapter_outlines        章节大纲 / 细纲
```

---

## 4. produce_chapters_from_plan.py

根据已立项 plan 生成章节七稿。

路径：

```text
scripts\produce_chapters_from_plan.py
```

### 命令

```powershell
.\.venv\Scripts\python.exe scripts\produce_chapters_from_plan.py --plan-path output\topic_development\topic_development_20260817-121402.json --limit 1
```

### 输出

```text
output\chapter_production\YYYYMMDD-HHMMSS\chapter_001
```

章节目录包含：

```text
01_outline.txt       细纲稿
02_draft.txt         初稿
03_consistency.txt   一致性稿
04_proofread.txt     校对稿
05_polish.txt        润色稿
06_compliance.txt    合规稿
07_final.txt         终稿
final_content.txt    纯发布正文
chapter_artifact.json
```

---

## 5. publish_local_chapter.py

把本地正文通过 ADB 发布到番茄作家助手。

路径：

```text
scripts\publish_local_chapter.py
```

### 命令

```powershell
.\.venv\Scripts\python.exe scripts\publish_local_chapter.py --device-id 127.0.0.1:61489 --chapter-number 105 --title "完整流程测试" --content-path output\chapter_production\20260817-121414\chapter_001\final_content.txt
```

### 注意

- `--content-path` 应使用 `final_content.txt`，不要直接发布带阶段标题的 `07_final.txt`。
- 脚本会选择“内容是否使用 AI：有使用 AI”。
- 成功后通常返回：

```text
status=审核中
```

---

## 6. publish_live_chapter.py

从飞书章节任务表读取章节并发布。

路径：

```text
scripts\publish_live_chapter.py
```

### 命令

```powershell
.\.venv\Scripts\python.exe scripts\publish_live_chapter.py <chapter_id> <device_id> <account_id>
```

示例：

```powershell
.\.venv\Scripts\python.exe scripts\publish_live_chapter.py CHAPTER-001 127.0.0.1:61489 ACCOUNT-001
```

### 适用场景

- 已接入飞书数据表。
- 章节任务表已有章节 ID、章节号、章节名。

---

# 三、验收、健康检查和无人值守脚本

## 7. healthcheck.py

检查环境、配置、服务、表结构等基础状态。

```powershell
.\.venv\Scripts\python.exe scripts\healthcheck.py
```

适合部署后第一步运行。

---

## 8. acceptance_test.py

验收测试脚本，用于检查项目关键能力是否可运行。

```powershell
.\.venv\Scripts\python.exe scripts\acceptance_test.py
```

适合交付前运行。

---

## 9. run_closed_loop.ps1

PowerShell 闭环运行脚本。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_closed_loop.ps1
```

适合 Windows 本机定时任务或手动启动闭环流程。

---

## 10. install_unattended_task.ps1

安装无人值守任务。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_unattended_task.ps1
```

适合将项目加入 Windows 定时任务。

---

# 四、飞书/账号/数据维护脚本

## 11. bootstrap_feishu.py

初始化或检查飞书相关表结构和基础数据。

```powershell
.\.venv\Scripts\python.exe scripts\bootstrap_feishu.py
```

---

## 12. sync_account_fields.py

同步账号表字段。

```powershell
.\.venv\Scripts\python.exe scripts\sync_account_fields.py
```

适合账号表新增字段后执行。

---

## 13. diagnose_apis.py

诊断 API 配置和接口连通性。

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_apis.py
```

---

# 五、修复和维护脚本

## 14. repair_mojibake_acceptance_batch.py

修复历史验收批次中的乱码内容。

```powershell
.\.venv\Scripts\python.exe scripts\repair_mojibake_acceptance_batch.py
```

适合历史数据出现中文乱码时使用。

---

## 15. revise_published_chapters.py

修订已发布章节。

```powershell
.\.venv\Scripts\python.exe scripts\revise_published_chapters.py
```

适合平台已发布内容需要修订时使用。

---

## 16. resume_ch2.py

历史调试脚本，用于恢复或继续第 2 章流程。

```powershell
.\.venv\Scripts\python.exe scripts\resume_ch2.py
```

不建议日常使用，除非明确需要恢复旧测试场景。

---

# 六、历史测试脚本

以下脚本主要用于早期开发测试或模型链路测试，不建议业务人员直接使用。

## 17. test_pipeline_full.py

完整管线测试脚本。

```powershell
.\.venv\Scripts\python.exe scripts\test_pipeline_full.py
```

输出参考：

```text
scripts\test_pipeline_full_output.txt
```

---

## 18. test_pipeline_ds_qwen.py

DeepSeek/Qwen 管线测试脚本。

```powershell
.\.venv\Scripts\python.exe scripts\test_pipeline_ds_qwen.py
```

输出参考：

```text
scripts\test_pipeline_ds_qwen_output.txt
```

---

## 19. test_pipeline_e2e.py

端到端测试脚本。

```powershell
.\.venv\Scripts\python.exe scripts\test_pipeline_e2e.py
```

---

## 20. test_3chapters.py

三章节生成测试脚本。

```powershell
.\.venv\Scripts\python.exe scripts\test_3chapters.py
```

输出参考：

```text
scripts\test_3chapters_output.txt
```

---

# 七、推荐使用顺序

## 新书开题并发布第一章

推荐直接使用：

```powershell
.\.venv\Scripts\python.exe scripts\run_full_flow_once.py --device-id 127.0.0.1:61489 --mode new-book
```

## 已开题旧书续写下一章

推荐直接使用：

```powershell
.\.venv\Scripts\python.exe scripts\run_full_flow_once.py --device-id 127.0.0.1:61489 --mode continue-book --plan-path output\topic_development\topic_development_20260817-121402.json
```

## 只生成七稿，不发布

```powershell
.\.venv\Scripts\python.exe scripts\produce_chapters_from_plan.py --plan-path output\topic_development\topic_development_20260817-121402.json --limit 1
```

## 只发布已有正文

```powershell
.\.venv\Scripts\python.exe scripts\publish_local_chapter.py --device-id 127.0.0.1:61489 --chapter-number 106 --title "章节标题" --content-path output\chapter_production\xxxx\chapter_001\final_content.txt
```

---

# 八、产物目录说明

## 选题采集

```text
output\topic_discovery
```

## 市场验证 / 世界观 / 章节大纲

```text
output\topic_development
```

## 章节七稿

```text
output\chapter_production
```

## 完整流程报告

```text
output\full_flow_reports
```

## ADB UI 验证日志

```text
logs
```

---

# 九、日常使用建议

1. 业务人员优先使用 `run_full_flow_once.py`。
2. 技术人员调试时再使用分段脚本。
3. 发布正文必须使用 `final_content.txt`。
4. `07_final.txt` 是给人看的终稿，包含阶段标题和发布检查说明。
5. 如果平台提示重复，需要补充跨章节去重或生成差异化正文后重发。
6. 每次正式无人值守前，先跑：

```powershell
.\.venv\Scripts\python.exe scripts\run_full_flow_once.py --device-id 设备ID --mode continue-book --plan-path 立项文件 --dry-run
```
