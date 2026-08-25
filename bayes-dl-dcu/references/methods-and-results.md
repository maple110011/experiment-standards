# BDL 方法对比协议与已测结果

## 公平对比协议

- 相同模型结构、相同数据切分、相同训练预算（epochs/batch/lr schedule）。
- 每个方法必须保存预测分布（均值/方差或概率），不能只存最终指标。
- 指标口径固定：
  - 分类: acc, NLL, Brier, ECE (top-label), sharpness (max_prob - 1/C)
  - 回归: RMSE, MAE, NLL (Gaussian), coverage95, sharpness95, ECE (50/80/90/95 区间)
- 每个方法记录 train_time_s 和 gpu_memory_gb。

## 已测结果速查（DCU, 2026-08-25）

### digits（1797×64, 10 类）
| 方法 | acc | NLL | ECE |
|---|---|---|---|
| MAP | .9694 | .1289 | .0816 |
| MC Dropout | .9694 | .1338 | .0863 |
| Deep Ensemble(5) | .9721 | .1304 | .0835 |
| SWAG-Diagonal | .9694 | .1175 | .0718 |
| LLLA | .9666 | .1953 | .1364 |
| SGHMC | .9276 | .4733 | .0986 |
| Pyro SVI AutoNormal | .9294 | .324 | .195 |
| Pyro SVI AutoLowRank | .9480 | .325 | .085 |

### YearPredictionMSD（463715×90 回归）
| 方法 | RMSE | coverage95 | ECE |
|---|---|---|---|
| MAP | 9.77 | .928 | .039 |
| MC Dropout | 32.76 | .999 | .182 |
| Deep Ensemble(4) | 9.39 | .635 | .306 |
| SWAG-Diagonal | 9.06 | .880 | .043 |
| LLLA | 失败（Cholesky） | — | — |
| SGHMC | NaN | — | — |

### UCI 小样本回归（RMSE/coverage95/ECE）
- uci_protein: MAP 4.45/.944/.014; MCD 4.51/.313/.560; Ensemble 4.38/.217/.632; SWAG 4.40/.223/.627; LLLA 4.47/.017/.776; SGHMC NaN
- uci_energy: MAP 4.48/.889/.095; MCD 4.31/.745/.193; Ensemble 4.04/.444/.464; SWAG 3.93/.065/.740; LLLA 4.17/.039/.758; SGHMC 4.37/1.000/.149
- uci_power: MAP 30.21/.959/.007; MCD 29.68/.938/.012; Ensemble 28.59/.202/.642; SWAG 31.93/.214/.630; LLLA 26.84/.002/.786; SGHMC NaN

### MoleculeNet（ECFP4 2048 维，二分类）
- BBBP: MAP .872/.128; MCD .887/.123; Ensemble .877/.131; SWAG .872/.127; LLLA .872/.167; SGHMC .867/.163
- HIV: MAP .957/.046; MCD .957/.049; Ensemble .965/.041; SWAG .964/.040; LLLA .967/.048; SGHMC .959/.489（质量差）

### 多变量时序一步预测（RMSE/coverage95/ECE）
- exchange_rate: MAP .792/.100/.711; MCD .897/.163/.679; Ensemble .749/.154/.694; SWAG .784/.033/.764; SGHMC NaN
- electricity: MAP .527/.798/.160; MCD .538/.478/.439; Ensemble .526/.350/.533; SWAG .531/.252/.608; SGHMC NaN

### CIFAR-10（图像基准）
- 小 CNN: MAP .814; MCD .834; Ensemble(3) .861; SWAG .744
- VGG16-BN (14.7M): MAP .9224; MCD .9113; Ensemble(2) .9335; SWAG .7809

### VBLL (Harrison et al. 2024, diagonal 实现)
- uci_protein: RMSE 4.383, coverage95 0.944, ECE 0.017, NLL 2.761 (40 epochs)
- YearPredictionMSD: RMSE 8.94, coverage95 0.942, ECE 0.018, NLL 3.43 (20 epochs, 148.6s)
- 对比: UCI protein 上点预测与 Ensemble 持平, 校准远好于 MCD/Ensemble/SWAG/LLLA;
  YearPredictionMSD 上优于 SWAG(小模型) 9.06。
- 实现要点: 目标 y 必须先标准化, 否则方差学习会欠拟合。

### 分布偏移 (CIFAR-10 损坏集, 小 CNN)
- MC Dropout 对 gaussian/blur/contrast 最稳健; Deep Ensemble 对 noise/pixelate 脆弱;
  所有方法 ECE 随 shift 上升。
- MoleculeNet scaffold split: VBLL_probit (acc .817/ECE .187) 略优于 MAP (.804/.199),
  显著低于随机 split (.872/.133)。

## 经验解读

1. **Deep Ensemble 几乎总是精度最稳**，但方差有时低估（UCI 上 coverage 低）。
2. **SWAG 在 YearPredictionMSD 上最好**，但 epochs 不足时明显欠训练。
3. **MC Dropout 在 BBBP 小样本上最好**；大样本回归 30 epochs 严重不足。
4. **LLLA 在 HIV 大样本分类上最好**；大样本回归 Cholesky 失败；CIFAR 全量太慢。
5. **SGHMC 当前实现在多数数据上发散**，需梯度裁剪/低 lr/burn-in 后再比。
6. **MAP + 训练残差方差**在 UCI 小样本回归上是可靠的校准基线。
