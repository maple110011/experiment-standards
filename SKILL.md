---
name: experiment-standards
description: 'Always use this skill when the user asks to standardize ML experiment outputs, needs reproducible training infrastructure, or mentions checkpoint management, experiment logging, environment recording, evaluation reports, early stopping, LR scheduling, training resilience (NaN recovery), or output directory structures — even if they don\'t explicitly say "experiment standards". Also trigger when the user complains about 训练中断无法恢复、实验结果无法复现、不同设备跑出来结果不一样、缺少实验记录、不知道怎么加日志/早停/学习率调度/NaN检测、想做 grid search 但输出一团乱、需要规范输出目录结构等任何训练工程化需求, 跑长实验/大模型担心中途挂掉/超时、想先测 1-epoch 基准、batch size 怎么定和缩放、显存/算力怎么监控, or wants large-experiment record packs, run manifests, code snapshots, prediction sample saving, incremental result logging, calibration curves/TensorBoard, temperature scaling / distribution-shift evaluation recording, or hits 受限 shell 里 GPU 不可用/`torch.cuda.is_available()` 误报 False、装包把 HIP torch 覆盖成 CUDA torch、预测概率没落盘导致换指标要重跑. Covers: checkpoint save/resume with sha256 sidecars and damaged-checkpoint fallback, hardware environment capture (CPU/GPU/RAM/DCU/HIP/MPS + driver/package versions), seed recording, training/error log separation, CSV metrics tracking, structured evaluation reports (JSON), model weight export (best/final), output directory specification, early stopping, learning rate scheduling (warmup/decay/cosine), NaN/Inf detection and auto-recovery, DataLoader best practices, memory profiling, batch-size↔learning-rate scaling, long-running background launch and 1-epoch benchmarking, experiment runner (grid search), reusable experiment_recorder for long runs (run manifest, code snapshot, data hash, event timeline, per-method metrics, TensorBoard, prediction probability/mean-variance/sample saving, incremental results, calibration curves, temperature-scaling and distribution-shift logging), and restricted-shell GPU access via Jupyter kernel. Framework-agnostic but includes Pyro/PyTorch examples. Do NOT use for: model architecture design, inference method selection, prior selection, uncertainty calibration — those belong to domain-specific skills.'
argument-hint: '[任务: checkpoint管理 / 实验日志 / 环境记录 / 早停 / 评估报告 / 输出物规范 / 长任务·大模型训练]'
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
  必须走 `gpu-runner/jupyter_exec.py` 的 Jupyter kernel，并在 kernel 里采集环境
  （该脚本随 skill 备份在 `scripts/jupyter_exec.py`，独立部署时可复制到工作区）
- **增量落盘**：每完成一个方法/阶段立即写 `results_partial.json`
- **显存与算力分开监控**：结果里记录 `gpu_memory_gb`，训练中定期看 allocated/reserved
- **大数据先转 `.npz` 缓存**，避免每 epoch 重复解析
- **大 batch 优先 + lr 缩放**：先测吞吐再定 batch，`2 的幂不是魔法`，必须实测
- **装包保护 HIP torch**：HIP/ROCm 环境里依赖 torch 的 PyPI 包用 `pip install --no-deps`，
  装完检查 `torch.version.hip` 和 `torch.cuda.is_available()`

## 何时读取参考资源

根据用户的具体需求，选择性读取以下参考文档：

| 用户需求 | 应读取的文档 | 关键章节 |
|----------|-------------|---------|
| 加 checkpoint 保存/恢复 | [checkpoint-guide.md](./references/checkpoint-guide.md) | §1-2; Pyro 用户加读 §3 |
| 加早停 / 调学习率 / batch 缩放 | [training-control.md](./references/training-control.md) | §1 (早停), §2 (LR调度), §2 末 (batch↔lr缩放) |
| 长任务 / 大模型 / 1-epoch 基准 / 后台运行 | [long-running-guide.md](./references/long-running-guide.md) | 全部 |
| 记录环境信息 / 配日志 | [logging-guide.md](./references/logging-guide.md) | §1 (环境), §2 (日志), §3 (CSV), §4 (元数据) |
| 规范输出目录 / 评估报告 / 模型导出 | [output-spec.md](./references/output-spec.md) | §1 (目录), §2 (报告), §3 (导出); Pyro/MCMC 用户加读 §3 后半 |
| 训练崩溃恢复 / NaN处理 / 内存管理 | [resilience-guide.md](./references/resilience-guide.md) | §1 (NaN), §2 (梯度), §3 (回退), §4 (DataLoader), §5 (内存) |
| 大型实验记录 / 可复现记录包 / 预测分布保存 / 分布偏移 / 温度缩放 | [recording-guide.md](./references/recording-guide.md) | 全部 |


## 领域相关 Skill

本仓库同时包含子 skill **`bayes-dl-dcu/`**，负责贝叶斯深度学习的方法选择、
校准指标、分布偏移/OOD、DCU 适配和大模型训练经验：

- **海光 DCU / ROCm/HIP 环境记录与 Pyro 设备恢复**：`environment_capture.py` 模板已处理
  硬件识别；DCU 适配、Pyro 恢复细节、算子编译 warmup 等见
  [`bayes-dl-dcu/references/dcu-adaptation.md`](./bayes-dl-dcu/references/dcu-adaptation.md)。
- **贝叶斯深度学习方法与校准指标**（SVI/Deep Ensemble/SWAG/Laplace/SGHMC/MC Dropout、
  ECE/sharpness/test_log_likelihood、最佳模型判断 mode）见
  [`bayes-dl-dcu/SKILL.md`](./bayes-dl-dcu/SKILL.md)。
- 生成 BDL 实验代码时，两个 skill 配合使用：本 skill 负责工程基础设施和记录包，
  `bayes-dl-dcu` 负责方法对比协议、校准评估和分布偏移实验设计。

## 可复用模板

以下模板文件可直接复制到用户项目中使用：

| 模板 | 路径 |
|------|------|
| CheckpointManager 类 | `assets/templates/checkpoint_manager.py` |
| EarlyStopper 类 | `assets/templates/early_stopper.py` |
| capture_environment() 函数 | `assets/templates/environment_capture.py` |
| generate_evaluation_report() / generate_experiment_metadata() | `assets/templates/evaluation_report.py` |
| experiment_recorder（大型实验记录包） | `assets/templates/experiment_recorder.py` |

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
```
