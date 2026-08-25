---
name: bayes-dl-dcu
description: 'Always use this skill when the user wants to run or compare Bayesian deep learning methods (MC Dropout, Deep Ensemble, SWAG, Laplace, SGHMC, Pyro SVI, HMC/NUTS), needs uncertainty quantification or calibration metrics (ECE, sharpness, coverage, NLL), works on scientific/sequential/tabular data like molecules, proteins, time series, UCI regression, or wants DCU/HIP/ROCm adaptation experience and large-model training experience. Also trigger when the user mentions 贝叶斯神经网络, 不确定性估计, 校准, temperature scaling/后校准, 分布偏移/OOD, 国产加速卡/DCU/HIP, 分子性质预测, 蛋白质工程, 时序预测, or wants to compare methods under a fair protocol with reusable record packs. Do NOT use for: pure deterministic training without uncertainty, basic checkpoint/logging engineering — that belongs to the experiment-standards skill.'
argument-hint: '[任务: BDL方法选择 / 方法对比 / 不确定性校准 / DCU适配 / 大模型经验]'
---

# 贝叶斯深度学习实验与 DCU 适配

为 BDL 实验提供方法选择、公平对比流程、不确定性校准指标、DCU 适配经验和大模型训练经验。所有长实验默认配合 `experiment-standards` 的 `experiment_recorder.py` 生成标准记录包。

## 何时使用

- 用户要比较多种 BDL 方法（MC Dropout / Deep Ensemble / SWAG / Laplace / SGHMC / SVI）
- 用户关心预测不确定性、校准（ECE/sharpness/coverage/NLL），或要做 OOD/分布外评估
- 实验数据是分子、蛋白质、时序、UCI 表格等非图像科学数据
- 在海光 DCU / ROCm/HIP 上跑 PyTorch/Pyro 遇到设备、版本、性能问题
- 要跑大参数模型，关心显存、吞吐、长任务监控

## 核心原则

1. **公平比较**：所有方法使用相同模型结构、数据切分、训练预算和评估口径。
2. **预测分布必须落盘**：保存每个方法的预测均值/方差/样本（`experiment_recorder`）。
3. **校准指标统一**：分类用 acc/NLL/Brier/ECE/sharpness；回归用 RMSE/MAE/NLL/coverage95/sharpness95/ECE。
4. **长实验要增量记录**：每完成一个方法立即写 `results_partial.json` 和预测文件。
5. **DCU 上先 warmup 再计时**：首次算子调用会触发内核编译。

## 工作流

1. 读 `references/methods-and-results.md` 选择方法组合和基准配置。
2. 读 `references/dcu-adaptation.md` 确认设备访问、版本兼容、常见坑。
3. 用 `experiment-standards` 的 `experiment_recorder.py` 创建 run 目录，
   数据切分后立即 `save_split_indices`。
4. 从 `bayes-dcu/` 下复制对应脚本模板：
   - 表格回归 `bdl_tabular.py`
   - 分子分类 `bdl_moleculenet.py`
   - 时序一步预测 `bdl_timeseries.py`
   - 图像基准 `bdl_cnn_cifar.py` / `bdl_vgg16bn_cifar.py`
5. 每完成一个方法：`update_results_json` + 保存预测分布
   （分类 `save_probs`、回归 `save_regression_predictions`、采样类 `save_samples_npz`）；
   每个 eval_interval：`log_epoch` 记录 train/val 指标。
6. 评估报告写清 `evaluation_config`（后验样本数、ECE 分箱、Laplace 结构/link_approx、
   温度缩放前后指标）。有分布偏移/OOD 时写 `evaluation_shift.json`。
7. 最终写 `evaluation_report.json`，并把结果汇总进 `RESULTS_SUMMARY.md`。

## 方法速查

| 方法 | 适用 | 经验要点 |
|------|------|----------|
| MAP + 训练残差方差 | 基线 | 小样本回归上常常是可靠校准基线 |
| MC Dropout | 小样本分类 | 需要较长训练；大样本 30 epochs 不够 |
| Deep Ensemble | 通用 | 精度最稳；方差偶尔低估 |
| SWAG-Diagonal | 大样本回归 | YearPredictionMSD 最佳；需要足够 epochs |
| Last-Layer Laplace | 小样本分类/大样本分类 | HIV 上最好；全量 last-layer 在大样本回归会 Cholesky 失败，在 CIFAR 上过慢 |
| SGHMC | 探索 | 当前实现易发散，需要梯度裁剪/低 lr/burn-in |
| Pyro SVI AutoNormal | 小模型 | 可跑；校准一般 |
| Pyro SVI AutoLowRank | 小模型 | digits 上显著优于 AutoNormal |
| VBLL (变分贝叶斯最后一层) | 回归/分类 | UCI protein 上 RMSE 4.38/coverage .944/ECE .017, 一次前向; 见 Harrison 2024 |
| Pyro NUTS | 小模型 | DCU 上能跑但很慢，暂不实用 |
| Temperature scaling | 后校准 | 分类/回归都能做；缩放前后 ECE/NLL 记录到 `calibration_temperature.json` |

## 数据选择

- AI4Science：MoleculeNet（BBBP/HIV 已测）；FLIP 蛋白质工程（待上传）
- 大样本回归：YearPredictionMSD（515k×90，已测）
- UCI 小样本回归：protein / energy / power / wine / concrete（已测前三）
- 时序：electricity / exchange_rate / solar / traffic（已测前二）
- 图像基准：CIFAR-10（小 CNN 与 VGG16-BN 已测）

## 参考资源

| 资源 | 内容 |
|------|------|
| [methods-and-results.md](./references/methods-and-results.md) | 方法对比协议、已测结果与解读 |
| [dcu-adaptation.md](./references/dcu-adaptation.md) | 海光 DCU 适配经验 |
| [large-model-experience.md](./references/large-model-experience.md) | 大参数模型训练经验 |
| [batch-size-guidance.md](./references/batch-size-guidance.md) | batch size 选择与空间换时间 |
| [research-topics.md](./references/research-topics.md) | 理论/应用课题建议 |

## 示例用法

```
# 比较多种 BDL 方法
/bayes-dl-dcu 在 YearPredictionMSD 上比较 Deep Ensemble、SWAG、MC Dropout

# 做分子性质预测的不确定度校准
/bayes-dl-dcu 用 MoleculeNet HIV 数据做 BDL 分类，报告 ECE 和 NLL

# DCU 上跑大模型
/bayes-dl-dcu 在 CIFAR-10 上训练 VGG16-BN，记录显存和吞吐
```
