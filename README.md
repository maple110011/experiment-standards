# experiment-standards

为机器学习训练脚本添加标准化实验基础设施的 Agent Skill。工程侧：checkpoint、日志、环境记录、早停、LR 调度、异常恢复、评估报告、标准输出目录，以及面向长实验的完整记录包（代码快照 / 数据哈希 / 训练曲线 / 预测样本 / TensorBoard / 增量结果）。

## 做什么

指导 AI 编程助手为训练脚本添加：

- **Checkpoint 管理** — 定期保存 / 断点续训 / 自动清理 / `mode="min"/"max"`
- **环境记录** — CPU/GPU/RAM/磁盘，支持 CUDA / ROCm(HIP, 海光 DCU) / MPS
- **日志系统** — 训练日志与错误日志分离，CSV 指标，TensorBoard 曲线
- **训练控制** — Early Stopping + LR 调度（warmup / 阶梯 / cosine）
- **异常恢复** — NaN/Inf 检测、梯度裁剪、OOM 回退、Pyro 设备恢复
- **评估报告** — JSON 结构化输出，校准曲线（分类 reliability / 回归 coverage）
- **标准化输出目录** — 统一文件结构
- **大型实验记录包** — `experiment_recorder.py`：run manifest、代码快照、事件时间线、逐 epoch 指标、预测概率/样本、增量结果

## 适用框架

框架无关，内置 PyTorch 和 Pyro 示例。贝叶斯深度学习方法选择、校准指标、DCU 适配经验等**领域内容**在配套 skill `bayes-dl-dcu` 中。

## 文件结构

```
experiment-standards/
├── SKILL.md                          # Skill 主文件（工作流 + 触发说明）
├── README.md
├── assets/templates/                 # 可复用代码模板
│   ├── checkpoint_manager.py         # Checkpoint + 完整 RNG 状态
│   ├── early_stopper.py              # Early Stopping (min/max)
│   ├── environment_capture.py        # CUDA/HIP/MPS 环境采集
│   ├── evaluation_report.py          # 评估报告 / 实验元数据
│   └── experiment_recorder.py        # 大型实验记录包（含 TensorBoard）
├── references/                       # 详细参考文档
│   ├── checkpoint-guide.md
│   ├── training-control.md
│   ├── logging-guide.md
│   ├── output-spec.md
│   ├── resilience-guide.md
│   └── recording-guide.md            # 大型实验记录标准
└── evals/
    ├── evals.json                    # 测试 prompt（5 条）
    └── run_evals.py                  # 自动单元测试 / 输出校验 / DCU 环境校验
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
    update_results_json, save_probs

run_dir = make_run_dir("runs", "my_experiment", config=CONFIG,
                       code_paths=[__file__], dataset_info={...})
log_event(run_dir, "data_loaded", n=len(train_set))
for epoch in range(num_epochs):
    ...
    log_epoch(run_dir, "MAP", epoch, loss=loss, val_acc=val_acc)
update_results_json(run_dir, "results_partial.json", "MAP", {"acc": acc})
save_probs(run_dir, "MAP", probs, y_true, num_classes)
```

每个 run 目录包含：`run_manifest.json`、`code/`、`training/*.csv`、`predictions/`、
`results_partial.json`、`evaluation_report.json`、`tb/`（TensorBoard）、`figures/`。

## 与 bayes-dl-dcu 的关系

- `experiment-standards`：实验工程基础设施（本仓库）。
- `bayes-dl-dcu`：贝叶斯深度学习方法比较、不确定性校准、分布偏移/OOD、DCU 适配、大模型经验。

两者配合使用：BDL 实验脚本按本 skill 规范产出记录，方法选择与校准指标按 `bayes-dl-dcu` 执行。
