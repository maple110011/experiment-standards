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
   指标计算用 `experiment-standards` 的 `assets/templates/metrics.py`。
4. **长实验要增量记录**：每完成一个方法立即写 `results_partial.json` 和预测文件。
5. **DCU 上先 warmup 再计时**：首次算子调用会触发内核编译。

## 工作流

1. 读 `references/methods-and-results.md` 确认公平对比协议。
2. 读 `references/dcu-adaptation.md` 确认设备访问、版本兼容、常见坑。
3. 用 `experiment-standards` 的 `experiment_recorder.py` 创建 run 目录，
   数据切分后立即 `save_split_indices`。
4. 实现所选 BDL 方法（MC Dropout / Deep Ensemble / SWAG / Laplace / SGHMC / SVI 等）。
   工程侧复用 `experiment-standards` 的模板：`checkpoint_manager.py`、`early_stopper.py`、
   `environment_capture.py`。
5. 每完成一个方法：`update_results_json` + 保存预测分布
   （分类 `save_probs`、回归 `save_regression_predictions`、采样类 `save_samples_npz`）；
   每个 eval_interval：`log_epoch` 记录 train/val 指标。
6. 评估报告写清 `evaluation_config`（后验样本数、ECE 分箱、Laplace 结构/link_approx、
   温度缩放前后指标）。有分布偏移/OOD 时写 `evaluation_shift.json`。
7. 最终写 `evaluation_report.json`，并把结果汇总进 `RESULTS_SUMMARY.md`。

## 方法速查

| 方法 | 说明 |
|------|------|
| MAP + 训练残差方差 | 点估计 + 残差方差，作为不确定度基线 |
| MC Dropout | dropout 采样近似后验；通常需要较长训练 |
| Deep Ensemble | 多模型集成，通常精度稳定 |
| SWAG-Diagonal | SGD 轨迹拟合对角高斯，需足够 epochs 收敛 |
| Last-Layer Laplace | 对最后一层权重做 Laplace；全量在大模型/大样本上计算成本高 |
| SGHMC | 随机梯度 MCMC，通常需梯度裁剪/低 lr/burn-in 稳定 |
| Pyro SVI AutoNormal | 对角高斯变分近似 |
| Pyro SVI AutoLowRank | 低秩协方差变分近似 |
| VBLL | 变分贝叶斯最后一层，单次前向（Harrison et al. 2024） |
| Pyro NUTS | Hamiltonian MCMC，通常较慢 |
| Temperature scaling | 后校准：单一温度参数缩放 logits/方差，缩放前后指标分别记录 |

## 数据选择

- AI4Science：MoleculeNet（如 BBBP/HIV）；FLIP 蛋白质工程
- 大样本回归：YearPredictionMSD
- UCI 小样本回归：protein / energy / power / wine / concrete
- 时序：electricity / exchange_rate / solar / traffic
- 图像基准：CIFAR-10

## 参考资源

| 资源 | 内容 |
|------|------|
| [methods-and-results.md](./references/methods-and-results.md) | 方法公平对比协议 |
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
