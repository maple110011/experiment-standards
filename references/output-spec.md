# 输出物规范

## 1. 标准输出目录结构

```
outputs/
├── environment.json          # 运行环境
├── seed.json                 # 随机种子
├── training.log              # 完整训练日志 (DEBUG)
├── errors.log                # 错误日志 (仅ERROR, 空文件=无错误)
├── metrics.csv               # 逐epoch指标
├── experiment_metadata.json  # 元数据 (环境+config+数据集)
├── checkpoints/
│   ├── ckpt_epoch500.tar     # 中间checkpoint (命名与 CheckpointManager 一致)
│   ├── ckpt_epoch1000.tar
│   └── ckpt_best.tar         # 最佳模型
├── best_model.pt             # 最佳模型权重
├── final_model.pt            # 最终模型权重 (建议保留)
├── evaluation_report.json    # 结构化评估报告
└── figures/
    ├── loss_curve.png
    ├── prediction_vs_true.png
    └── residuals.png
```

## 2. 评估报告格式

> 模板函数已内置在 `assets/templates/evaluation_report.py`, 直接复制使用,
> 不要自己重写。

```python
from evaluation_report import generate_evaluation_report, generate_experiment_metadata

generate_evaluation_report(metrics, env, CONFIG, "outputs/evaluation_report.json")
generate_experiment_metadata(CONFIG, env, dataset_info, "outputs/experiment_metadata.json")
```

`generate_evaluation_report` 会写入 `experiment`, `timestamp`, `environment`,
`config`, `metrics`, `training` 六个字段。`metrics` 建议包含:

| 任务 | 指标 |
|------|------|
| 回归 | `test_rmse`, `test_mae`, `coverage_95pct`, `test_log_likelihood` |
| 分类 | `test_acc`, `test_nll`, `ece`, `brier` |
| 训练 | `total_epochs`, `final_loss`, `early_stopped`, `training_time_seconds`, `best_epoch` |

贝叶斯深度学习实验强烈建议额外报告不确定性校准指标: ECE (expected
calibration error)、sharpness (后验预测区间平均宽度)、coverage。

## 3. 模型导出

```python
# 最佳模型权重 (仅参数, 轻量)
torch.save({
    "model_state": model.state_dict(),
    "config": CONFIG,
    "best_epoch": best_epoch,
    "best_metric": best_metric,
}, "best_model.pt")

# 训练结束时的最终模型
torch.save({
    "model_state": model.state_dict(),
    "config": CONFIG,
}, "final_model.pt")
```

### Pyro 模型的导出

```python
# SVI: 保存 guide 参数
torch.save({"guide_state": pyro.get_param_store().get_state(),
            "config": CONFIG}, "best_model.pt")

# MCMC: 保存后验样本
torch.save({
    "samples": mcmc.get_samples(),
    "config": CONFIG,
}, "posterior.pt")

# 同时导出 ArviZ NetCDF (更好的互操作性)
import arviz as az
az.to_netcdf(az.from_pyro(mcmc), "posterior.nc")
```

## 4. 输出物检查清单

| 文件 | 必须 | 说明 |
|------|:---:|------|
| `environment.json` | ✅ | 硬件环境 (CPU/GPU/RAM/版本) |
| `seed.json` | ✅ | 随机种子 |
| `training.log` | ✅ | 完整日志 |
| `errors.log` | ✅ | 错误日志 (空文件=无错误) |
| `metrics.csv` | ✅ | 逐epoch指标 |
| `checkpoints/ckpt_best.tar` | ✅ | 最佳checkpoint |
| `best_model.pt` | ✅ | 最佳权重 |
| `final_model.pt` | | 最终权重 |
| `evaluation_report.json` | ✅ | 评估报告 |
| `figures/*.png` | ✅ | 图表 |
