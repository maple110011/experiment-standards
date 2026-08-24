---
name: experiment-standards
description: 'Always use this skill when the user asks to standardize ML experiment outputs, needs reproducible training infrastructure, or mentions checkpoint management, experiment logging, environment recording, evaluation reports, early stopping, LR scheduling, training resilience (NaN recovery), or output directory structures — even if they don\'t explicitly say "experiment standards". Also trigger when the user complains about 训练中断无法恢复、实验结果无法复现、不同设备跑出来结果不一样、缺少实验记录、不知道怎么加日志/早停/学习率调度/NaN检测、想做 grid search 但输出一团乱、需要规范输出目录结构等任何训练工程化需求。Covers: checkpoint save/resume, hardware environment capture (CPU/GPU/RAM), seed recording, training/error log separation, CSV metrics tracking, structured evaluation reports (JSON), model weight export (best/final), output directory specification, early stopping, learning rate scheduling (warmup/decay/cosine), NaN/Inf detection and auto-recovery, DataLoader best practices, memory profiling, experiment runner (grid search). Framework-agnostic but includes Pyro/PyTorch examples. Do NOT use for: model architecture design, inference method selection, prior selection, uncertainty calibration — those belong to domain-specific skills.'
argument-hint: '[任务: checkpoint管理 / 实验日志 / 环境记录 / 早停 / 评估报告 / 输出物规范]'
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

**必须记录**: CPU型号/核数、GPU型号/VRAM、总RAM、PyTorch版本、CUDA版本、磁盘可用空间、运行时环境（Colab/Local）。

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
if np.isnan(loss):  # 自动回退checkpoint + 降lr，见 resilience-guide.md §1
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

## 何时读取参考资源

根据用户的具体需求，选择性读取以下参考文档：

| 用户需求 | 应读取的文档 | 关键章节 |
|----------|-------------|---------|
| 加 checkpoint 保存/恢复 | [checkpoint-guide.md](./references/checkpoint-guide.md) | §1-2; Pyro 用户加读 §3 |
| 加早停 / 调学习率 | [training-control.md](./references/training-control.md) | §1 (早停), §2 (LR调度) |
| 记录环境信息 / 配日志 | [logging-guide.md](./references/logging-guide.md) | §1 (环境), §2 (日志), §3 (CSV), §4 (元数据) |
| 规范输出目录 / 评估报告 / 模型导出 | [output-spec.md](./references/output-spec.md) | §1 (目录), §2 (报告), §3 (导出); Pyro/MCMC 用户加读 §3 后半 |
| 训练崩溃恢复 / NaN处理 / 内存管理 | [resilience-guide.md](./references/resilience-guide.md) | §1 (NaN), §2 (梯度), §3 (回退), §4 (DataLoader), §5 (内存) |


## 国产加速卡 (海光 DCU / ROCm / HIP) 注意事项

- `torch.cuda.is_available()` 在 DCU 上为 `True`, 但 `torch.version.cuda` 为 `None`;
  必须用 `torch.version.hip` 记录 ROCm/HIP 版本, 用 `get_device_properties().gcnArchName`
  记录架构 (如 `gfx936`)。`capture_environment()` 模板已处理。
- 训练脚本中张量/模型的 `.to(device)` 与普通 CUDA 写法一致 (`device="cuda"`)。
- 首次调用新算子会触发内核编译 (可能数百 ms), 基准测试必须先 warmup。
- Pyro `AutoNormal` 在 DCU 上可能出现 guide 参数留在 CPU 导致设备不匹配;
  优先在 `model` 内显式把先验参数创建在 `x.device` 上, 必要时用
  `pyro.get_param_store().set_state()` 后调用 `.to(device)` 处理。
- 遇到 `HIP out of memory` 时按 OOM 恢复流程处理 (见 resilience-guide §3)。
- Pyro 断点续训 / NaN 恢复时, `set_state()` 会把 checkpoint 中的参数按加载时的设备放回
  param store (通常 `torch.load(map_location="cpu")` 后是 CPU), 必须把 param store 参数
  逐个 `.to(device)` 移回训练设备, 否则会报 `Expected all tensors to be on the same device`。

## 贝叶斯深度学习补充

- 评估报告除 `coverage_95pct` 外, 建议报告 `test_log_likelihood`、ECE、sharpness
  (后验预测区间平均宽度), 模板 `evaluation_report.py` 的 metrics 字段支持任意键。
- 最佳模型判断: SVI 的 `svi.step` 返回负 ELBO, 越小越好; 但 accuracy / ELBO /
  对数似然是越大越好, `CheckpointManager` 和 `EarlyStopper` 都要设置 `mode="max"`。
- Pyro SVI 保存/恢复: 保存 `pyro.get_param_store().get_state()` 到 checkpoint 的
  `model_state`; 恢复用 `pyro.get_param_store().set_state(...)`。
- MCMC/NUTS 建议额外导出 ArviZ NetCDF (`az.to_netcdf(az.from_pyro(mcmc), ...)`),
  便于后验分析和跨工具比较。

## 可复用模板

以下模板文件可直接复制到用户项目中使用：

| 模板 | 路径 |
|------|------|
| CheckpointManager 类 | `assets/templates/checkpoint_manager.py` |
| EarlyStopper 类 | `assets/templates/early_stopper.py` |
| capture_environment() 函数 | `assets/templates/environment_capture.py` |
| generate_evaluation_report() / generate_experiment_metadata() | `assets/templates/evaluation_report.py` |

## 参考资源

| 资源 | 内容 |
|------|------|
| [checkpoint-guide.md](./references/checkpoint-guide.md) | Checkpoint 管理 (保存/恢复/最佳/清理) |
| [training-control.md](./references/training-control.md) | Early Stopping + LR 调度 |
| [logging-guide.md](./references/logging-guide.md) | 环境记录 + 日志系统 + CSV + 元数据 |
| [output-spec.md](./references/output-spec.md) | 输出目录规范 + 评估报告格式 + 模型导出 |
| [resilience-guide.md](./references/resilience-guide.md) | NaN/Inf 检测、梯度异常、DataLoader、内存管理 |

## 示例用法

```
# 为训练脚本添加 checkpoint 和早停
/experiment-standards 给我的训练脚本加上 checkpoint 和 early stopping

# 标准化实验输出
/experiment-standards 让这个脚本输出规范的实验记录（环境信息+日志+评估报告）

# 添加完整基础设施
/experiment-standards 为这个训练代码添加完整的实验基础设施
```
