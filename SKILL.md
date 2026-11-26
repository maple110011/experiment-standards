---
name: experiment-standards
description: |-
  Use this skill whenever the user is building, fixing, or running an ML experiment: checkpoint/resume after a crash, split training and error logs, cross-device environment capture, early stopping and LR scheduling, batch-size↔lr scaling, NaN/OOM recovery, evaluation reports, standard output directory, the experiment_recorder pack (manifest, code snapshot, per-epoch metrics, saved predictions, calibration curves, TensorBoard), long-running launch with 1-epoch benchmarking, cached datasets. Also when the compute is remote — 昇腾 NPU/CANNLab、超算互联网/SCNet 海光 DCU、SSH 云主机、Kaggle 免费 GPU（没有 SSH，只能用平台 API 提交/查状态/取回产物）：先选拓扑（本地 DSH+命令通道 / 远端 dsh+浏览器 / 平台 API 批次作业）、凭据与隧道、代理与持久盘、长命令载体、验证与关机关时。 Trigger even if the user only says 跑一下、复现不了、结果对不上、换了机器结果不一样、实验挂了一半、显存不够、batch 该多大、受限 shell 里 GPU 不可用，或问 日志/早停/学习率/输出目录/超参搜索/远程跑实验 怎么弄. Do NOT use for architecture design or inference-method choice (use bayes-dl-dcu for BDL calibration). If the bottleneck is human comprehension rather than compute — 信息过载、跟不上 agent、看不懂结果、分不清噪声与改进、想积累方法洞见 — use collab-lab.
argument-hint: '[任务: checkpoint管理 / 实验日志 / 环境记录 / 早停 / 评估报告 / 输出物规范 / 长任务·大模型训练 / 远程接入·CANNLab·SCNet·Kaggle免费GPU]'
---

# ML 实验标准化

ML 实验常因缺少基础设施导致：训练中断后重来、不同设备结果不可比、评估靠肉眼、超参搜索输出混乱。本 Skill 为训练脚本一键添加完整的实验工程基础设施，确保每次实验输出规范、可复现、可跨设备比较。

## 核心原则

1. **每个训练脚本必须产出标准化输出** — 环境记录、检查点、日志、评估报告缺一不可
2. **训练状态可恢复** — Checkpoint 包含完整状态（参数+optimizer+RNG），支持断点续训
3. **错误信息不丢失** — 错误日志独立于训练日志，空文件 = 无错误
4. **实验结果可跨设备比较** — 每次运行记录完整的硬件信息（CPU型号/核数/GPU/RAM）
5. **评估结果结构化** — JSON 格式评估报告，可脚本化批量对比

## 工作流

按顺序执行以下 7 步。每一步标注了对应的参考文档，需要详细信息时读取。

### 第 1 步: 设置输出目录结构

每个训练脚本必须创建以下目录结构：

```
outputs/
├── environment.json          # 运行环境
├── seed.json                 # 随机种子
├── experiment_metadata.json  # 元数据 (环境+config+数据集规模)
├── training.log              # 完整训练日志
├── errors.log                # 错误日志 (仅ERROR, 空文件=无错误)
├── metrics.csv               # 逐epoch指标
├── checkpoints/
│   ├── ckpt_epoch*.tar       # 中间checkpoint (含RNG state)
│   └── ckpt_best.tar         # 最佳模型
├── best_model.pt             # 最佳模型权重
├── final_model.pt            # 最终模型权重 (建议保留)
├── evaluation_report.json    # 结构化评估报告
└── figures/                  # 图表输出
```

> ✅ **完成标志**: `os.makedirs` 已创建 `checkpoints/` 和 `figures/` 目录

### 第 2 步: 记录运行环境 ⚠️

在训练开始时捕获硬件信息。将 `assets/templates/environment_capture.py` 复制到用户项目中，然后调用。详见 [logging-guide.md](./references/logging-guide.md) §1。

**必须记录**: CPU型号/核数、GPU型号/VRAM/架构、总RAM、PyTorch版本、CUDA/HIP 版本、
`hy-smi` 驱动版本（DCU/ROCm）、磁盘可用空间、运行时环境（Colab/Local）、关键依赖版本。

```python
from environment_capture import capture_environment
env = capture_environment()
json.dump(env, open("environment.json", "w"), indent=2, ensure_ascii=False, default=str)
json.dump({"seed": CONFIG["seed"]}, open("seed.json", "w"), indent=2)
```

> ✅ **完成标志**: `environment.json` 和 `seed.json` 已保存

### 第 3 步: 配置日志系统 ⚠️

三级日志架构：控制台 (INFO+) + 训练日志文件 (DEBUG+) + 错误日志文件 (ERROR+)。详见 [logging-guide.md](./references/logging-guide.md) §2。

```python
# 三个 handler: StreamHandler(INFO) + FileHandler(training.log, DEBUG) + FileHandler(errors.log, ERROR)
```

> ✅ **完成标志**: `training.log` 和 `errors.log` 已开始写入

### 第 4 步: 集成 Checkpoint 系统 ⚠️

将 `assets/templates/checkpoint_manager.py` 复制到用户项目中。详见 [checkpoint-guide.md](./references/checkpoint-guide.md)。

```python
from checkpoint_manager import CheckpointManager, capture_rng_state, restore_rng_state
# mode="min" 用于 loss/rmse, accuracy/ELBO 等用 mode="max"
ckpt_mgr = CheckpointManager("checkpoints", keep_recent_n=3, mode="min")
resume = ckpt_mgr.load()  # 尝试断点续训
if resume:
    # PyTorch: model.load_state_dict(resume["model_state"])
    # Pyro:   pyro.get_param_store().set_state(resume["model_state"])
    restore_rng_state(resume["rng_state"])
# 训练循环中: ckpt_mgr.save(epoch, config, model_state, opt_state, capture_rng_state())
# 评估后: if ckpt_mgr.update_best(epoch, val_metric): ckpt_mgr.save(..., is_best=True)
```

> ✅ **完成标志**: Checkpoint 可正常 save/load; 中断重启可恢复训练

### 第 5 步: 添加 Early Stopping + LR 调度

将 `assets/templates/early_stopper.py` 复制到用户项目中。详见 [training-control.md](./references/training-control.md)。

```python
from early_stopper import EarlyStopper
stopper = EarlyStopper(patience=15, min_delta=1e-4, mode="min")  # accuracy/ELBO 用 mode="max"
lr = get_lr(epoch)  # warmup + 阶梯衰减，见 training-control.md §2
```

> ✅ **完成标志**: 早停和 LR 调度逻辑已嵌入训练循环

### 第 6 步: CSV 指标 + NaN 检测

详见 [resilience-guide.md](./references/resilience-guide.md)。

```python
csv_logger.writerow({"epoch": e, "train_loss": loss, "val_metric": val, "lr": lr})
if not np.isfinite(float(loss)):  # 自动回退checkpoint + 降lr，见 resilience-guide.md §1
```

### 第 7 步: 生成评估报告 + 导出模型 + 实验元数据

详见 [output-spec.md](./references/output-spec.md)。

```python
# 评估报告 (模板: assets/templates/evaluation_report.py)
from evaluation_report import generate_evaluation_report
generate_evaluation_report(metrics, env, CONFIG, "outputs/evaluation_report.json")
# 模型导出
torch.save({"model_state": model.state_dict(), "config": CONFIG, "best_epoch": best_epoch}, "best_model.pt")
torch.save({"model_state": model.state_dict(), "config": CONFIG}, "final_model.pt")
# 实验元数据
json.dump({"experiment_name": "...", "environment": env, "config": CONFIG, "dataset": {...}}, open("experiment_metadata.json", "w"), indent=2, default=str)
```

## 代码输出要求

Agent 生成的代码必须在训练结束后产生以下文件：

| 文件 | 必须 | 说明 |
|------|:---:|------|
| `environment.json` | ✅ | 硬件环境 |
| `seed.json` | ✅ | 随机种子 |
| `experiment_metadata.json` | ✅ | 元数据 (环境+config+数据集) |
| `training.log` | ✅ | 完整日志 |
| `errors.log` | ✅ | 错误日志 |
| `metrics.csv` | ✅ | 逐epoch指标 |
| `checkpoints/ckpt_best.tar` | ✅ | 最佳checkpoint |
| `best_model.pt` | ✅ | 最佳模型权重 |
| `final_model.pt` | 建议 | 最终模型权重 |
| `evaluation_report.json` | ✅ | 评估报告 |
| `figures/` | ✅ | 图表 |

## 大型实验记录包 (长实验必读)

长时间训练、多方法对比、需要事后复算指标或写论文的实验，**必须**使用
`assets/templates/experiment_recorder.py` 生成标准记录包（代码快照、完整配置、
事件时间线、每方法训练曲线、预测概率/样本、增量结果）。详细规范见
[recording-guide.md](./references/recording-guide.md)。核心要求:

- `make_run_dir()` 创建 `runs/<experiment>/run_<时间戳>/`，并自动写 `run_manifest.json`
- 分类预测概率用 `save_probs`、回归均值/方差用 `save_regression_predictions`、
  采样类方法用 `save_samples_npz` —— 预测分布必须落盘，只存最终指标是最大的坑
- 每完成一个方法/阶段立即 `update_results_json`；数据切分后立即 `save_split_indices`
- 每方法逐 epoch 指标写入 `training/<method>_metrics.csv`，**验证集指标也要逐 epoch 记录**
- 记录代码哈希、git commit、完整依赖版本、数据集 sha256、模型结构和显存占用
- TensorBoard events 自动写入 `run_dir/tb/`，校准曲线用
  `plot_reliability_diagram()` / `plot_regression_calibration()` 自动生成
- 分布偏移/OOD 结果用 `update_shift_results_json` 写 `evaluation_shift.json`；
  温度缩放等后校准用 `save_temperature_scaling` 写 `calibration_temperature.json`
- 模型权重用 `save_model_weights` 存 best/final；所有 except 块调 `log_exception` 写 errors.log

## 长任务 / 大模型训练 (跑长实验必读)

一次训练动辄 30 分钟到数小时的实验，出错代价极高。启动前先读
[long-running-guide.md](./references/long-running-guide.md)，核心纪律:

- **先测 1-epoch 基准**：测出单 epoch 耗时 / 峰值显存 / loss 下降速度，再外推全量配置
- **后台启动 + 超时余量**：`setsid ... &`，`--timeout` 大于预计总时长，轮询 `results_partial.json`
- **受限 shell 跑 DCU/ROCm**：bash 里 `torch.cuda.is_available()` 可能是 False（假象），
  必须走 `scripts/jupyter_exec.py` 的 Jupyter kernel，并在 kernel 里采集环境
  （独立部署时把该脚本复制到工作区）
- **增量落盘**：每完成一个方法/阶段立即写 `results_partial.json`
- **显存与算力分开监控**：结果里记录 `gpu_memory_gb`，训练中定期看 allocated/reserved
- **大数据先转 `.npz` 缓存**，避免每 epoch 重复解析
- **大 batch 优先 + lr 缩放**：先测吞吐再定 batch，`2 的幂不是魔法`，必须实测
- **装包保护 HIP torch**：HIP/ROCm 环境里依赖 torch 的 PyPI 包用 `pip install --no-deps`，
  装完检查 `torch.version.hip` 和 `torch.cuda.is_available()`

## 远程接入 (把算力接进 DSH)

本机没卡、卡不够用、或要用昇腾 NPU 时，**先解决的问题不是怎么跑实验，而是怎么让 DSH 够得着那台机器**。
接法只有三种拓扑，选错会白折腾半天；五段链路（凭据 → 建连 → 传输 → 存活 → 回收）在哪个平台都一样。
动手前先读 [remote-access.md](./references/remote-access.md)，核心:

- **先问有没有 SSH**：有就直接本地 DSH + `ssh` + [scripts/remote_job.sh](./scripts/remote_job.sh)
  （提交/状态/日志/终止/取回一条命令，远端只需 bash+setsid），别急着把 dsh 装进远端。
  注意平台 SSH 常见是**每实例一个专属端口、只在开机期间监听**，登录命令去实例页面复制，
  不要用"我测了 22 端口不通"下结论
- **再选拓扑**：平台只给 WebIDE/SSH、连接要自己建 → 本地 DSH + 命令通道
  （[cannlab-guide.md](./references/cannlab-guide.md) 昇腾 NPU）；容器能装 Node、出网受限 →
  dsh 装进远端、本地只留浏览器（[scnet-guide.md](./references/scnet-guide.md) SCNet 海光 DCU）；
  普通云主机 → 本地 DSH + OpenSSH
- **`dsh web` 只监听 loopback、拒绝通配地址**：跨机访问只能 SSH 隧道 / 平台转发 / CLI 一次性隧道；
  `--trusted-host` 只是承认 authority，不代替认证
- **本机的进程 ≠ 远端的进程**：DSH 会清理子进程，长命令必须交给远端 `setsid`/`nohup` 或平台作业系统
- **代码单向推上去、产物取回来**；每次记下 `git rev-parse HEAD`
- **回收是链路的最后一段**：跑完自动关机、长作业加时长护栏、确认 stopped 才算结束
- **没有 SSH 的免费 GPU（Kaggle）走拓扑 A′**：用平台 CLI 提交/查状态/取回产物；不能执行任意 shell、没有持久盘、单次 9–12 小时、30 GPU 小时/周。
  成功判据不能只看平台状态——作业必须自己写 `result.json`（含 `exit_code`），主机侧校验 `exit_code=0`；
  作业脚本里**不要替换 `sys.stdout/stderr`**、**不要 `sys.exit()`**，否则平台会把成功作业标成 ERROR。见 [kaggle-guide.md](./references/kaggle-guide.md)。

✅ **完成标志**: 通过 [remote-access.md](./references/remote-access.md) §7 的 8 条验证
（凭据 / 建连 / 设备 / 持久盘 / 长命令载体 / 传输 / 回收），再接实验

## 何时读取参考资源

根据用户的具体需求，选择性读取以下参考文档：

| 用户需求 | 应读取的文档 | 关键章节 |
|----------|-------------|---------|
| 加 checkpoint 保存/恢复 | [checkpoint-guide.md](./references/checkpoint-guide.md) | §1-2; Pyro 用户加读 §3 |
| 加早停 / 调学习率 / batch 缩放 | [training-control.md](./references/training-control.md) | §1 (早停), §2 (LR调度), §2 末 (batch↔lr缩放) |
| 长任务 / 大模型 / 1-epoch 基准 / 后台运行 | [long-running-guide.md](./references/long-running-guide.md) | 全部 |
| 建立远程接入 / 选拓扑 / 通道与信任 / 验证清单 / 换平台复用 | [remote-access.md](./references/remote-access.md) | §0 拓扑, §1 五段链路, §3 通道, §3b SSH 作业协议, §7 验证, §9 复用表 |
| 用 SSH 在远端跑长作业（提交/状态/日志/终止/取回） | [scripts/remote_job.sh](./scripts/remote_job.sh) | 全部（`--help`） |
| Kaggle 免费 GPU / 没有 SSH 的平台 / 平台 API 作业协议 / TabPFN 权重许可 / 20GB 工作盘 | [kaggle-guide.md](./references/kaggle-guide.md) | §0 适用性, §2 凭据, §3 作业协议, §4 脚本契约（必读）, §6 验证, §7 失败分层 |
| 用 Kaggle 免费 GPU 跑作业（提交/状态/日志/取回） | [scripts/kaggle_job.py](./scripts/kaggle_job.py) | 全部（`--help`）；模板在 `scripts/templates/` |
| 本地 DSH 遥控昇腾 NPU / CANNLab CLI / 隧道 / job / 卡时 | [cannlab-guide.md](./references/cannlab-guide.md) | §1 协议链, §2 SOP, §4 隧道, §7 job, §8 回收 |
| SCNet 海光 DCU 接入 / SSH 直连 / 无 SSH 兜底 / DCU 实验纪律 | [scnet-guide.md](./references/scnet-guide.md) | §0 三种形态, §0.6 SSH 事实, §1 通道, §9 DCU 实验 |
| 记录环境信息 / 配日志 | [logging-guide.md](./references/logging-guide.md) | §1 (环境), §2 (日志), §3 (CSV), §4 (元数据) |
| 规范输出目录 / 评估报告 / 模型导出 | [output-spec.md](./references/output-spec.md) | §1 (目录), §2 (报告), §3 (导出); Pyro/MCMC 用户加读 §3 后半 |
| 训练崩溃恢复 / NaN处理 / 内存管理 | [resilience-guide.md](./references/resilience-guide.md) | §1 (NaN), §2 (梯度), §3 (回退), §4 (DataLoader), §5 (内存) |
| 大型实验记录 / 可复现记录包 / 预测分布保存 / 分布偏移 / 温度缩放 | [recording-guide.md](./references/recording-guide.md) | 全部 |
| 结果太多看不懂 / 下一步该做什么 / 想积累方法洞见 / 分清噪声与改进 / 想从实际问题里长出理论问题 | [`collab-lab/SKILL.md`](./collab-lab/SKILL.md) | 全部（人机协作回路 + 三级台账） |


## 领域相关 Skill

本仓库同时包含两个子 skill，各自负责本 skill 不覆盖的部分：

**`bayes-dl-dcu/`** — 贝叶斯深度学习的方法选择、校准指标、分布偏移/OOD、
DCU 适配和大模型训练经验：

- **海光 DCU / ROCm/HIP 环境记录与 Pyro 设备恢复**：`environment_capture.py` 模板已处理
  硬件识别；DCU 适配、Pyro 恢复细节、算子编译 warmup 等见
  [`bayes-dl-dcu/references/dcu-adaptation.md`](./bayes-dl-dcu/references/dcu-adaptation.md)。
- **贝叶斯深度学习方法与校准指标**（SVI/Deep Ensemble/SWAG/Laplace/SGHMC/MC Dropout、
  ECE/sharpness/test_log_likelihood、最佳模型判断 mode）见
  [`bayes-dl-dcu/SKILL.md`](./bayes-dl-dcu/SKILL.md)。
- 生成 BDL 实验代码时，两个 skill 配合使用：本 skill 负责工程基础设施和记录包，
  `bayes-dl-dcu` 负责方法对比协议、校准评估和分布偏移实验设计。

**`collab-lab/`** — 人机协作回路。本 skill 的产出物是给机器复现用的（run manifest、
events、预测分布），`collab-lab` 负责把它们变成**人能判断**的形状：

- **什么时候用**：agent 跑得比人读得快、结果一多就失去方向、分不清分数变化是噪声
  还是改进、想同时积累对实际问题的考察和对方法本身的洞见、**想从实际问题里生发出
  可探索的理论问题**。
- **三层回路**：L1 执行与记录（本 skill，不动）→ L2 预注册协议块（跑之前先定判据，
  人批准）→ L3 摘要卡 + 决策卡 + 三级台账（人决策，agent 不自作主张）。
- **三级台账**：问题台账（这个实际问题长什么样）→ 方法台账（这个方法在此条件下
  怎么回事，必须是可证伪的主张）→ **理论台账**（实践需要而方法给不了、且现有框架
  解释不了的东西；这是"从实际问题里长出理论问题"的唯一去处）。第三层用
  `collab-lab/references/theory-ladder.md` 的七级梯子生成，两条机械把关：张力必须
  含数字、理论问题里不许出现"怎么/如何让"。
- **硬闸门**：一个闸门 = 一个协议块；跑完必须等人回答；批准前不写消耗算力的代码。
- **可执行检查**：`collab-lab/scripts/score_noise_floor.py`（评测噪声下界与最小可检测
  效应）、`collab-lab/scripts/check_collab_artifacts.py`（摘要卡/协议块/三级台账校验、
  反向自检、evals 执行器）。
- 详见 [`collab-lab/SKILL.md`](./collab-lab/SKILL.md)。

## 可复用模板

以下模板文件可直接复制到用户项目中使用：

| 模板 | 路径 |
|------|------|
| CheckpointManager 类 | `assets/templates/checkpoint_manager.py` |
| EarlyStopper 类 | `assets/templates/early_stopper.py` |
| capture_environment() 函数 | `assets/templates/environment_capture.py` |
| generate_evaluation_report() / generate_experiment_metadata() | `assets/templates/evaluation_report.py` |
| experiment_recorder（大型实验记录包） | `assets/templates/experiment_recorder.py` |
| ECE/NLL/Brier/sharpness/coverage 指标 | `assets/templates/metrics.py` |

## 参考资源

| 资源 | 内容 |
|------|------|
| [checkpoint-guide.md](./references/checkpoint-guide.md) | Checkpoint 管理 (保存/恢复/最佳/清理) |
| [training-control.md](./references/training-control.md) | Early Stopping + LR 调度 + batch 缩放 |
| [logging-guide.md](./references/logging-guide.md) | 环境记录 + 日志系统 + CSV + 元数据 |
| [output-spec.md](./references/output-spec.md) | 输出目录规范 + 评估报告格式 + 模型导出 |
| [resilience-guide.md](./references/resilience-guide.md) | NaN/Inf 检测、梯度异常、DataLoader、内存管理 |
| [recording-guide.md](./references/recording-guide.md) | 大型实验记录包、预测样本、校准曲线、增量结果 |
| [long-running-guide.md](./references/long-running-guide.md) | 长任务/大模型训练：1-epoch 基准、后台启动、显存/算力监控、batch 缩放、卡型选型 |

## 示例用法

```
# 为训练脚本添加 checkpoint 和早停
/experiment-standards 给我的训练脚本加上 checkpoint 和 early stopping

# 标准化实验输出
/experiment-standards 让这个脚本输出规范的实验记录（环境信息+日志+评估报告）

# 添加完整基础设施
/experiment-standards 为这个训练代码添加完整的实验基础设施

# 长任务/大模型训练
/experiment-standards 我要跑一个 30 分钟的大实验，帮我先测 1-epoch 基准、后台启动并记录显存

# 远程接入
/experiment-standards 我想在 DSH 里直接驱动 CANNLab 的昇腾 NPU，从登录到能发一条远端命令，要配哪些东西？
/experiment-standards SCNet 的海光 DCU 容器里想常驻一个 dsh、本地浏览器遥控，容器重启后怎么一条命令恢复？
/experiment-standards 换一个新的云平台（只有 SSH + sbatch），怎么把 DSH 接上去、怎么验证？
```
