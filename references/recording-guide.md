# 大型实验记录指南

> **模板代码**: `assets/templates/experiment_recorder.py` — 通用实验记录工具，任何训练任务都可使用。

## 为什么需要完整记录

大型实验跑一次很久，缺少关键信息时无法重来。完整的实验记录包应能回答：
跑的是什么代码/什么配置/什么数据/什么环境、中间发生了什么、训练轨迹如何、
预测分布是否还在、每个阶段耗时和显存是多少。

## 标准 run 目录结构

```
runs/<experiment>/run_<YYYYMMDD_HHMMSS>/
├── run_manifest.json          # run_id、时间、git commit、config/args、数据集、环境、代码哈希
├── code/                      # 实际运行的代码快照
├── environment.json           # (如单独调用 capture_environment)
├── dataset_info.json          # (可选) 数据来源/哈希/切分
├── events.jsonl               # 事件时间线
├── errors.log                 # 错误日志
├── training/
│   └── <method>_metrics.csv   # 每方法逐 epoch 指标
├── checkpoints/
├── predictions/
│   ├── <method>_probs.npy     # 后验预测概率
│   ├── <method>_ytrue.npy
│   └── <method>_samples.npz   # (可选) 后验预测样本
├── results_partial.json       # 每完成一个方法立即增量落盘
├── evaluation_report.json
└── figures/
```

## 基本用法

```python
from experiment_recorder import (
    make_run_dir, log_event, log_epoch, update_results_json,
    save_probs, save_split_indices, model_summary, gpu_memory,
)

run_dir = make_run_dir(
    "runs", "my_experiment",
    config=CONFIG,
    args=vars(args) if args else None,
    code_paths=[__file__, "model.py", "data.py"],
    dataset_info={"n_train": len(train_set), "n_test": len(test_set)},
    notes="第一次正式训练",
)
log_event(run_dir, "data_loaded", n_train=len(train_set))

save_split_indices(run_dir, train_idx, val_idx, test_idx)

for epoch in range(num_epochs):
    ...
    log_epoch(run_dir, "MAP", epoch, loss=loss, val_acc=val_acc)

# 每完成一个方法/阶段立即落盘，防止长跑中断丢失
update_results_json(run_dir, "results_partial.json", "MAP", {"test_acc": acc})

# 预测概率必须保存，以后可复算任何指标、画任何图
save_probs(run_dir, "MAP", probs, y_true, num_classes)

# 最终报告
json.dump(report, open(os.path.join(run_dir, "evaluation_report.json"), "w"))
```

## 必须遵守的规则

1. **预测分布必须落盘**：`save_probs` / `save_samples_npz`，只存最终指标不够。
2. **增量结果**：每完成一个方法/一个阶段，立刻 `update_results_json`。
3. **代码快照**：`code_paths` 包含所有影响结果的脚本、模型定义、数据加载代码。
4. **数据集信息**：来源、文件名、sha256（如有）、形状、类别分布、切分索引。
5. **每方法训练轨迹**：`log_epoch` 按方法分文件写 `training/<method>_metrics.csv`。
6. **评估口径**：在报告中写清后验样本数、置信区间、ECE 分箱等 evaluation_config。
7. **环境与硬件**：`make_run_dir` 会自动调用 `environment_capture`，并在结果里记录
   `gpu_memory`；模型结构用 `model_summary` 记录。
