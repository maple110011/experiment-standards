# Kaggle 接入指南：没有 SSH 的免费 T4（平台 API 批次作业）

> 这是 [remote-access.md](./remote-access.md) §0 里 **拓扑 A′** 的样本：平台不给 SSH、也不让你装 Node，只接受「提交一个脚本，平台帮你跑」。
> 实测日期 **2026-11-26**：账号、硬件、作业结果都来自真机，不是文档转述。
> 同系列样本：[cannlab-guide.md](./cannlab-guide.md)（拓扑 A，昇腾 NPU）、[scnet-guide.md](./scnet-guide.md)（拓扑 B，海光 DCU）。

## 0. 先判断：Kaggle 适合你吗

**适合**：单卡 16GB 以内的评测/微调/小型训练；需要零成本、可脚本化、每周固定额度；不需要交互式 shell。

**不适合**：单次超过 9–12 小时的训练（平台强制中断）；需要持久盘（工作盘 20GB，关机即丢）；需要 48GB+ 显存；需要随时 `ssh` 进去改环境。

| 维度 | Kaggle（A′） | CANNLab（A） | SCNet（B） | SSH 云主机（C） |
|:--|:--|:--|:--|:--|
| 命令通道 | 平台 API（CLI/HTTP） | 平台 CLI 隧道 | SSH（每实例端口） | SSH |
| 能否在远端执行任意 shell | ❌ 只能提交脚本 | ✅ | ✅ | ✅ |
| 持久盘 | ❌ 20GB 工作盘，关机即丢 | ✅ /mnt/workspace | ✅ private_data | ✅ 看平台 |
| 单次时长 | 约 9–12 小时 | 按卡时 | 按配额 | 看平台 |
| 回收 | 30 GPU 小时/周硬额度 | 按卡时，空闲关机 | 配额/排队 | 手动关机 |
| 典型坑 | 平台 ERROR 但脚本成功；无 cancel；每次重建环境 | 隧道断、CANN 未 source | SSH 端口只在开机期监听 | 忘关机 |

## 1. 协议链：五段链路在 A′ 上长什么样

| 段 | Kaggle 上的实现 | 失败长什么样 |
|:--|:--|:--|
| ① 凭据 | API token 写 `~/.kaggle/access_token`；前提是账号完成**手机验证**（免费 T4 只需手机，不需要 Persona） | 401 / `Authentication required` |
| ② 建连 | 无 SSH：CLI 直接走 `kaggle.com` HTTPS API | 连接超时（本机网络/代理） |
| ③ 传输 | `kaggle kernels push -p <dir>` 上传脚本；`kaggle kernels output` 下载产物 | 上传的代码与本地不一致；产物取回为空 |
| ④ 存活 | 平台托管 kernel，本机断开不影响；但单次最长 9–12 小时 | 跑到一半被平台结束 |
| ⑤ 回收 | 每周 30 GPU 小时硬额度；**CLI 没有 cancel** | 额度耗尽；误提交长 timeout 的作业 |

## 2. ① 凭据：token 文件 + 手机验证前提

- **前提**：免费 GPU 需要手机验证；TPU、L4×4、RTX Pro 6000 才额外要身份验证（Persona）。+86 号码可能被拒，被拒后按 [remote-access.md](./remote-access.md) §8 的凭据层排查，必要时走 Kaggle 官方的 phone verification 支持表单。
- **API token**：`https://www.kaggle.com/settings/api` 生成；存成 `~/.kaggle/access_token`（**单行纯 token**，不要 JSON），或设环境变量 `KAGGLE_API_TOKEN`（值可以是 token，也可以是 token 文件路径）。
- **不要用**「把 token 贴进对话」的方式交接：让用户自己复制/生成文件，agent 只读文件。
- **交互式 OAuth**（`kaggle auth login`）要求把浏览器里的验证码粘回终端，DSH 的非交互 shell 里做不了，**优先 token 文件**。
- 凭据目录默认 `~/.kaggle`；如果必须在 workspace 内使用，设 `KAGGLE_CONFIG_DIR=<path>` 并把该目录加进 `.gitignore`。

## 3. ② 提交：作业协议

原生 CLI 的五条命令（这是 A′ 的核心，等价于 SSH 拓扑里的 submit/status/logs/fetch）：

```bash
kaggle kernels push   -p <staging> --accelerator NvidiaTeslaT4 -t 1800   # 提交（-t 是超时秒数）
kaggle kernels status  <owner>/<slug>                                    # 状态
kaggle kernels logs    <owner>/<slug> [-f]                               # 日志（-f 跟随）
kaggle kernels output  <owner>/<slug> -p <out>                           # 取回产物
kaggle kernels list    -m --page-size 5                                  # 我最近的内核
```

本仓库把它封装成和 `remote_job.sh` 同语义的适配器 [`scripts/kaggle_job.py`](../scripts/kaggle_job.py)：

```bash
python scripts/kaggle_job.py doctor        # CLI、登录、额度、磁盘体检
python scripts/kaggle_job.py quota         # 本周剩余 GPU/TPU 小时（成本护栏）
python scripts/kaggle_job.py submit --name exp1 --file job.py --timeout-seconds 28800
python scripts/kaggle_job.py status --name exp1 --wait 3600 --interval 30
python scripts/kaggle_job.py logs   --name exp1 -f
python scripts/kaggle_job.py fetch  --name exp1
python scripts/kaggle_job.py list
```

提交时适配器会在 `jobstate/<name>/kernel/` 生成 `kernel-metadata.json`，关键字段：

| 字段 | 值 | 说明 |
|:--|:--|:--|
| `id` | `<username>/<slug>` | 用户名从 `kaggle config view` 读；没有就用 `--owner` |
| `code_file` / `language` / `kernel_type` | `job.py` / `python` / `script` | 脚本模式，从上到下执行 |
| `is_private` | `true` | 私有内核，别把实验代码公开 |
| `enable_gpu` / `enable_internet` | `true` / `true` | 评测/装包都要联网 |
| `dataset_sources` | `[owner/dataset]` | 私有数据挂载到 `/kaggle/input/<dataset>` |

**成功判据只有一种**：平台状态 `COMPLETE` **且** 取回的 `result.json` 里 `exit_code == 0`。

## 4. ③ 作业脚本契约（最容易踩坑的一节）

被推上去的脚本必须自己写产物，因为平台只负责「跑完/没跑完」，不会传回你的退出码：

| 文件 | 必须 | 说明 |
|:--|:--:|:--|
| `/kaggle/working/environment.json` | ✅ | 远端采集的硬件信息（fork 自 [logging-guide.md](./logging-guide.md)） |
| `/kaggle/working/run.log` | ✅ | 人类可读的日志 |
| `/kaggle/working/result.json` | ✅ | 至少含 `exit_code`；建议带 metrics、error |
| `/kaggle/working/metrics.csv` | 建议 | 逐阶段/逐数据集指标 |

四条硬规则：

1. **不要替换 `sys.stdout` / `sys.stderr`**。Kaggle 的执行器依赖标准输出捕获；换成自己的 Tee 对象后，即使脚本成功、`result.json` 写了 `exit_code=0`，平台也会把 kernel 标成 `ERROR`。直接 `print` 即可，需要 `run.log` 就在末尾把结果写一份。（2026-11-26 实测复现并修复。）
2. **不要在脚本末尾调用 `sys.exit()`**。脚本是转成 notebook 执行的，SystemExit 会被当成异常处理；让脚本自然结束即可。
3. **工作盘 20GB、关机即丢**。checkpoint / 预测分布必须在脚本里打包成 Kaggle Dataset，或者跑完立刻 `fetch` 取回。
4. **环境每次重建**。`pip install` 约 1–2 分钟，写进脚本；不要指望上一次装的包还在。

此外：

- **私有数据**：`kaggle datasets create -p <dir>` 建私有数据集，提交时加 `--dataset owner/name`。
- **TabPFN 2.x**：本地权重下载前会校验 license，需要 `TABPFN_TOKEN`（<https://ux.priorlabs.ai> 接受 license 后拿 API Key）。在 Kaggle 里用 **Add-ons → Secrets** 添加同名 Secret，脚本内 `UserSecretsClient().get_secret("TABPFN_TOKEN")` 读出来再 `fit()`。模板见 [`scripts/templates/kaggle_pfn_eval.py`](../scripts/templates/kaggle_pfn_eval.py)。
- **模板**：冒烟 [`kaggle_smoke.py`](../scripts/templates/kaggle_smoke.py)、通用入口 [`kaggle_entry.py`](../scripts/templates/kaggle_entry.py)、迷你 PFN 训练 [`kaggle_pfn_train_smoke.py`](../scripts/templates/kaggle_pfn_train_smoke.py)。

## 5. 硬件与额度（2026-11-26 实测）

| 项 | 值 |
|:--|:--|
| GPU | Tesla T4 ×2，每张 15360 MiB，驱动 580.178.04 |
| torch | 2.11.0+cu130（预装，CUDA 可用） |
| CPU / 内存 | 4 vCPU / 29 GiB |
| 工作盘 | `/kaggle/working` 20 GB |
| Python | 3.13.16 |
| GPU 额度 | **30 小时/周**（UTC 周六刷新；`kaggle quota --format json` 可查剩余） |
| 实算校验 | 1024×1024 矩阵乘通过；400 步 0.53M 参数 PFN 训练 6.8 秒、loss 2.266→0.019、峰值显存 122 MiB |

额度换算：一个 CC18 完整评测轮约 2–8 GPU 小时（TabPFN 类模型的实测口径），30 小时/周大约够 4–15 轮。

## 6. 验证清单（A′ 改造版）

| # | 做什么 | 通过判据 |
|:--|:--|:--|
| 1 | 凭据 | `kaggle quota --format json` 返回额度而不是 401 |
| 2 | 提交通道 | `kernels push` 返回 `Kernel version N successfully pushed` |
| 3 | 身份与环境 | kernel 里打印的 hostname / python / python 版本与记录一致 |
| 4 | 设备 | kernel 里 `nvidia-smi` 看到 T4，`torch.cuda.is_available()=True` |
| 5 | 持久化（改造） | 没有持久盘：产物以 `fetch` 取回、内容与远端一致；或已发布为 Dataset |
| 6 | 长命令载体 | 提交一个 10 分钟的 kernel，本机断开后它仍 RUNNING |
| 7 | 传输 | `fetch` 取回刚写的 `result.json`，`exit_code` 可读 |
| 8 | 回收（改造） | `quota` 显示的已用小时数随运行增长、kernel 结束后停止增长 |

✅ **完成标志**：8 条全过，且至少有一个真实实验产物取回。

> 本仓库整合后（2026-11-26）用 `bash scripts/stage1_kaggle.sh integration 1800` 从本仓库根目录复验过一次：
> 提交 → 状态 `COMPLETE` → 拉日志 → 取回 `environment.json`/`result.json`，`exit_code=0`，
> 设备为 Tesla T4 ×2、torch 2.11.0+cu130。

## 7. 失败分层（Kaggle 专有）

| 症状 | 先查 |
|:--|:--|
| 401 / `Authentication required` | token 文件路径与格式；`kaggle config view` 的 username；token 是否被重新生成覆盖 |
| 平台 `ERROR`，但日志里结果正常、`result.json` 是 `exit_code=0` | 是否替换了 `sys.stdout/stderr`（见 §4）；是否调用了 `sys.exit` |
| `TabPFNLicenseError` | 没有 `TABPFN_TOKEN` 或 Secret 未挂载 |
| `No space left on device` | `/kaggle/working` 20GB 用满：中间产物写到 `/tmp` 或及时清理 |
| 一直是 `QUEUED` | 平台排队；免费档高峰时段常见，等或换时间 |
| 到时长上限被杀 | 单次 9–12 小时；长训练必须拆成可续训的小段 |
| 额度耗尽 / 不能开 GPU | `kaggle quota`；等周六刷新或改用备选平台 |
| 403 / CSP / 人机验证加载不出来 | 这是浏览器侧（登录网页）的问题，不是 API 侧；见 [remote-access.md](./remote-access.md) 与 pfn 仓库的 reCAPTCHA 说明 |

## 8. 回收与成本护栏

- **最强护栏是平台硬额度**：30 GPU 小时/周，不绑卡、不会超支；每次提交前用 `kaggle_job.py quota` 看一眼。
- **没有 cancel 命令**：CLI 只能查/取，取消要去网页；所以提交前把 `--timeout-seconds` 设成合理值。
- **不要并发多个 GPU kernel**：额度按 GPU 小时计，排队也计入等待成本（社区口径），免费档并发容易互相挤掉。
- 免费卡型以队列实际分配为准（官方文档列 P100 与 T4×2；2026-09 起有 P100 退役的社区报告）。

## 9. 接入记录表（本次实测已填）

| 字段 | 本次记录 |
|:--|:--|
| 平台 / 入口 | Kaggle（kaggle.com），免费 GPU T4×2 |
| 认证方式 | API token，`~/.kaggle/access_token`；前提手机验证 |
| 拓扑 | **A′**：本地 DSH + 平台 API 批次作业 |
| 建连命令 | 无 SSH；`python scripts/kaggle_job.py submit/status/logs/fetch` |
| 信任配置 | 无（HTTPS 公网 API） |
| 持久盘 | 无；`/kaggle/working` 20GB 关机即丢 |
| 长命令载体 | 平台 kernel（单次 9–12h） |
| 回收 | 30 GPU 小时/周；无 cancel |
| 已知坑 | stdout 劫持导致平台 ERROR；TabPFN token；20GB 爆盘；每次重建环境 |

## 10. 复用到别的「平台 API 批次作业」平台

任何满足下面五条的平台，都可以套用本指南的「脚本契约 + result.json 判据」模板，只换 §3 的命令：

1. 有 CLI/HTTP API 能提交作业（不需要 SSH）；
2. 有状态查询接口（能区分 queued/running/完成/失败）；
3. 能取回产物（下载输出目录或对象存储）；
4. 有明确的单次时长上限与额度上限；
5. 能挂载私有数据/持久存储（否则产物只能靠一次性取回）。

判据和原则与 [remote-access.md](./remote-access.md) §9 完全一致：**参数化、探测而非假设、成功判据唯一**。差别只在于「建连」这一段的实现从 SSH 换成了平台 API。
