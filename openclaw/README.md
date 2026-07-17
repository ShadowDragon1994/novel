# OpenClaw

OpenClaw（小龙虾）是一个单进程 Python 编排服务，以飞书多维表为唯一业务数据源，使用 SQLite 承担读缓存、任务锁和发布去重。

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy config\.env.example config\.env
python main.py
```

## Tests

```powershell
python -m pytest -q
```

`pyproject.toml` sets `pythonpath = ["."]`, so tests can be run from the `openclaw/` directory without extra environment variables.

## Architecture

- `core/`: 可复用积木层，包含飞书客户端、缓存、锁、限流、断路器、日志。
- `business/`: 小说业务层，包含 GuardLayer、LLM 生产、排班、发布、设定回写、监控。
- `llm/`: 模型适配层，所有模型通过 `LLMClient` 接口调用。
- `config/`: 运行配置、字段映射和本地密钥。
- `tests/`: 优先覆盖 GuardLayer、TaskLock、CircuitBreaker、RateLimiter。
