# 远程接入：把算力接进 DSH

> 本文只讲**连接**这一层：DSH 与远端之间那条链路怎么搭、怎么验、断了怎么判、换平台怎么复用。
> 接上之后的实验仍按 [SKILL.md](../SKILL.md) 的 7 步走；产物落盘见 [output-spec.md](./output-spec.md)，
> 记录包见 [recording-guide.md](./recording-guide.md)，长跑纪律见 [long-running-guide.md](./long-running-guide.md)。
>
> 两个现成样本：[cannlab-guide.md](./cannlab-guide.md)（拓扑 A：本地 DSH 遥控昇腾 NPU）·
> [scnet-guide.md](./scnet-guide.md)（拓扑 B：把 dsh 装进 SCNet 计算卡容器）。

## 0. 先选拓扑：DSH 放在哪一侧

远端接入从来不是一条命令，而是先回答一个问题：**agent 跑在哪台机器上？**

| 远端是什么 | 远端能装 Node 吗 | 建议拓扑 | 代表 |
|:--|:--|:--|:--|
| 平台只给 WebIDE / SSH，连接要自己建 | 不必 | **A：DSH 在本地，命令通道到远端** | CANNLab 昇腾 NPU |
| 一台 Linux 容器，出网受限，但能装 Node | 能 | **B：dsh 装在远端，本地只留浏览器** | SCNet 计算卡容器 |
| 普通 SSH 云主机 / 跳板机 | 可选 | **C：本地 DSH + OpenSSH** | 学校/实验室服务器 |

按顺序问三条（**先问能不能最省事，再问好不好用**）：

1. **有没有可用的 SSH？** 有 → 直接走拓扑 C：本机 DSH + `ssh` + `scripts/remote_job.sh`。
   这是最直白的一条：不装 Node、不搞转发器、不碰 Host 栅栏，本机就是"发命令的那一侧"。

   > 判断"有没有 SSH"别靠 ping 端口：很多平台（如 SCNet）的 SSH 是**每个实例一个专属端口**，
   > 只在实例开机期间监听，登录命令要实例页面复制。实例关着时，这些端口当然是黑的。
2. **没有 SSH、但远端能装 Node 并长驻进程？** → 拓扑 B：把 dsh 装进远端，本地只留浏览器。
   代价是代理、`DSH_HOME`、转发端口、`--trusted-host` 四件事都得自己维护。
3. **远端既没有 SSH、也装不了 Node？** → 拓扑 A：平台 CLI（如 CANNLab）当一次一条命令的通道。

**别把有 SSH 的情况做成 B。** 装 dsh 进容器只在"根本发不出命令"时才划算；一旦有命令通道，
多出来的每一层（转发器、信任白名单、出网代理）都是故障点，而不是能力。

选错的代价：在只允许跑作业的平台上硬装 dsh，会被空闲回收；在容器里做 A，会为本机与容器的双层代理反复买单。

## 1. 一条链路由五段组成

任何拓扑都能拆成同样五段。接新平台时逐段确认，不要跳。

| 段 | 要钉死的事 | 典型失败 |
|:--|:--|:--|
| ① 凭据 | 谁签发、存在哪、多久过期、要不要本人在浏览器点 | 401 / `MISSING_CREDENTIAL` / 登录态失效 |
| ② 建连 | 隧道还是端口转发、服务监听在哪、信任哪个 authority | 连接超时 / 403 / 502 |
| ③ 传输 | 代码怎么上去、产物怎么下来、方向是否单向 | 远端代码与本地不一致 / 取回空文件 |
| ④ 存活 | 远端进程谁托管、本机断了会怎样 | 隧道一断训练就没了 |
| ⑤ 回收 | 怎么关机/释放、空闲会不会被自动关 | 空烧卡时 / 额度耗尽被砍 |

**这五段就是可复用的骨架**：换平台只换每段的具体实现（CLI、SSH、平台转发），顺序不变。

## 2. ① 凭据：不落盘、不进日志、要人点

- **OAuth / 扫码登录必须用户本人完成**。agent 不能代点，也不该让用户把 token 贴进对话。
- 凭据放当前用户的加密存储（如 Windows DPAPI）或权限 600 的文件；不要放项目目录、不要进 git。
- 密钥与模型路由走**文件配置**，因为远程浏览器里设置页通常不可用（见 §3）。
- 复用点：先确认凭据存在哪、怎么过期、失效时哪条命令会报什么，再谈连接。

## 3. ② 建连：三条通道，信任规则是唯一的坑

**dsh web 只监听 loopback，且拒绝通配地址。** 实测 `dsh web --help`（0.2.2-rc.3）：

```
--host <host>                  bind address: one concrete IPv4 or IPv6 literal
                               of a local interface; wildcard addresses are rejected
--trusted-host <authority...>  extra authority the /api browser-trust fence
                               accepts (host or host:port; repeatable)
```

所以「从另一台机器打开浏览器」只有三条路：

| 通道 | 做法 | 代价 |
|:--|:--|:--|
| **SSH 隧道** | `ssh -N -L 8081:127.0.0.1:3080 ...` | 无；设置页可用；重启后命令不变 |
| **平台自定义服务（无 SSH）** | 容器里起 `0.0.0.0:<端口> → 127.0.0.1:3080` 转发器，在平台 UI 暴露该端口 | 设置页不可用；外部地址会变；**平台常只允许暴露一个端口** |
| CLI 自建一次性隧道 | 平台 CLI 每条命令建一次、用完即拆（拓扑 A） | 不能交互；每次 1–2 秒开销 |

选哪条看约束，而不是看习惯：**没有可用 SSH 就选平台端口暴露**（很多 Notebook 型实例就是这样），
**要改设置或平台代理不支持 WebSocket 就选 SSH 隧道**。选端口暴露时只暴露转发器端口，dsh 的 3080 不对外。

三条事实（官方文档与实测一致）：

1. **Host 栅栏只放行请求，不做认证**：`--trusted-host` 是"承认这个 authority"，真正的认证靠启动 token 和签名 cookie。不带端口的条目匹配任意端口，正好适合每次换端口的隧道。
2. **监听器绑定的那个地址自动被信任**；代理 / DNS 的 authority 必须显式加。
3. **设置页只对 loopback 浏览器开放**（本仓库实测）；远程浏览器显示 `settings are unavailable in this browser` 是设计，改配置走文件。

## 3b. 有 SSH 就够：一条命令跑完整个作业生命周期

本仓库带一个不依赖任何服务端的作业协议 [`scripts/remote_job.sh`](../scripts/remote_job.sh)：
远端只需要 `bash` + `setsid` + 一个可写目录，装上什么。它把 CANNLab `job` 那套语义搬到裸 SSH：

```bash
bash scripts/remote_job.sh doctor --host me@host        # 体检：bash/setsid/盘/卡/网络
bash scripts/remote_job.sh submit --host me@host --name exp1 --file run.sh --workdir '~/proj'
bash scripts/remote_job.sh status --host me@host --name exp1
bash scripts/remote_job.sh logs   --host me@host --name exp1 --tail 120 [--stream stderr]
bash scripts/remote_job.sh list   --host me@host
bash scripts/remote_job.sh stop   --host me@host --name exp1
bash scripts/remote_job.sh ship   --host me@host ./code '~/proj/code'
bash scripts/remote_job.sh fetch  --host me@host '~/proj/runs' ./runs
bash scripts/remote_job.sh submit --host me --ssh-opts '-p 11042 -i ~/.ssh/id_x' ...
```

设计上守着四条，和 CANNLab 的判据一致：

| 事实 | 做法 |
|:--|:--|
| 本机 job 会随会话清理 | `setsid`/`nohup` 起在远端，SSH 断开照跑 |
| 状态必须原子 | 每个作业一个目录，`status/pid/exit_code` 一律 `.tmp` + `mv` |
| 成功只有一种 | `state=finished` 且 `exit_code=0`；pid 用 `kill -0` 判活 |
| 失败要吵 | 同名作业在跑就拒（`92`）；进程没起来就报 `94`，不留"running 但没进程" |

所以"像 CANNLab 那样直接"其实不需要 CANNLab：**一个 bash 脚本 + 平台给的 SSH 就是同一套语义**。

## 4. ③ 传输：单向，且每次记 HEAD

- 代码**只从本地推上去**；远端产生的一切（checkpoint、日志、run 目录）**取回来**，不要在远端改代码再手抄回来。
- 只推必要文件：不要 `.venv`、`data/`、`.git` 历史。大数据第一次上去后转成缓存（`.npz`/`.pt`）。
- 提交前 `git status` 干净，并记下 `git rev-parse HEAD`——它进 `run_manifest.json`，是"远端跑的到底是哪一版"的唯一证据。
- 取回保持目录名不变（`runs/<experiment>/run_<ts>/`），离线复算和跨运行对比都靠这个约定。

## 5. ④ 存活：本机的进程不等于远端的进程

这是拓扑 A/C 最反直觉的一条：**DSH 结束作业时会清理子进程**，本机的隧道、前台命令都可能随时消失；
能活下来的只有远端自己托管的那份进程。

| 你做的事 | 谁在活 | 结论 |
|:--|:--|:--|
| 本机 `ops_bash({run_in_background})` 起 | DSH 的 job | 会话结束即清理，**不能**当训练载体 |
| 本机前台 `ssh host python train.py` | 本机 ssh + 远端子进程 | 断线即死 |
| 远端 `setsid`/`nohup` 或平台 `job submit` | 远端 init | 能活，**这才是载体** |

配套两条：

- **心跳**：平台常按"空闲"回收。首轮采样 / 编译预热 NPU 利用率为 0 时，先提交一个小作业占位。
- **断线 ≠ 失败**：先查远端作业状态（`state`、`exitCode`、`alive`），再查 `metrics.csv` / 增量结果，最后才决定续训还是重跑。

## 6. ⑤ 回收：关机是链路的一部分

- 计费按卡数 × 时间，**开机即烧**；回收不是"收尾"，是接入流程的最后一段。
- 默认提交时带「跑完自动关机」；超过 1 小时的作业再加一道时长护栏（如 CANNLab 的 `guard --max-hours`）。
- 顺序固定：**确认作业 finished + 产物已取回 → 关机 → 确认状态为 stopped/已释放**。
- 平台的空闲自动关机只能当兜底，不能当策略：它会在你最不想的时候砍掉长任务。

## 7. 十分钟验证清单（从零到一条可用的远端命令）

每一步都有通过判据；任一步不过，不要往下走。

| # | 做什么 | 通过判据 |
|:--|:--|:--|
| 1 | 凭据 | 登录完成，之后的无交互命令能列出资源（不报 401） |
| 2 | 建连 | 远端 `echo ok` 返回（A/C）；或 `curl --noproxy '*' 127.0.0.1:3080` 返回 200/302（B） |
| 2b | 代理与信任 | 代理按"环境变量→上次地址→直连"探测出结论；平台域名已进 `--trusted-host` |
| 3 | 身份与环境 | `whoami`、`uname -m`、`df -h` 与预期一致 |
| 4 | 设备 | 卡可见且可用（`npu-smi` / `torch.npu.is_available()`） |
| 5 | 持久盘 | 往持久目录写文件，断开重连后还在 |
| 6 | 长命令载体 | 提交一个 `sleep 60` 的远端作业，本机断开后它仍 running |
| 7 | 传输 | 取回刚写的文件，内容一致 |
| 8 | 回收 | 关机 / 停容器，状态确认，占用停止增长 |

✅ **完成标志**：8 条全过，才把"能连接"升级为"能交付"。

## 8. 失败分层：先定位在哪一段

按五段顺序排查，别一上来就重装。

| 层 | 症状 | 先查 |
|:--|:--|:--|
| 凭据 | 401 / `MISSING_CREDENTIAL` / `尚未登录` | 凭据文件、环境变量优先级、过期时间 |
| 网络 | 连接超时 / `Connection refused` / 502 | 本机代理与 VPN、远端出网代理、端口是否暴露、**实例是否开机**（平台 SSH 端口是实例级、只在运行期监听） |
| 信任 | 每个 API 都 403 / `settings are unavailable` | Host 栅栏：loopback？`--trusted-host`？转发器？ |
| 协议 | helper 启动超时 / LOCK 冲突 / 版本不匹配 | helper 日志；旧进程残留 |
| 远端环境 | 找不到 `libascendcl` / `torch.npu` 不存在 | 有没有 source 环境；包是否被覆盖 |
| 进程 | 作业 finished 但无产物 / 文件写一半 | 工作目录是否持久盘；是否原子写 |

## 9. 复用：接一个新平台的 6 步

1. **画协议链**：谁签发凭据 → 谁建隧道 → 谁执行命令 → 谁托管长任务。
2. **定拓扑**：按 §0 的三问选 A/B/C。
3. **钉持久盘**：问清"关机后哪个目录还在"，代码 / 环境 / 产物只放那里。
4. **选长命令载体**：平台作业系统（`sbatch` / `job submit`）优先；没有就用 `setsid` + `nohup`。
5. **定回收方式**：关机命令、空闲回收规则、额度上限。
6. **写平台专章 + 填一张接入记录表**，下一次换平台照表填。

写脚本时守住三条，它们决定这套东西能活多久：

- **参数化**：域名、端口、代理、模型都走命令行参数，别硬编码进脚本——换实例/换域名只改一行命令。
- **探测而非假设**：代理按"环境变量 → 上次地址 → 直连"逐级探测，网络在变而脚本不该跟着改。
- **参数持久化**：带参数运行时把本次参数写成 `run.sh`（`exec bash start.sh <参数>`）；
  重启只跑这一条，丢了也能用新参数重跑生成。

| 字段 | 本次记录 |
|:--|:--|
| 平台 / 入口 URL | |
| 认证方式 | OAuth / 密钥 / 密码；凭据存哪 |
| 拓扑 | A / B / C |
| 建连命令 | |
| 信任配置 | `--trusted-host` / 绑定地址 / 转发端口 |
| 持久盘 | 绝对路径 |
| 长命令载体 | 平台作业 / setsid |
| 回收 | 关机命令、空闲规则 |
| 已知坑 | |

## 10. 接上之后，只有三条会直接影响实验正确性

连接层之外的事按本仓库其他文档走；这三条是远程特有的，别忘：

1. **`environment.json` 必须在远端采集**。本机采到的是你的笔记本，写进论文就是错的硬件信息（[logging-guide.md](./logging-guide.md) §1）。
（DCU/昇腾容器里最容易错的是"装错 torch 版本"——务必记录实际 `torch.__version__` 与设备可见性。）
2. **成功判据只有 `state=finished` 且 `exitCode=0`**；`alive=false` 不代表成功。
3. **产物写持久盘 + 原子替换**（`.tmp` + `mv`），关机前取回（[output-spec.md](./output-spec.md) §1、[recording-guide.md](./recording-guide.md)）。
