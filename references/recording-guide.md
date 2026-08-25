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
├── split_indices.npz          # 数据切分索引 (save_split_indices)
├── events.jsonl               # 事件时间线
├── errors.log                 # 错误日志 (log_exception 写完整堆栈)
├── training/
│   └── <method>_metrics.csv   # 每方法逐 epoch 指标 (含 train/val)
├── tb/                        # TensorBoard events (log_epoch 自动写入)
├── checkpoints/
│   ├── <method>_best.pt       # 模型权重 (save_model_weights)
│   └── <method>_final.pt
├── predictions/
│   ├── <method>_probs.npy     # 分类后验预测概率
│   ├── <method>_mean.npy      # 回归预测均值 (save_regression_predictions)
│   ├── <method>_var.npy
│   ├── <method>_ytrue.npy
│   └── <method>_samples.npz   # 采样类方法原始样本
├── results_partial.json       # 每完成一个方法立即增量落盘
├── evaluation_shift.json      # (可选) 分布偏移/OOD 结果
├── calibration_temperature.json # (可选) 温度缩放等后校准结果
├── evaluation_report.json
└── figures/
    ├── reliability_<method>.png     # 分类校准曲线
    └── calibration_<method>.png     # 回归覆盖率校准曲线
```

## 基本用法

```python
from experiment_recorder import (
    make_run_dir, log_event, log_epoch, update_results_json,
    save_probs, save_regression_predictions, save_samples_npz, save_split_indices,
    update_shift_results_json, save_temperature_scaling, save_model_weights,
    plot_reliability_diagram, plot_regression_calibration,
    log_exception, model_summary, gpu_memory,
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

# 预测分布必须保存，以后可复算任何指标、画任何图
save_probs(run_dir, "MAP", probs, y_true, num_classes)                    # 分类概率
save_regression_predictions(run_dir, "MAP", mean, var, y_true)            # 回归均值/方差
# 采样类方法额外保存原始样本
save_samples_npz(run_dir, "MAP", samples, y_true)
# 分布偏移 / OOD 评估结果单独存放，不要和原始测试集指标混在一起
update_shift_results_json(run_dir, "gaussian_noise", "MAP", {"acc": ..., "ece": ...})
# 温度缩放等后校准结果单独记录
save_temperature_scaling(run_dir, "MAP", temperature=1.2,
                         before={"ece": 0.12}, after={"ece": 0.05})
# 自动生成校准曲线
plot_reliability_diagram(run_dir, "MAP", probs, y_true, num_classes)      # 分类
plot_regression_calibration(run_dir, "MAP", mean, var, y_true)            # 回归
# 异常时写 errors.log
try:
    ...
except Exception:
    log_exception(run_dir)
    raise
# 保存模型权重（best/final 各存一份；重训比磁盘贵得多）
save_model_weights(run_dir, "MAP", model, is_best=True)
save_model_weights(run_dir, "MAP", model, is_best=False)
# 最终报告
json.dump(report, open(os.path.join(run_dir, "evaluation_report.json"), "w"))
```

## 必须遵守的规则

1. **预测分布必须落盘**：分类用 `save_probs`、回归用 `save_regression_predictions`、
   采样类方法用 `save_samples_npz`，只存最终指标不够。
   这正是"store first, improve later"：只要概率/样本在磁盘上，事后换指标、换图、
   做温度缩放/后校准、补分布偏移评估都**不需要重训**——这是最便宜也最常被
   忽略的一步。
2. **增量结果**：每完成一个方法/一个阶段，立刻 `update_results_json`。
3. **代码快照**：`code_paths` 包含所有影响结果的脚本、模型定义、数据加载代码。
4. **数据集信息**：来源、文件名、sha256（下载的数据可能损坏/上传不完整，必须记）、
   形状、类别分布；**自定义切分必须落盘** —— 切分后立即
   `save_split_indices(run_dir, train_idx, val_idx, test_idx)`，否则以后无法精确重建同一切分。
5. **每方法训练轨迹**：`log_epoch` 按方法分文件写 `training/<method>_metrics.csv`。
   **每个 eval_interval 都要记录验证集指标**（`val_loss`/`val_acc`/`val_rmse`），
   不要只记训练 loss——长实验中验证轨迹是判断过拟合/早停的唯一依据。
6. **评估口径**：在报告中写清后验样本数、置信区间、ECE 分箱、Laplace
   link_approx/结构等 evaluation_config，指标口径不一致就没法跨方法/跨实验比较。
7. **环境与硬件**：`make_run_dir` 会自动调用 `environment_capture`，并在结果里记录
   `gpu_memory`；模型结构用 `model_summary` 记录。
8. **TensorBoard**：`log_epoch` 自动把标量写入 `run_dir/tb/`，无需额外代码。
9. **异常留痕**：所有 `except` 块调用 `log_exception(run_dir)`，把完整堆栈写入
   `errors.log`，不要只 print。
10. **模型权重**：默认用 `save_model_weights` 保存 best/final 权重到 `checkpoints/`；
    磁盘成本远低于重训成本。
11. **checkpoint 完整性**：checkpoint 记录 `format_version` 和 sha256，防止静默损坏；
    用 try-except 包裹 `torch.load`，损坏时回退到上一个可用 checkpoint。

## 可选扩展（需要更全面复盘时）

- **分布偏移/OOD 评估**：在原始测试集之外，另存 `evaluation_shift.json`，记录每个
  shifted 测试集（噪声/模糊/亮度/scaffold split 等）的 acc/ECE/NLL/Brier。
  预测分布已落盘时，这些事后也能补算。
- **后校准结果**：做完 temperature scaling / variance calibration 后，用
  `save_temperature_scaling` 把温度值、缩放前后 ECE/NLL 写入
  `calibration_temperature.json`，避免和原始指标混淆。
- **回归校准曲线**：`plot_regression_calibration()`（名义覆盖率 vs 经验覆盖率）
  与分类的 `plot_reliability_diagram()` 配合，覆盖两类任务的校准图。
