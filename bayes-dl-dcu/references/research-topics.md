# 可探索课题建议

## 理论方向

1. **不确定性校准**：为什么 MC Dropout/Deep Ensemble/SWAG 在 UCI 回归上方差被低估？
   如何在不损精度前提下做 variance calibration / temperature scaling / recalibration。
2. **后验近似比较理论**：SWAG vs Laplace vs SGMCMC 在不同数据规模/过参数化程度下何时更优。
3. **函数空间推断**：function-space BDL（function-space VI/priors）在 AI4Science 小样本上的表现。
4. **OOD 检测**：分子结构新颖性与 BDL 不确定度的相关性，能否用 uncertainty 指导分子筛选。
5. **贝叶斯模型选择**：Laplace / SWAG 的 marginal likelihood 作为模型选择指标。
6. **冷后验效应**：cold posterior effect 在分子/时序数据上是否存在。

## 应用方向

1. **AI4Science / 分子性质预测**：MoleculeNet 已跑 BBBP/HIV；后续加 BACE/Tox21/SIDER，
   做“不确定度指导的分子筛选”。
2. **蛋白质工程**：FLIP（GB1/AAV/Protein G）小样本+不确定度。
3. **时间序列预测区间**：electricity/traffic/solar/exchange_rate。
4. **推荐系统**：MovieLens 贝叶斯矩阵分解。

## 方法侧可继续

- Laplace 变体: diag/kron/last-layer with damping（修复 Cholesky 失败）。
- SGHMC 稳定化: 梯度裁剪 + 更低 lr + burn-in + 预热。
- SWAG 改进: SGD 收集 + 低秩协方差（当前只实现 diagonal）。
- Deep Ensemble + SWAG 混合、MC Dropout concrete dropout。
- Pyro guide 进阶: AutoMultivariateNormal / AutoNormalizingFlow / AutoIAFNormal。
- 函数空间: GP 先验 BNN、Deep Kernel Learning。
