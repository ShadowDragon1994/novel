# OpenClaw

OpenClaw（小龙虾）是一个单进程 Python 编排服务，以飞书多维表为唯一业务数据源，使用 SQLite 承担读缓存、任务锁和发布去重。

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy config\.env.example config\.env
python closed_loop.py --once
```

Use `python closed_loop.py --continuous` for unattended operation. The closed-loop
entrypoint starts the device gateway, connects every ADB device in
`config/config.yaml`, runs an immediate production/publish cycle, and then keeps the
configured scanners scheduled. Stop it with `Ctrl+C`; the scheduler, HTTP clients,
and gateway are closed before exit.

On Windows, `scripts/run_closed_loop.ps1` is the background-service launcher used
by the `OpenClaw Novel Closed Loop` logon task. Its combined service log is written
to `logs/closed_loop.service.log`.

## Tests

```powershell
python -m pytest -q
```

## Device Gateway

The local gateway is disabled from publishing until a platform workflow is configured. Start its ADB health and
device-status endpoints on loopback with:

```powershell
python -m uvicorn device_gateway.app:app --host 127.0.0.1 --port 8080
```

Set `ADB_PATH` when `adb` is not available on `PATH`, then verify `GET /health` and
`GET /devices/{device_id}` before enabling the publish scanner.

Known UI-only actions are stored in `device_gateway/ui_coordinates.yaml`. Each coordinate is bound to its source
page and reference resolution; `CoordinateProfile.resolve()` scales it for the connected device. The Fanqie Writer
`start_creation` action is valid only after `open_works` reaches `works_page`, and the editor must then expose
`下一步` or `AI工具箱` before the workflow continues.

`pyproject.toml` sets `pythonpath = ["."]`, so tests can be run from the `openclaw/` directory without extra environment variables.

## Architecture

- `core/`: 可复用积木层，包含飞书客户端、缓存、锁、限流、断路器、日志。
- `business/`: 小说业务层，包含 GuardLayer、LLM 生产、排班、发布、设定回写、监控。
- `llm/`: 模型适配层，所有模型通过 `LLMClient` 接口调用。
- `config/`: 运行配置、字段映射和本地密钥。
- `tests/`: 优先覆盖 GuardLayer、TaskLock、CircuitBreaker、RateLimiter。

完整的部署、运行、设备换端口、日志分析和故障处理说明见
[`docs/运维操作手册.md`](docs/运维操作手册.md)。
