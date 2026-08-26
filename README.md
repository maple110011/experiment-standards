# experiment-standards

一个给 AI 编程助手（Agent）用的 Skill 仓库，把普通 ML 训练脚本升级成「能断点续训、可复现、可跨设备比较、有标准化评估」的实验。里面有两个 Skill：

| Skill | 位置 | 做什么 |
|---|---|---|
| **experiment-standards** | 根目录 | 实验工程基础设施：checkpoint、日志、环境记录、早停、LR 调度、异常恢复、评估报告、长实验记录包 |
| **bayes-dl-dcu** | [`bayes-dl-dcu/`](./bayes-dl-dcu/) | 贝叶斯深度学习的方法公平对比协议、不确定度校准、分布偏移/OOD、海光 DCU 适配、大模型训练经验 |

两者配合使用：BDL 实验脚本按根 Skill 规范产出标准记录，方法比较与校准按 `bayes-dl-dcu` 执行。

## 何时用 / 不用

**用（满足任一即可）**

- 训练脚本需要 checkpoint/断点续训、日志、环境记录、早停、异常恢复、评估报告
- 要跑长实验（几十分钟以上）或大模型，担心中途挂掉/超时，需要监控显存和算力
- 要多方法对比或写论文，需要标准化记录包、预测分布落盘、校准曲线/TensorBoard
- 要比较贝叶斯深度学习方法、做不确定度校准、在 DCU/HIP 上跑 PyTorch/Pyro（用 `bayes-dl-dcu`）

**不用**

- 纯一次性快速原型、不需要记录和复现的小实验
- 纯模型架构设计 / 推理方法选择（不属于本仓库两个 Skill 的范围）

## 做什么

指导 AI 编程助手为训练脚本添加：

- **Checkpoint 管理** — 定期保存 / 断点续训 / 损坏自动回退 / sha256 sidecar / `mode="min"/"max"`
- **环境记录** — CPU/GPU/RAM/磁盘 + 完整依赖版本 + `hy-smi` 驱动版本，支持 CUDA / ROCm(HIP, 海光 DCU) / MPS
- **日志系统** — 训练日志与错误日志分离，CSV 指标，TensorBoard 曲线
- **训练控制** — Early Stopping + LR 调度（warmup / 阶梯 / cosine）+ batch↔lr 缩放
- **异常恢复** — NaN/Inf 检测、梯度裁剪、OOM 回退、Pyro 设备恢复
- **评估报告** — JSON 结构化输出，校准曲线（分类 reliability / 回归 coverage）
- **标准化输出目录** — 统一文件结构
- **大型实验记录包** — `experiment_recorder.py`：run manifest、代码快照、数据哈希、事件时间线、逐 epoch 指标、预测概率/均值方差/样本、切分索引、增量结果、分布偏移与温度缩放记录、TensorBoard、模型权重
- **长任务 / 大模型训练** — 1-epoch 基准先行、后台启动与超时余量、受限 shell 通过 Jupyter kernel 跑 GPU、显存/算力分开监控、数据缓存、batch 缩放、卡型选型

## 适用框架

框架无关，内置 PyTorch 和 Pyro 示例。

## 文件结构

```
experiment-standards/
├── SKILL.md                          # Skill 1: 实验工程标准化（根目录）
├── README.md
├── assets/templates/                 # 可复用代码模板
│   ├── checkpoint_manager.py         # Checkpoint + 完整 RNG 状态
│   ├── early_stopper.py              # Early Stopping (min/max)
│   ├── environment_capture.py        # CUDA/HIP/MPS 环境采集
│   ├── evaluation_report.py          # 评估报告 / 实验元数据
│   └── experiment_recorder.py        # 大型实验记录包（含 TensorBoard）
├── scripts/
│   └── jupyter_exec.py               # 受限 shell 通过 Jupyter kernel 跑 GPU 的助手
├── references/                       # Skill 1 参考文档
│   ├── checkpoint-guide.md
│   ├── training-control.md
│   ├── logging-guide.md
│   ├── output-spec.md
│   ├── resilience-guide.md
│   ├── recording-guide.md            # 大型实验记录标准
│   └── long-running-guide.md         # 长任务/大模型训练工程
├── evals/
│   ├── evals.json                    # 测试 prompt（8 条）
│   └── run_evals.py                  # 自动单元测试 / 输出校验 / DCU 环境校验
└── bayes-dl-dcu/                     # Skill 2: 贝叶斯深度学习 / DCU 领域经验
    ├── SKILL.md
    ├── references/
    │   ├── methods-and-results.md    # 方法公平对比协议
    │   ├── dcu-adaptation.md
    │   ├── batch-size-guidance.md
    │   ├── large-model-experience.md
    │   └── research-topics.md
    └── evals/
        └── evals.json
```

## 快速使用

```bash
# 运行模板单元测试
python evals/run_evals.py

# 校验标准化输出目录
python evals/run_evals.py --check-outputs outputs

# 校验 DCU/HIP 环境记录
python evals/run_evals.py --check-dcu-env outputs/environment.json
```

## 大型实验记录包（长实验必读）

长实验使用 `assets/templates/experiment_recorder.py`：

```python
from experiment_recorder import make_run_dir, log_event, log_epoch, \
    update_results_json, save_probs, save_regression_predictions, \
    save_split_indices, save_model_weights

run_dir = make_run_dir("runs", "my_experiment", config=CONFIG,
                       code_paths=[__file__], dataset_info={...})
log_event(run_dir, "data_loaded", n=len(train_set))
save_split_indices(run_dir, train_idx, val_idx, test_idx)
for epoch in range(num_epochs):
    ...
    log_epoch(run_dir, "MAP", epoch, loss=loss, val_acc=val_acc)
update_results_json(run_dir, "results_partial.json", "MAP", {"acc": acc})
save_probs(run_dir, "MAP", probs, y_true, num_classes)             # 分类
save_regression_predictions(run_dir, "MAP", mean, var, y_true)     # 回归
save_model_weights(run_dir, "MAP", model, is_best=True)
```

每个 run 目录包含：`run_manifest.json`、`code/`、`training/*.csv`、`predictions/`、
`results_partial.json`、`evaluation_report.json`、`tb/`（TensorBoard）、`figures/`。
