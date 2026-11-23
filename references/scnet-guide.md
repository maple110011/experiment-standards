# SCNet 接入指南：把 dsh 装进海光 DCU 容器

> 平台：国家超算互联网（SCNet）的计算卡容器（海光 DCU / DTK 镜像）。拓扑 **B**：dsh 在容器内常驻，
> 本地只留一个浏览器。本文讲**怎么装、怎么连、重启后怎么一条命令恢复**；通用骨架见
> [remote-access.md](./remote-access.md)，另一条拓扑见 [cannlab-guide.md](./cannlab-guide.md)。
>
> 版本演进（三份材料，别用错）：
>
> | 版本 | 材料 | 形态 |
> |:--|:--|:--|
> | 2026-08 初版 | 本机 `远程部署dsh说明.md` | **以 SSH 隧道为主**，域名/端口/代理全写死在脚本里 |
> | **2026-10-20 r2（现行）** | `D:\临时\SCNet部署dsh\deploy-r2\`（`README.md` + `start.sh` + `deploy-dsh.ps1`） | **无 SSH 为主**：上传脚本 → JupyterLab 跑一行 → 平台"访问自定义服务"暴露 8082；参数化、代理自动探测、`run.sh` 持久化参数、`--diagnose` |
> | 2026-10-20 DCU 训练包 | `gsv_dcu_bundle.tar.gz`（`RUNBOOK.md`） | 在容器里跑真实训练时的 DCU 适配与禁令，见 §9 |
>
> 本文按 **r2** 写。

## 0. 为什么反过来把 dsh 放进容器

SCNet 给的是"一台带卡的 Linux 容器 + 平台端口转发 + 一个会漂移的出网代理"。
本地的 dsh 远程操作它，每一步都要和维护权打架：装包、改端口、看进程状态、代理失效。
把 dsh 装进容器，本地只留浏览器：代码、checkpoint、日志就地读写；容器重启后本机**不需要**重装任何东西；
代价是 dsh 自己的模型调用也要走容器的出网代理——这是 §4 最大的坑。

## 0.5 先问一句：这台机器真的需要装 dsh 吗

装 dsh 进容器是**有代价**的：代理要探测、`DSH_HOME` 要落在持久卷、转发器要起、平台域名要加进
`--trusted-host`、平台只能暴露一个端口。这五件事每一项都能单独把链路搞挂。

所以先按代价从低到高试：

| 顺序 | 做法 | 前提 | 代价 |
|:--|:--|:--|:--|
| 1 | **本机 DSH + SSH + [remote_job.sh](../scripts/remote_job.sh)** | 平台给 SSH（`ssh.zzai.scnet.cn:<端口>`，账号密码） | 最低：不装任何东西，一条命令提交/查状态/取回 |
| 2 | 本机 DSH + SSH 隧道 + 远端只跑 `dsh web` | 同上，且想用**图形界面** | 中：容器里仍要 Node + dsh，但不需要转发器与 `--trusted-host` |
| 3 | **本文的方式 A（无 SSH，装 dsh + 转发器）** | **没有可用 SSH** | 最高：Agent 在容器里，本机只留浏览器 |

第 1 条就是"像 CANNLab 一样直接"的答案：**同一个 `remote_job.sh` 在 CANNLab 那种"CLI 给你命令通道"
的场景同样能用**（把 `--ssh-opts` 换成 CLI 提供的隧道命令即可）。

> 本机实测（2026-11-23）：`ssh.zzai.scnet.cn` 解析到 `42.228.13.144`，但 22 / 11042 / 443
> **三个端口都连不通**。也就是说在这台机器、这个网络下**第 1、2 条路走不通**，只能走第 3 条。
> 这正是当初把脚本从"SSH 隧道版"改成"无 SSH 版"的原因——**不是绕，是被平台逼的**。
> 换一台能连 SSH 的机器（或平台放开 SSH），就该退回第 1 条。

## 1. 两条通道：A 不用 SSH（本平台现状的主推），B SSH 隧道（能连 SSH 时优先）

| | A：平台自定义服务 | B：SSH + 本机隧道 |
|:--|:--|:--|
| 需要什么 | JupyterLab 终端（或 notebook cell）+ 平台 UI | SSH 账号密码 + 本机 `ssh` |
| 端口 | 平台暴露 **8082**（容器内转发器） | 本地 `8081 → 127.0.0.1:3080` |
| 设置页 | 不可用（远程浏览器，loopback-only） | 可用 |
| 重启后 | 重跑 `bash ~/private_data/dsh/run.sh`，再点一次"启动任务" | 重跑 `run.sh`，`ssh -N scnet` |
| 平台限制 | **只支持暴露一个端口** | — |

选 A 的理由：SCNet 的 Notebook 实例经常根本没有可用的 SSH，A 不需要任何入站凭据。
B 只是在"要改设置"或"平台代理不支持 WebSocket、页面一直转圈"时才用。

**信任模型（两条通道共同）**：`dsh web` 只监听 loopback 且拒绝通配地址；Host 栅栏接受 loopback、
监听器自身地址，以及每个 `--trusted-host` 点名的 authority（不带端口 = 匹配任意端口）；
栅栏只放行请求，认证靠启动 token 与签名 cookie。平台域名必须显式加进 `--trusted-host`。

## 2. 前置事实

| 项 | 事实 | 怎么验证 |
|:--|:--|:--|
| 持久目录 | `~/private_data` 是 NFS，实例重启不丢；``~` 其余与 overlay 层关机即丢 | 重启后再看文件还在不在 |
| 配置复用 | `~/private_data/dsh/.dsh` 里的密钥/设置跨实例复用 | 新实例起来后 `dsh` 能直接对话 |
| 出网 | 国内通、**国际基本不通**（GitHub/PyPI/HF） | `curl -v --max-time 10 https://github.com` |
| 卡 | 海光 DCU，DTK 镜像自带 torch | `hy-smi -L` / `rocm-smi` / `torch.cuda.is_available()` |
| 出网代理 | 地址**会漂移** | 见 §4 |

## 3. 方式 A：上传 → 跑一行 → 平台暴露端口

```text
A1 上传 start.sh          → /root/private_data/dsh/start.sh
A2 先诊断（建议）         → bash /root/private_data/dsh/start.sh --diagnose
A3 跑一行                 → bash /root/private_data/dsh/start.sh --domain c-xxxx.zzai.scnet.cn
A4 平台 UI                → 实例 →「访问自定义服务」→ 端口填 8082 → 启动任务
A5 打开平台给的外链       → https://c-xxxx.zzai.scnet.cn:<平台外部端口>/
```

要点：

- **域名**就是平台 URL 里 `c-xxxx.zzai.scnet.cn` 那一段。脚本还会从 `hostname`
  （`crdnotebook-<实例ID>-...`）自动推导出 `c-<id>.zzai.scnet.cn / .zzai2.scnet.cn / .ksai.scnet.cn` 三个候选，
  一并写进 `--trusted-host`。平台如果给了固定外部端口（旧实例是 `58043`），加 `--external-port 58043`。
- **第一次没有密钥**：加 `--deepseek-key sk-...`，或事后改 `~/private_data/dsh/.dsh/.credentials.yaml`。
- `setsid` 起的进程不会因为 cell/终端关掉而退出；但**容器重启会**，所以有 §7 的 `run.sh`。
- 平台只暴露一个端口，所以**只暴露转发器 8082**，dsh 自己的 3080 不对外。

**方式 B**（备选）：

```powershell
pwsh -NoProfile -File .\deploy-dsh.ps1 -HostName ssh.zzai.scnet.cn -Port 11042 `
    -Domain c-xxxx.zzai.scnet.cn -DeepseekKey sk-...
```

它把 `start.sh` 经 ssh stdin 送进容器执行，写 `~/.ssh/config` 的 `Host scnet-gsv`，开隧道并打开
`http://127.0.0.1:8081`；`-NoTunnel` 只部署不开隧道，`-LocalPort 8083` 改本地端口。

## 4. 出网代理：r2 的做法是"探测"，不是"假设"

初版把代理地址写死，地址一漂就整条链路失效。r2 改成三段式，按顺序判定：

1. **环境变量里有代理** → 直接用（打印通不通）。
2. 没有 → 试历史地址（脚本里的 `DEFAULT_PROXY`）；**通就用**。
3. 还不通 → 试直连；直连通就用直连，两边都不通则报警并继续（后面 Node 安装会再报一次）。

配套：

- `no_proxy` 必须包含平台域名与回环：`*.zzai.scnet.cn`、`*.zzai2.scnet.cn`、`*.ksai.scnet.cn`、`localhost`、`127.0.0.1`、`::1`。
  漏掉平台域名会让"页面能开、API 403"或"回环请求被送去代理"。
- `NODE_USE_ENV_PROXY=1` 由脚本统一 export（**Node 不原生读 `https_proxy`**）。
- 手动覆盖：`--proxy <url>` 钉死一个、`--no-proxy` 强制直连。**拿到新地址就改进脚本**，别只 `export` 一次。
- **代理密码不要写进仓库或文档**：本仓库只留占位符，真实地址在容器/本机脚本里。

诊断第一招永远是 `curl -v --max-time 10 <目标>`：能看出卡在代理、DNS、TCP、TLS 还是 HTTP。

## 5. `start.sh` 的设计（r2，幂等）

一遍跑完八件事，每步都有失败出口：

| # | 步骤 | 具体做法 |
|:--|:--|:--|
| 1 | 代理 | 探测（§4）；`--diagnose` 时只打印不启动 |
| 2 | 清残留 | 先 `pkill dsh web / fwd.py`，否则会把自己上次的转发器误判成"端口被占" |
| 3 | 端口 | 8082 被占就顺延 8083–8102，**打印实际端口**，平台填那个 |
| 4 | 保存参数 | 带参数运行时生成 `run.sh`（§7） |
| 5 | Node | 要求 ≥ 24.10；用**清华/阿里镜像**下指定版本 tar.gz + `SHASUMS256` 校验，解压到 `BASE/node`；镜像都不通时回退 `conda install nodejs>=24` |
| 6 | dsh | `npm i -g @deepseek-ai/dsh --registry npmmirror`；再校验依赖完整性（缺 `js-yaml` 就补装一次，并提示 `--force`） |
| 7 | 配置 | `.credentials.yaml`（有就沿用）+ `settings.yaml`（`agent-default-model: deepseek-official / <model>`，存在就不覆盖） |
| 8 | 启动+自检 | 生成 `fwd.py`（端口读环境变量）→ `setsid` 起 dsh 与转发器 → `curl --noproxy '*'` 轮询，3080 最多等 40 s、转发器 15 s，认 200/302/307 |

失败时的输出也设计过：打印进程、node/dsh/python3 路径、两个日志大小与末尾、必要时前台重跑 15 s 抓真实报错，
并对 `ERR_MODULE_NOT_FOUND` 直接给出 `npm install -g @deepseek-ai/dsh --force`。

参数表：

| 参数 | 说明 |
|:--|:--|
| `--domain <域名>` | 实例外部域名（**必须**，否则平台域名访问被拒） |
| `--external-port <端口>` | 平台固定外部端口，额外加一条 `域名:端口` 的 trusted-host |
| `--fwd-port <端口>` | 容器内转发端口，默认 8082 |
| `--deepseek-key <key>` / `--model <模型>` | 写/更新密钥；模型默认 `deepseek-v4-flash` |
| `--proxy <url>` / `--no-proxy` | 覆盖代理探测 |
| `--diagnose` | 只打印：脚本版本、宿主、BASE、环境代理、旧代理/直连可达性、node/python3/conda/dsh、凭据、3080/端口状态 |

## 6. 配置写文件（设置页在远程浏览器里不可用）

```text
DSH_HOME=$HOME/private_data/dsh/.dsh      # 必须在持久卷上
├── .credentials.yaml                     # chmod 600
├── settings.yaml
├── dsh-web.log / fwd.log
└── tools/                                # 可选：插件/工具（PATH 里会带上 .bin）
```

```yaml
# .credentials.yaml
version: 1
refs:
  DEEPSEEK_API_KEY: "sk-..."
```

```yaml
# settings.yaml
agent-default-model:
  provider: deepseek-official
  model: deepseek-v4-flash
```

解析优先级：**进程环境变量 > `.credentials.yaml` > 项目 `.env` > 用户 `.env`**。

## 7. `run.sh`：参数持久化，重启只跑一条

`start.sh` **带参数运行**时会把这次参数写成 `$BASE/run.sh`（`chmod 700`），内容就是一行 `exec`：

```bash
#!/usr/bin/env bash
exec bash /root/private_data/dsh/start.sh --domain c-xxxx.zzai.scnet.cn --external-port 58043 --fwd-port 8082 --model deepseek-v4-flash
```

所以：

- **`run.sh` 不是手写的，也不需要备份**——它由 `start.sh` 生成；丢了就用新参数重跑一次 `start.sh`，它会覆盖重建。
- 想只跑 `run.sh` 而参数已经过时（换了实例/端口）：别改 `run.sh`，直接用新 `--domain/--external-port` 重跑 `start.sh`。
- 代理**不建议**写进 `run.sh`：钉死会随漂移失效，留空即 auto。

## 8. 重启清单与验收

1. 平台重启容器（可能排队）。
2. `bash ~/private_data/dsh/run.sh`（或带新参数重跑 `start.sh`）。
3. 方式 A：重新「访问自定义服务」暴露 8082 / 点「启动任务」；方式 B：`ssh -N scnet-gsv`。
4. 验收三条：
   ```bash
   curl -s -o /dev/null -w "dsh: %{http_code}\n" --noproxy '*' http://127.0.0.1:3080/   # 200/302/307
   curl -s -o /dev/null -w "fwd: %{http_code}\n" --noproxy '*' http://127.0.0.1:8082/   # 200/302/307
   ps aux | grep -E "dsh web|fwd.py" | grep -v grep
   ```
5. 人的两条：浏览器里发一句话能回复（模型+代理都通）；在容器里写文件、网页端读得到（工作目录与权限没问题）。

## 9. 在 DCU 容器里跑实验（用训练包的标准做法）

拿到 dsh 之后，训练包（如 `gsv_dcu_bundle.tar.gz`）是这么组织的：`RUNBOOK.md` 给执行者（stage 0–6，
每步有通过判据）、`PROMPT_FOR_DSH.md` 是粘进会话的启动指令、`scripts/` 是分阶段脚本、`MANIFEST` 带 sha256。

DCU 特有的十条（都是从实机踩出来的）：

1. **不要 `pip install torch/torchaudio/torchvision`**，也不要用仓库自带的 `requirements.txt`/`install.sh`：
   前者会装成 CUDA 版，后者走 `download.pytorch.org`（国际网）。只用为 DCU 精简的依赖清单
   （示例 `scripts/requirements.dcu.txt`）。
2. **venv 用 `--system-site-packages`** 继承镜像里的 DTK torch，别在容器里重建 torch。
3. **不要 `git clone`**：国际网不通，源码随包带；需要改仓库逻辑时用补丁脚本（`patch_repo.py`）且带备份。
4. **不启动 WebUI**：没有浏览器，训练走 CLI；WebUI 的预处理步骤用脚本等价复刻。
5. **卡用 `hy-smi`**（`rocm-smi` 也可）：`hy-smi -L`；训练时 `watch -n 5 hy-smi`。
6. **默认 python 可能不是镜像主解释器**（torch 在 conda 环境里）→ `torch.cuda.is_available()=False` 先查这个。
7. **fp16 在 DCU 上可能 NaN**：把训练配置的 `precision` 改 32 / `fp16_run: false`，预处理重跑一次。
8. **预训练权重从 ModelScope 现场下**（国内可达），不要随包上传 2.5 GB。
9. **共享型实例 CPU 份额未知**：预处理慢 2–3 倍正常，别因此反复重启实例；`num_workers` 别开大。
10. **失败一律留日志**（`logs/*.log`），回报只贴末尾 40 行；不要自行大改。

DCU 环境事实（2026-10 实测一台 SCNet Pod，供参照）：

| 项 | 值 |
|:--|:--|
| 架构 / 生态 | 海光 DCU，`gfx906`（Vega 20 血统），HSA vendor `HYGON`；**无 NVIDIA/CUDA** |
| 可见卡数 | 宿主 4 卡，容器 cgroup 只放通 1 卡 → `torch.cuda.device_count()==1` |
| 单卡显存 | 16 GiB HBM2（另有 64 GB 规格池，以实例为准） |
| 软件栈 | DTK 26.04（`/opt/dtk`）、HIP 6.3、rocBLAS/rocFFT/RCCL；torch 2.9.0 + HIP |
| 实测吞吐 | FP32 GEMM ≈10.9 TFLOPS、FP16 ≈19.2 TFLOPS、D2D 拷贝 ≈723 GB/s |
| 已知坑 | `hipBLASLt` 缺 gfx906 kernel（GEMM 实际走 rocBLAS 回退）；gfx906 无原生 BF16/FP8 矩阵指令 |
| NUMA | 卡在 node 0，绑核用 `numactl --cpunodebind=0 --membind=0` |

## 10. 故障表（按 [remote-access.md](./remote-access.md) §8 分层）

| 症状 | 层 | 处理 |
|:--|:--|:--|
| `Request timed out` / 对话一直转圈 | 网络 | 先 `--diagnose`；代理漂移就 `--proxy <新地址>`；平台代理不支持 WS 时改走方式 B |
| 页面 403 / 空白 | 信任 | 没带 `--domain` 或域名不是平台那个 |
| `502` / 平台"未检测到可用服务" | 协议 | 8082 没监听 → `--diagnose` 看端口；被占就按脚本打印的顺延端口在平台填 |
| `settings are unavailable` | 信任 | 远程浏览器 loopback-only，改文件配置（§6） |
| `dsh(3080): 000` | 协议 | dsh 没起来，看 `dsh-web.log` 末尾；`ERR_MODULE_NOT_FOUND` → `npm i -g @deepseek-ai/dsh --force` |
| npm 装不动 | 网络 | `--proxy` 换代理；或改用 `--registry https://registry.npmmirror.com` |
| 重启后全丢 | 持久化 | `DSH_HOME` 必须指到 `~/private_data/dsh/.dsh` |
| `MISSING_CREDENTIAL` / `401` | 凭据 | `.credentials.yaml` 的 key/引用名 |
| `torch.cuda.is_available()=False` | 远端环境 | 镜像不是 DTK+PyTorch，或默认 python 不是主解释器（`conda activate` / `GSV_BASE_PYTHON`） |

## 11. 与 CANNLab 的拓扑对比

| 维度 | SCNet DCU 容器（B） | CANNLab 昇腾 NPU（A） |
|:--|:--|:--|
| dsh 在哪 | **容器内**（本地只是浏览器） | **本机**（CLI 远程驱动） |
| 建连 | 平台自定义服务 8082（主）/ SSH 隧道（备） | CLI 自建一次性隧道 |
| 长命令载体 | 容器内 `setsid` 后台进程 | `cannlab job submit`（setsid+nohup） |
| 持久目录 | `~/private_data`（NFS） | `/mnt/workspace`、`/home` |
| 回收 | 平台配额与排队，主动关实例 | 按卡时，空闲 30 分钟自动关机 |
| 典型坑 | 出网代理漂移、设置页不可用、DCU 装错 torch | 隧道断、CANN 未 source、torch_npu 未 import |
| 复用要点 | 参数化 + 探测 + `run.sh` 持久化参数 | 凭据与隧道全交给 CLI |
