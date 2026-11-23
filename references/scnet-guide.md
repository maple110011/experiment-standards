# SCNet 接入指南：把 dsh 装进计算卡容器

> 平台：国家超算互联网（SCNet）的计算卡容器。拓扑 **B**：dsh 在容器内常驻，本地只留一个浏览器。
> 本文讲**怎么装、怎么连、容器重启后怎么一条命令恢复**；通用骨架见 [remote-access.md](./remote-access.md)，
> 另一条拓扑见 [cannlab-guide.md](./cannlab-guide.md)。
> 事实来源：本机 `远程部署dsh说明.md`（SCNet 容器实测，2026-08）。

## 0. 为什么反过来把 dsh 放进容器

SCNet 给的是"一台带卡的 Linux 容器 + 平台端口转发 + 一个会漂移的出网代理"。
本地的 dsh 远程操作它，每一步都要和维护权打架：装包、改端口、看进程状态、代理失效。
把 dsh 装进容器，本地只留浏览器：

- 代码、checkpoint、日志在容器内就地读写，不用来回搬；
- 容器重启后本机**不需要**重装任何东西（只要 `start.sh` 在持久盘上）；
- 代价：dsh 自己的模型调用也要走容器的出网代理——这是 §4 最大的坑。

## 1. 前置检查

| 项 | 怎么查 | 通过判据 |
|:--|:--|:--|
| 持久卷路径 | `df -h` / 平台说明 | 知道哪个目录重置后还在（常见 `~/private_data`） |
| Node | `node -v` | ≥ 20；没有就 §2 |
| 出网 | `curl -v --max-time 10 https://<你的模型 API>` | 能到 TLS/HTTP，不是卡在代理 |
| 代理 | `env \| grep -i proxy` | 记下当前地址（会漂移，见 §4） |

## 2. 装 Node 与 dsh（幂等）

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc
nvm install --lts && nvm alias default 'lts/*'

npm install -g @deepseek-ai/dsh
dsh --version
```

## 3. 三条访问通道与信任模型

| 通道 | 服务端 | 本地 | 代价 |
|:--|:--|:--|:--|
| **SSH 隧道（首选）** | `dsh web --no-open`（默认 `127.0.0.1:3080`） | `ssh -N -L 8081:127.0.0.1:3080 -p <端口> <用户>@<主机>` | 无；设置页可用 |
| 平台端口转发 | 额外起转发器 `0.0.0.0:8082 → 127.0.0.1:3080` | 打开平台暴露的外部地址 | 设置页不可用、重启换地址 |
| **双通道（推荐长期）** | dsh 加 `--trusted-host <外部域名>`（不带端口）+ 转发器 | 日常用外部地址，改配置走 SSH | 需要维护两处 |

**信任模型的三条事实**（`dsh web --help`，0.2.2-rc.3）：

- `dsh web` 默认只监听 **loopback**，并**拒绝通配地址**（`--host 0.0.0.0` 在加载时被拒）。
- Host 栅栏接受 loopback、监听器自身的绑定地址，以及每个 `--trusted-host` 点名的 authority；
  **不带端口的条目匹配任意端口**。栅栏只放行请求，真正的认证靠启动 token 与签名 cookie。
- **设置页只对 loopback 浏览器开放**。远程浏览器显示 `settings are unavailable in this browser` 是设计，不是 bug → 配置走文件（§5）。

Windows 本地把隧道写进 `~/.ssh/config`：

```
Host scnet
    HostName ssh.zzai.scnet.cn
    Port <SSH端口>
    User root
    LocalForward 8081 127.0.0.1:3080
```

之后 `ssh -N scnet` 即可（平台不支持公钥时仍要输密码）。

## 4. 出网代理：三个坑

1. **Node 不读 `https_proxy`**（curl 读，Node 不读）。受限网络下"curl 能通、dsh 却 `Request timed out`"就是它。
   Node ≥ 24.10 用 `NODE_USE_ENV_PROXY=1` 启动 dsh。
2. **代理地址会漂移**：容器重启后可能整个换掉。症状是突然"无法对话 / `Connection error` / 连不上外网"。
   ```bash
   env | grep -i proxy
   curl -v --max-time 10 https://www.baidu.com
   ```
   curl 报 `Connection refused`（指向某个旧代理 IP:端口）→ 找平台要新地址，形如：
   ```bash
   export http_proxy='http://preset:<密码>@<新IP>:3128'
   export https_proxy='http://preset:<密码>@<新IP>:3128'
   export no_proxy='*.zzai2.scnet.cn,zzai2.scnet.cn,localhost,127.0.0.1'
   ```
   **拿到新地址就写进 `start.sh`**（覆盖容器里的旧值），别只 `export` 一次。
3. **免费代理常常只能访问国内站点**：单独验证你要用的 LLM 接口通不通，别等对话时才炸。

诊断第一招永远是 `curl -v <接口地址>`：能一步步看出卡在代理、DNS、TCP、TLS 还是 HTTP。

## 5. DSH_HOME 与文件化配置

数据目录 `$DSH_HOME`（默认 `~/.dsh`）**必须指到持久卷**，否则容器重置时配置和会话一起没。

```
$DSH_HOME/.credentials.yaml      # 密钥
$DSH_HOME/settings.yaml          # 模型路由
$DSH_HOME/logs/                  # 运行日志
```

```yaml
# .credentials.yaml
version: 1
refs:
  DEEPSEEK_API_KEY: sk-官方key
  PENGUIN_API_KEY: sk-中转key
```

```bash
chmod 600 "$DSH_HOME/.credentials.yaml"
```

解析优先级：**进程环境变量 > `.credentials.yaml` > 项目 `.env` > 用户 `.env`**。
官方 DeepSeek 用内置 `deepseek-official` 路由，配好密钥即可；中转站（OpenAI 兼容接口）在
`settings.yaml` 的 `llm-pi-ai.providers` 下手工声明（`apiKeyEnv`、`baseURL`、`api: openai-completions`、
`compat.thinkingFormat` 等）。完整示例见 `远程部署dsh说明.md` §5.2。

## 6. `start.sh`：一条命令恢复

放持久盘，**幂等**，每次重启容器只跑这一条。它做四件事：装依赖 → **每次重新生成转发器** →
`setsid` 起两个进程 → `curl` 自检。

```bash
#!/usr/bin/env bash
set -u
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1
if ! command -v node >/dev/null 2>&1; then
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1
  nvm install --lts && nvm alias default 'lts/*' >/dev/null 2>&1
fi
export NODE_USE_ENV_PROXY=1
export DSH_HOME="$HOME/private_data/dsh/.dsh"
mkdir -p "$DSH_HOME"
command -v dsh >/dev/null 2>&1 || npm install -g @deepseek-ai/dsh

cat > "$HOME/private_data/dsh/fwd.py" <<'PY'
import socket, threading
TARGET = ('127.0.0.1', 3080)
def pipe(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d: break
            b.sendall(d)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try: s.close()
            except OSError: pass
def handle(c):
    u = socket.socket()
    try:
        u.connect(TARGET)
    except OSError:
        c.close(); return
    threading.Thread(target=pipe, args=(c, u), daemon=True).start()
    threading.Thread(target=pipe, args=(u, c), daemon=True).start()
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('0.0.0.0', 8082))
srv.listen(128)
print('forwarder 0.0.0.0:8082 -> 127.0.0.1:3080', flush=True)
while True:
    c, _ = srv.accept()
    threading.Thread(target=handle, args=(c,), daemon=True).start()
PY

pkill -f "dsh web" 2>/dev/null || true
pkill -f "fwd.py"  2>/dev/null || true
sleep 1

setsid dsh web --no-open \
  --trusted-host <容器外部域名> \
  > "$DSH_HOME/dsh-web.log" 2>&1 < /dev/null &

setsid python3 "$HOME/private_data/dsh/fwd.py" \
  > "$DSH_HOME/fwd.log" 2>&1 < /dev/null &

sleep 4
curl -s -o /dev/null -w "dsh(3080): %{http_code}\n" http://127.0.0.1:3080/
curl -s -o /dev/null -w "fwd(8082): %{http_code}\n" http://127.0.0.1:8082/
```

**每次重新生成 `fwd.py`** 是为了避免旧文件残留导致端口冲突；改过转发端口时必须重新生成（或先 `rm` 再跑）。

## 7. 容器重启后的恢复清单

1. 平台重启容器（可能排队）。
2. `bash ~/持久目录/dsh/start.sh`。
3. 平台转发通道：重新暴露 8082，拿新外部地址（域名不变则 `--trusted-host` 不用改）。
4. SSH 通道：命令不变，`ssh -N scnet`。
5. 验证：§8 三条。

## 8. 验证（可复制）

```bash
curl -s -o /dev/null -w "dsh: %{http_code}\n"      http://127.0.0.1:3080/   # 期望 200
curl -s -o /dev/null -w "fwd: %{http_code}\n"      http://127.0.0.1:8082/   # 期望 200
ps aux | grep -E "dsh web|fwd.py" | grep -v grep       # 两个进程都在
```

再做两次"人"的验证：**浏览器里发一句话能回复**（证明模型调用与代理都通）；
**在容器里写一个文件、网页端读得到**（证明工作目录与权限没问题）。

## 9. 故障表

| 症状 | 层 | 处理 |
|:--|:--|:--|
| `Request timed out` | 网络 | Node 没走代理 → `NODE_USE_ENV_PROXY=1` |
| 重启后无法对话 / `Connection error` | 网络 | 出网代理漂移 → §4，更新 `start.sh` |
| `502` | 信任 | 平台连网卡 IP，dsh 只监听回环 → 起转发器 |
| 每个 API 403 | 信任 | `--trusted-host` 没写浏览器看到的 authority |
| `settings are unavailable` | 信任 | 远程浏览器，设置页 loopback-only → 改文件配置 |
| 平台"未检测到可用服务" | 协议 | 端口没服务 / 转发器没起 → `ps` + 日志 + `curl 127.0.0.1:<端口>` |
| `dsh(3080): 000` | 协议 | dsh 没起来（常见：旧 `fwd.py` 占端口）→ 重跑 `start.sh` |
| `MISSING_CREDENTIAL` | 凭据 | 密钥没配 / 引用名错 → 检查 `.credentials.yaml` |
| `401` / AUTH | 凭据 | 密钥值错或过期 |

## 10. 与 CANNLab 的拓扑对比

| 维度 | SCNet 计算卡容器（B） | CANNLab 昇腾 NPU（A） |
|:--|:--|:--|
| dsh 在哪 | **容器内**（本地只是浏览器） | **本机**（CLI 远程驱动） |
| 建连 | SSH 隧道 / 平台转发 | CLI 自建一次性隧道 |
| 长命令载体 | 容器内 `setsid` 后台进程 | `cannlab job submit`（setsid+nohup） |
| 持久目录 | 平台持久卷（如 `~/private_data`） | `/mnt/workspace`、`/home` |
| 回收 | 平台配额与排队，主动关闭实例 | 按卡时，空闲 30 分钟自动关机 |
| 典型坑 | 出网代理漂移、设置页不可用 | 隧道断、CANN 未 source、torch_npu 未 import |
| 复用要点 | 配置全在文件里，重启只跑一条命令 | 凭据与隧道全交给 CLI，别自己拼 ssh |
