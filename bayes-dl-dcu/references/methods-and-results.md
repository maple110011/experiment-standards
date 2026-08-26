# BDL 方法对比协议

本文件定义贝叶斯深度学习（BDL）方法公平对比的操作规范。所有方法必须遵循同一协议，确保结果可复现、可公平比较。

## 公平对比协议

- 相同模型结构、相同数据切分、相同训练预算（epochs/batch/lr schedule）。
- 每个方法必须保存预测分布（均值/方差或概率），不能只存最终指标。
- 指标口径固定：
  - 分类: acc, NLL, Brier, ECE (top-label), sharpness (max_prob - 1/C)
  - 回归: RMSE, MAE, NLL (Gaussian), coverage95, sharpness95, ECE (50/80/90/95 区间)
- 每个方法记录 train_time_s 和 gpu_memory_gb。
- 数据切分索引必须落盘（`save_split_indices`），保证以后能精确重建同一切分。
- 评估口径必须写进 `evaluation_config`：后验样本数、置信区间、ECE 分箱方式、
  Laplace 的 link_approx/结构/prior 优化、温度缩放前后指标等。
- 有分布偏移/OOD 评估时，结果写入 `evaluation_shift.json`，不要和原始测试集指标混在一起。
