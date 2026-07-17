# OpenClaw 部署运行指导书

> 版本：V1.1
> 目标环境：Windows 10+ / Linux (Ubuntu 20.04+)
> Python：3.9+

---

## 一、环境要求

### 1.1 基础依赖

| 组件 | 最低版本 | 说明 |
|------|---------|------|
| Python | 3.9 | 3.11 推荐（消除 `X \| None` 语法限制） |
| pip | 21.0+ | |
| git | 任意 | 版本管理 |

### 1.2 外部服务账号

| 服务 | 用途 | 获取方式 |
|------|------|---------|
| 飞书开放平台 | Bitable 数据源 | [open.feishu.cn](https://open.feishu.cn) → 创建企业自建应用 → 获取 App ID / App Secret |
| 飞书 Bitable | 数据存储 | 创建多维表格 → 获取 App Token |
| DeepSeek API | 细纲/初稿/润色 | [platform.deepseek.com](https://platform.deepseek.com) → API Keys |
| 火山引擎 Ark | 初稿/润色 | [console.volcengine.com](https://console.volcengine.com) → Ark 模型推理 → 开通豆包 |
| 阿里云 DashScope | 一致性/合规/校对 | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) → API-KEY |
| 百度千帆 | 合规检查 | [console.bce.baidu.com/qianfan](https://console.bce.baidu.com/qianfan) → API Key |
| 红手指/ADB | 发布执行 | `HONGSHOUZHI_ENDPOINT`（可选，未配置时发布步骤静默跳过） |

---

## 二、安装

### 2.1 获取代码

```bash
git clone <your-repo-url> openclaw
cd openclaw
```

### 2.2 安装依赖

```bash
pip install -r requirements.txt
# 或逐项安装：
pip install httpx pyyaml pydantic python-dotenv jinja2 tenacity loguru apscheduler
```

### 2.3 安装开发依赖（可选，用于测试和类型检查）

```bash
pip install pytest pytest-asyncio mypy types-PyYAML ruff
```

---

## 三、配置

### 3.1 环境变量 (`config/.env`)

```bash
cp config/.env.example config/.env
# 编辑 config/.env，填入真实 API Key
```

```
FEISHU_APP_ID=cli_a92d5fff9838dcc6          # 飞书应用 App ID
FEISHU_APP_SECRET=QTOFaqYoAu9ah388anRl...   # 飞书应用 App Secret
FEISHU_APP_TOKEN=VfdObtGiPard0LsNqMpc3...   # 飞书多维表格 App Token

DEEPSEEK_API_KEY=sk-2a62094cb621416c...     # DeepSeek API Key
DOUBAO_API_KEY=591b5732-acad-4d38-...       # 豆包 API Key (火山引擎 Ark)
QWEN_API_KEY=sk-0e12ca67eabe4adea4...       # 千问 API Key (阿里云 DashScope)
WENXIN_API_KEY=bce-v3/ALTAK-kPUHS87Z...     # 文心 API Key (百度千帆)

HONGSHOUZHI_ENDPOINT=http://192.168.1.100:8080   # 红手指发布服务地址（可选）
```

### 3.2 可调节参数 (`config/config.yaml`)

```yaml
scan:
  production_interval_seconds: 300    # 生产扫描间隔（秒）
  publish_interval_seconds: 300       # 发布扫描间隔（秒）

concurrency:
  per_novel_max: 2                    # 单本小说最大并发
  global_max: 5                       # 全局最大并发

retry:
  llm_max_attempts: 3                 # LLM 调用最大重试
  publish_max_attempts: 3             # 发布最大重试

circuit_breaker:
  failure_threshold: 5                # 连续失败 N 次 → 熔断
  cooldown_seconds: 600               # 熔断冷却时间（秒）

rate_limit:
  feishu_read_qps: 3                  # 飞书读 QPS
  feishu_write_qps: 2                 # 飞书写 QPS
  llm_qps: 2                          # LLM 调用 QPS

cache:
  read_cache_ttl_seconds: 60          # 读缓存有效期（秒）

task_lock:
  lock_timeout_minutes: 30            # 任务锁超时（分钟）

inventory:
  safety_threshold: 6                 # 存稿安全线（低于此数 → warn）
  pause_threshold: 3                  # 存稿停工线（低于此数 → critical）

publish_window:
  earliest: 08:30                     # 最早发布时间
  latest: '22:00'                     # 最晚发布时间
  min_gap_hours: 6                    # 同本相邻章节最小间隔（小时）
  jitter_minutes: [5, 15]            # 发布时间随机偏移范围（分钟）
```

### 3.3 飞书表格初始化

飞书 Bitable 需要按 `config/field_mapping.yaml` 中定义的 16 张表创建。每张表必须包含对应的字段（field_id 在飞书创建字段后自动生成）。

```bash
# 飞书操作步骤:
# 1. 在飞书创建多维表格 → 获取 App Token
# 2. 按 field_mapping.yaml 创建 16 张子表
# 3. 每张表按 yaml 定义创建字段 → 记录 field_id 填入 yaml
# 4. 运行 healthcheck 验证
```

---

## 四、启动前检查

```bash
# 1. 健康检查（验证飞书连通 + 表映射 + 写入权限 + 日志双写）
python scripts/healthcheck.py

# 2. 验收测试（验证所有模块可导入、无 NotImplementedError）
python scripts/acceptance_test.py

# 3. API 诊断（验证 4 个 LLM API 连通性）
python scripts/diagnose_apis.py

# 4. 初始化测试数据（可选）
python scripts/bootstrap_feishu.py --count 10 --dry-run   # 预览
python scripts/bootstrap_feishu.py --count 10             # 实际创建
```

---

## 五、启动服务

### 5.1 直接运行

```bash
cd openclaw
python main.py
```

### 5.2 Windows 服务（NSSM）

```powershell
# 下载 nssm.exe → 安装服务
nssm install OpenClaw
# Application: C:\Python39\python.exe
# Arguments: main.py
# Start directory: C:\Users\xingyu.zhang\Documents\novel\openclaw
nssm start OpenClaw
```

### 5.3 Linux systemd

```ini
# /etc/systemd/system/openclaw.service
[Unit]
Description=OpenClaw Novel Production Orchestrator
After=network.target

[Service]
Type=simple
User=openclaw
WorkingDirectory=/opt/openclaw
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now openclaw
sudo systemctl status openclaw
```

### 5.4 Docker（可选）

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

```bash
docker build -t openclaw .
docker run -d --name openclaw -v $(pwd)/config:/app/config -v $(pwd)/data:/app/data openclaw
```

---

## 六、运行时行为

启动后，APScheduler 注册 5 个定时任务：

| 任务 ID | 触发频率 | 功能 |
|---------|---------|------|
| `production_scanner` | 每 5 分钟 | 扫描待生成章节，触发 LLM 6 步链路 |
| `publish_scanner` | 每 5 分钟 | 扫描到期章节，调 DeviceController 发布 |
| `publish_plan_evening` | 每天 23:00 | 生成次日发布计划 |
| `publish_plan_morning` | 每天 08:10 | 调整当日发布计划 |
| `watchdog` | 每 1 分钟 | 存稿/故障/熔断/API 四项监控 |

**自动激活机制**：`main.py` 中的 `add_job_if_implemented()` 通过检查方法源码中的 `NotImplementedError` 来决定是否调度。当 stub 被替换为真实实现后，任务自动激活，无需修改 main.py。

---

## 七、日志

### 7.1 本地日志

```
logs/openclaw.log          # loguru 滚动日志（路径在 config.yaml paths.log_file）
```

### 7.2 飞书运行日志

生产/发布/监控的运行日志实时写入飞书 Bitable `运行日志表`，字段：
- `节点名称`：production_scanner / publish_scanner / llm_pipeline / watchdog / settings_extractor
- `执行状态`：成功/Success / 警告/Warning / 严重告警/Critical
- `输入摘要` / `输出摘要`：步骤关键信息
- `错误信息`：异常详情

---

## 八、停止服务

```bash
# 直接运行：Ctrl+C（优雅退出，调度器 shutdown + 资源 close）
# systemd: sudo systemctl stop openclaw
# NSSM: nssm stop OpenClaw
# Docker: docker stop openclaw
```

---

## 九、目录权限要求

| 目录 | 读写权限 | 用途 |
|------|---------|------|
| `config/` | 读 | .env + config.yaml + field_mapping.yaml |
| `data/` | 读写 | SQLite 缓存和任务锁文件（自动创建） |
| `logs/` | 写 | 本地日志文件（自动创建） |
| `prompts/` | 读 | Jinja2 Prompt 模板 |
