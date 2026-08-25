# 训练控制: Early Stopping + LR 调度

> **模板代码**: `assets/templates/early_stopper.py` — 可直接复制到项目中使用。

## 1. Early Stopping 集成

基于验证集指标（不是训练 loss）的早停。`mode="min"` 用于 loss/rmse，
`mode="max"` 用于 accuracy/ELBO/对数似然。

```python
from early_stopper import EarlyStopper

stopper = EarlyStopper(patience=15, min_delta=1e-4, mode="min")

for epoch in range(num_epochs):
    # ... 训练 ...
    if epoch % eval_interval == 0:
        val_metric = evaluate(...)
        if stopper(val_metric):
            print(f"🛑 Early stopping at epoch {epoch}")
            break
```

### 最大训练时间限制

```python
import time
MAX_TRAINING_SECONDS = 3600 * 4  # 4 小时
training_start = time.time()

for epoch in range(max_epochs):
    # ... 训练 ...
    if time.time() - training_start > MAX_TRAINING_SECONDS:
        print(f"⚠️ 达到最大训练时间, 停止")
        break
```

## 2. 学习率调度

### 手动阶梯衰减 (最可靠)

```python
def get_lr(epoch, base_lr=0.01, milestones={3000: 0.5, 8000: 0.1}):
    factor = 1.0
    for milestone, decay in sorted(milestones.items()):
        if epoch >= milestone:
            factor = decay
    return base_lr * factor
```

### Warmup

```python
def warmup_lr(epoch, base_lr=0.01, warmup_epochs=500):
    if epoch < warmup_epochs:
        return base_lr * (epoch + 1) / warmup_epochs
    return base_lr
```

### 余弦退火

```python
import math
def cosine_lr(epoch, base_lr=0.01, min_lr=1e-4, total_epochs=10000):
    progress = epoch / total_epochs
    return min_lr + (base_lr - min_lr) * (1 + math.cos(math.pi * progress)) / 2
```

### 平台检测自动降 lr

```python
def auto_reduce_lr(loss_history, window=500, factor=0.5, threshold=0.001):
    """如果最近 window 步改善不足 threshold, lr *= factor"""
    if len(loss_history) < 2 * window:
        return False
    prev = np.mean(loss_history[-2*window:-window])
    recent = np.mean(loss_history[-window:])
    improvement = (prev - recent) / max(abs(prev), 1e-8)
    return improvement < threshold
```

### batch size 缩放与学习率

加大 batch 能提升吞吐（见 [long-running-guide.md](./long-running-guide.md) §6），
但会改变收敛行为，需配合学习率缩放：

```python
def scale_lr(base_lr, base_batch, new_batch, rule="sqrt"):
    """batch 翻倍时 lr 线性(×N)或平方根(×√N)缩放。"""
    factor = (new_batch / base_batch) if rule == "linear" else (new_batch / base_batch) ** 0.5
    return base_lr * factor
```

- **线性缩放** (`lr × N`) 是 SGD 的经典做法；**平方根缩放** (`lr × √N`) 对
  Adam 更稳。回归/表格大模型用平方根缩放配合大 batch 实测又快又好。
- **先测吞吐再定 batch**：不同模型的吞吐曲线不同，`2 的幂不是魔法`，必须实测。
- **不要只看吞吐**：图像 CNN 大 batch 常精度略降 0.5-1 点，需要 lr 微调；
  小数据上大 batch 结论不稳定（batch 数变少）。

## 3. 训练循环完整集成示例

```python
from early_stopper import EarlyStopper

stopper = EarlyStopper(patience=15, mode="min")

for epoch in range(num_epochs):
    lr = warmup_lr(epoch) if epoch < 500 else get_lr(epoch)
    for param_group in optimizer.param_groups:
        param_group["lr"] = lr

    # 训练一步
    loss = train_step(...)

    # 评估 + 早停
    if epoch % eval_interval == 0:
        val_metric = evaluate(...)
        if stopper(val_metric):
            print(f"🛑 Early stopping at epoch {epoch}")
            break
```

> Pyro SVI 用户注意: `svi.step` 返回的 loss 通常是负 ELBO, 越小越好;
> 但若用 ELBO/对数似然作为监控指标, 则 `mode="max"`。
