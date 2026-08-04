# OpenClaw 小说闭环系统

OpenClaw 是一个单进程 Python 编排服务，以飞书多维表格作为业务数据源，通过 ADB 控制番茄作家助手，完成章节生成、人工审核、排期、发布、状态对账和异常恢复。

## 环境要求

- Windows 10/11
- Python 3.10 或更高版本
- Android platform-tools（ADB）
- 已登录番茄作家助手的云手机
- 飞书应用及多维表格访问权限
- 已配置的模型 API

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item config\.env.example config\.env
```

填写 `config/.env` 后，先执行健康检查：

```powershell
.\.venv\Scripts\python.exe scripts\healthcheck.py
```

## 运行

单周期运行：

```powershell
.\.venv\Scripts\python.exe closed_loop.py --once
```

无人值守运行：

```powershell
.\.venv\Scripts\python.exe closed_loop.py --continuous
```

程序会从 HOME 键开始重置设备页面，打开番茄作家助手，并按飞书任务状态执行生成、发布或状态对账。章节级幂等检查用于避免重复发布。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check business device_gateway core tests
.\.venv\Scripts\python.exe -m mypy business device_gateway core
```

## 配置

- `config/config.yaml`：扫描周期、设备映射、并发、重试和发布窗口。
- `config/field_mapping.yaml`：飞书表格及字段映射。
- `config/.env`：本地密钥，不进入 Git。
- `device_gateway/ui_coordinates.yaml`：720×1280 参考分辨率下的番茄页面动作。

云手机端口变化后，需要同步修改 `config/config.yaml` 中的 `adb.devices`，并更新飞书账号管理表的“红手指设备ID”。

## 目录

- `business/`：生产、审核、排期、发布和看门狗逻辑。
- `core/`：飞书客户端、限流、缓存、锁和日志。
- `device_gateway/`：ADB 驱动、番茄状态机和页面恢复。
- `llm/`：模型适配器。
- `scripts/`：健康检查、数据修复和运维脚本。
- `tests/`：自动化测试。
- `docs/`：运维及验收文档。

详细操作见 [`docs/运维操作手册.md`](docs/运维操作手册.md)。
