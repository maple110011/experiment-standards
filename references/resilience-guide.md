# 训练韧性: 异常检测与恢复

## 1. NaN/Inf 实时监控

```python
import numpy as np

# 在每个 epoch 后检查 loss
if not np.isfinite(float(loss)):
    logger.error(f"Epoch {epoch}: loss={loss} (NaN/Inf), 尝试恢复...")
    resume = ckpt_mgr.load()
    if resume:
        # PyTorch: model.load_state_dict(resume["model_state"])
        # Pyro:   pyro.get_param_store().set_state(resume["model_state"])
        restore_rng_state(resume["rng_state"])
        base_lr *= 0.5
        logger.info(f"已从 checkpoint epoch {resume['epoch']} 恢复, lr 降至 {base_lr}")
        continue
    else:
        logger.error("无可恢复 checkpoint, 终止训练")
        break
```

> ⚠️ 对 torch 标量直接用 `np.isnan(loss)` 可能告警或报错, 用
> `not np.isfinite(float(loss))` 最稳妥。
>
> Pyro 用户恢复后还要把 param store 参数移回训练设备, 见
> checkpoint-guide.md §2。

## 2. 梯度异常处理

```python
# 梯度裁剪 (推荐, 比手动 continue 更稳)
torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)

# 监控梯度范数
total_norm = 0.0
for p in model.parameters():
    if p.grad is not None:
        total_norm += p.grad.data.norm(2).item() ** 2
total_norm = total_norm ** 0.5

if total_norm > 1000:  # 梯度爆炸
    logger.warning(f"梯度爆炸 (norm={total_norm:.0f}), 跳过此步")
    continue
```

## 3. 自动回退机制

```
训练步骤出错?
├── NaN/Inf in loss → 从上个 checkpoint 恢复, lr × 0.5
├── 梯度爆炸      → 跳过当前 step, 降低 lr
├── OOM (显存)     → 降低 batch_size, 从 checkpoint 恢复
├── 断电/崩溃      → 重启后自动加载最新 checkpoint
└── 连续异常      → 终止训练, 发送告警
```

### OOM 恢复示例

```python
try:
    loss = train_step(batch)
except RuntimeError as e:
    if "out of memory" in str(e).lower() or "HIP out of memory" in str(e):
        logger.error("OOM: 降低 batch_size 并恢复 checkpoint")
        torch.cuda.empty_cache()
        batch_size = max(1, batch_size // 2)
        resume = ckpt_mgr.load()
        if resume:
            model.load_state_dict(resume["model_state"])
            restore_rng_state(resume["rng_state"])
        continue
    raise
```

## 4. DataLoader 最佳实践

```python
from torch.utils.data import DataLoader

dataloader = DataLoader(
    dataset,
    batch_size=128,
    shuffle=True,       # 必须 shuffle
    num_workers=2,      # 多进程加载, 0=主进程
    pin_memory=True,     # GPU/DCU 训练时开启
    drop_last=True,     # 避免最后一批大小不一致
)
```

## 5. 内存泄漏检测

```python
import gc

if epoch % 1000 == 0:
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3
        reserved = torch.cuda.memory_reserved() / 1024**3
        print(f"[epoch {epoch}] GPU: {allocated:.2f}GB allocated, "
              f"{reserved:.2f}GB reserved")
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
```
