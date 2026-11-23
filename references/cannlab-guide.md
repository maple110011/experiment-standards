# CANNLab 接入指南：用本地 DSH 遥控昇腾 NPU

> 平台：CANNLab（昇腾 NPU 云开发环境）。拓扑 **A**：dsh 跑在本机，CANNLab 只提供"命令通道"。
> 本文讲**这条通道怎么搭、怎么验、坑在哪**；命令表以已安装的 `cannlab-npu` skill 为准。
> 通用骨架见 [remote-access.md](./remote-access.md)；另一条拓扑见 [scnet-guide.md](./scnet-guide.md)。

## 0. 为什么需要一层 CLI

CANNLab 官方只给两个**给人点**的入口：WebIDE 和 VSCode Remote-SSH。agent 用不了它们。
但两者背后是同一套协议，`cannlab` 把这套协议实现成纯 Node CLI：

```
GitCode OAuth ─access token─► CANNLab OpenAPI
                                │ 临时 SSH 私钥 + 签名 WSS 地址
                                ▼
       官方 AtomGit Dev Space port-forward helper（纯 JS）
                                │ 实例 :22 映射到 127.0.0.1:<随机端口>
                                ▼
                     系统 OpenSSH（ssh / scp）
```

**边界**：agent 只调 `node cannlab/bin/cannlab.mjs ...`，不自己拼 `ssh` 命令，也不试图复用连接。
这一层不是为了自动跑实验，而是为了**把"人点 GUI"变成"agent 能发的命令"**；命令能发出去，实验规范才有地方落地。

## 1. DSH 侧要装什么

| 项 | 要求 | 本机实测 |
|:--|:--|:--|
| Node.js | ≥ 20 | v24.14.1 |
| OpenSSH 客户端 | 任意 | OpenSSH_for_Windows_9.5p1 |
| 网络 | **必须关闭代理/VPN**（官方要求） | 已验证可直连 |
| WSL / 管理员权限 | 不需要 | 均无 |
| CLI 位置 | `<工作区>/research/cannlab/bin/cannlab.mjs` | `E:\software\ss\research\cannlab` |

把规则装进 DSH（让它自动发现"用 CLI、不拼 ssh、长任务走 job"）：

```powershell
pwsh -File cannlab\install-skill.ps1   # → ~/.dsh/skills/cannlab-npu/
```

## 2. 首次接入 SOP

```bash
# 0) 登录：浏览器授权必须用户本人点；回调固定占本机 3000 端口
node cannlab/bin/cannlab.mjs login

# 1) 看环境 / 开机（开机即开始计费，见 §8）
node cannlab/bin/cannlab.mjs list
node cannlab/bin/cannlab.mjs power on --env <名>      # 约 24 秒到 running

# 2) 连通性自检（判据见 §6）
node cannlab/bin/cannlab.mjs info --env <名>
```

**agent 必须停下来等用户的两件事**：① 重新 `login`（授权只能本人点）；② 开关机、尤其是开多卡（产生费用）。

## 3. 建环境：字段一次填对

| 字段 | 推荐值 | 备注 |
|:--|:--|:--|
| 环境类型 | 云开发环境 → 昇腾 NPU → **A2** | A2 = 910B 系列；A3(910C) 池子紧且规格过剩 |
| 环境名称 | `pfn-a2-01` | 字母开头，只含字母/数字/下划线，≤15 字符 |
| 模板 | **`cann_9.0.0_py3.11-A2-arm`** | 决定 CANN + Python + 架构；选错只能删环境重建 |
| 规格 | **`1*NPU 910B3 32vCPUs 32GiB`**（无则 16vCPU） | 卡数写在规格里；vCPU 不影响卡时 |
| 预加载代码仓 | 你的实验仓 + 目标分支 | 创建时自动 clone 到 `/mnt/workspace/gitCode/` |

不可逆的约束：**A2↔A3 不能切换、卡数不能加、镜像不能换**；改任一只能关机 → 删除 → 重建，
而删除会**清空 `/mnt/workspace` 与 `/home`**。所以重建前先 `git push` + 把 checkpoint 拉回本地。

## 4. 一条命令一条隧道：生命周期与并发

- 每次 CLI 调用**自建自拆隧道**（约 1–2 秒开销），没有交互式 shell；两条命令之间不要假设连接还在。
- helper 进程随 CLI 退出；DSH 沙箱还会杀掉游离子进程 → **不要在本机后台挂一条隧道等下次用**。
- **helper 僵尸锁**：进程死后留下 `1.0.12.LOCK`，新 helper 报 `Could not create LOCK file: EEXIST`；CLI 已会检测 pid 死亡并先清锁。
- 同一环境**不支持多机同时连**：被 VSCode 插件占用时 CLI 连不上。
- 开本机代理 / VPN 会直接打断连接，官方明确要求关闭。

## 5. 远端环境的事实（少走两小时弯路）

- 登录用户是 **`developer`，不是 root**；需要 root 用 `sudo -n`，失败就如实报告。
- CANN 装在 `/home/developer/Ascend`，`set_env.sh` 在 `/home/developer/Ascend/ascend-toolkit/set_env.sh`。
- **非交互 SSH 不加载 CANN**：`npu-smi` 报 `libc_sec.so` 缺失、`import torch_npu` 报 `libhccl.so` 缺失；
  CLI 现在对每条远端脚本自动 source，**不要**在脚本里再手工 source 一遍。
- **torch / torch_npu 已预装**（实测 `2.7.1+cpu` / `2.7.1.post4`），`torch.npu.is_available()=True`；
  官方配套表写的是别的版本，**以实例实测为准**，不要照表重装。
- 持久盘只有 `/mnt/workspace` 与 `/home`（各 200G，关机保留、删除环境即清空）；其余目录关机即丢。

## 6. 连通性验证：`info` 的期望输出

| 项 | 期望 |
|:--|:--|
| 架构 / 用户 | `aarch64` / `developer` |
| 卡 | `npu-smi` 看到 `910B3`，Health OK，HBM 可用 |
| CANN | 9.0.0，路径在 `/home/developer/Ascend` |
| torch | `torch.npu.is_available() == True`，设备名 `Ascend910B3` |
| 盘 | `df -h /mnt/workspace` 有空间 |

✅ **判据**：`is_available()==True` 且设备名与预期一致，才算"接通"；只看 ssh 能登录不算。

## 7. 长命令的载体：job 协议

隧道会断、本机会关机，所以**长命令不能放在前台 `exec` 里**。`job submit` 在远端落盘一个作业目录，
用 `setsid`+`nohup` 托管，CLI 只负责"落盘 + 拉起"，秒级返回；之后本机做什么都不影响它。

`/mnt/workspace/.cannlab/jobs/<job-id>/`：

| 文件 | 含义 |
|:--|:--|
| `cmd.sh` / `runner.sh` | 你的脚本 / setsid+nohup 运行器 |
| `status` | `queued` → `running` → `finished` / `failed` / `killed` |
| `pid` / `exit_code` / `started_at` / `finished_at` | 进程与时间 |
| `stdout.log` / `stderr.log` | 输出 |
| `meta.json` | 作业元数据 |

状态先写 `.tmp` 再 `mv`，所以读不到写了一半的状态。

```bash
node cannlab/bin/cannlab.mjs job submit --name run1 --file run.sh --workdir /mnt/workspace/proj --env <名>
node cannlab/bin/cannlab.mjs job status run1-XXXX --env <名>
node cannlab/bin/cannlab.mjs job logs   run1-XXXX --tail 120 --env <名>
node cannlab/bin/cannlab.mjs fetch /mnt/workspace/proj/runs/<exp>/run_<ts> ./results --env <名>
```

**成功判据只有一条**：`state=finished` 且 `exitCode=0`。`alive=false` 不代表成功；
失败先看 `--stream stderr`（常见：CANN 没 source、torch 与 torch_npu 不配套、OOM、NPU 被占用）。

## 8. 防烧卡与回收

- **1 卡时 = 卡数 × 小时**，初始 100 卡时，**开机即烧**；8 卡跑 2 小时 = 16 卡时（100 卡时只够 8 卡跑 12.5 小时）。
- **单卡 NPU 空闲超过 30 分钟自动关机**（CPU 环境 72 小时），会中断正在跑的进程，但 `/mnt/workspace`、`/home` 保留。
  危险场景：首轮采样 / `torch.compile` 预热让 NPU 利用率长时间为 0 → 被判空闲。**进去先提交一个心跳小作业**。
- 提交时默认加 **`--poweroff-when-done=5`**（作业停止 5 分钟后自动关机）；这是最省心的一条。
- 超过 1 小时的作业先 `guard arm --env <名> --idle-min 30 --max-hours N`，到点强制关机（checkpoint 在持久盘，不丢）。
- 守卫需要一条 Windows 计划任务每 5 分钟 `guard tick`（DSH 沙箱禁止注册计划任务，**要用户自己在普通终端装一次**）：
  `pwsh -ExecutionPolicy Bypass -File cannlab\install-guard-task.ps1`。
- 守卫的设计取向：查询失败 / 隧道断 / 未登录 → **一律不关机**，宁可多烧也不误杀正在跑的实验。

## 9. 故障表（按 [remote-access.md](./remote-access.md) §8 的分层）

| 症状 | 层 | 处理 |
|:--|:--|:--|
| `尚未登录` / 401 | 凭据 | `login`，授权必须用户本人点 |
| `环境 X 当前为 stopped` | 建连 | `power on`，等到 running（1–3 分钟） |
| `本地端口转发 helper 启动超时` | 协议 | 看 `cannlab/.state/logs/helper.log`；重试一次 |
| `Could not create LOCK file: EEXIST` | 协议 | 旧 helper 僵尸锁；确认 pid 已死后删掉 `1.0.12.LOCK` |
| 连接超时 / 时断时续 | 网络 | 关本机代理 / VPN |
| `Cannot listen on 3000` | 网络 | 登录回调端口被占，腾出来 |
| 找不到 `libascendcl` / 头文件 | 远端环境 | 作业脚本里的 CANN 没 source（CLI 已自动加） |
| `torch.npu.is_available()==False` | 远端环境 | 没 `import torch_npu`，或 torch 被 pip 换成 CPU 版（`--no-deps` 重装） |
| 开机报"当前规格暂无可用算力资源" | 平台 | 等资源或换规格重建（不可原地改） |

## 10. 复用到别的平台

把这条链抽象成六件事，任何"官方只给 GUI"的平台都能照这个顺序补一层：

```
auth（登录 + 凭据存储） → tunnel（隧道/端口映射） → exec（单条命令）
  → ship/fetch（文件） → job（长命令载体） → poweroff/guard（回收）
```

补齐这六件事，新平台的专章就只需要填 [remote-access.md](./remote-access.md) §9 的记录表，
而不是重新摸索一遍。
