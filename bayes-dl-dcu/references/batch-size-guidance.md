# batch size 与空间换时间

## 核心原则

1. **先测吞吐再定 batch**：不同模型/算子的显存-吞吐曲线不同，必须先做 1-epoch
   基准（见 [long-running-guide.md](../../references/long-running-guide.md) §1）
   或专门的吞吐扫描。
2. **空间换时间不总是免费**：大 batch 提高吞吐，但会改变收敛行为，通常需要
   lr 线性/平方根缩放；图像模型大 batch 常精度略降，需要 lr 微调。
3. **2 的幂不是魔法**：在部分算子/内存对齐上有微小优势，建议优先测 2 的幂，
   但最终以实测吞吐为准。
4. **BDL 方法的 batch 敏感性不同**：
   - MAP / Deep Ensemble / VBLL：对 batch 相对稳健，配合 lr 缩放即可。
   - MC Dropout / SGHMC：小 batch 的梯度噪声是方法本身的一部分，盲目加大 batch
     会改变噪声结构，需要重调 dropout / 噪声温度。
   - SWAG：大 batch 需要更多 epochs 收集快照，否则协方差估计差。

## 建议

- 显存允许时优先加大 batch 提升吞吐，并配合 lr 缩放（见
  [training-control.md](../../references/training-control.md) §2）。
- SGMCMC / MC Dropout 先固定小 batch 保持噪声，再通过多卡并行提高吞吐。
