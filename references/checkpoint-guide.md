# Checkpoint 管理指南

训练中断后能否恢复，决定了长时间实验的成败。

> **模板代码**: `assets/templates/checkpoint_manager.py` — 可直接复制到项目中使用。

## 1. 在训练循环中集成

```python
from checkpoint_manager import CheckpointManager, capture_rng_state, restore_rng_state

# mode="min" 用于 val_loss/rmse 等越小越好; accuracy/ELBO 等用 mode="max"
ckpt_mgr = CheckpointManager("checkpoints", keep_recent_n=3, mode="min")

# 尝试断点续训
resume = ckpt_mgr.load()
start_epoch = resume["epoch"] + 1 if resume else 0
if resume:
    model.load_state_dict(resume["model_state"])
    optimizer.load_state_dict(resume["optimizer_state"])
    restore_rng_state(resume["rng_state"])
    print(f"✅ 从 epoch {resume['epoch']} 恢复训练")

for epoch in range(start_epoch, num_epochs):
    # ... 训练一步 ...

    # 定期保存
    if epoch % 500 == 0:
        ckpt_mgr.save(epoch, CONFIG,
                      model.state_dict(), optimizer.state_dict(),
                      capture_rng_state())

    # 验证并更新最佳
    if epoch % 1000 == 0:
        if ckpt_mgr.update_best(epoch, val_metric):
            ckpt_mgr.save(epoch, CONFIG,
                          model.state_dict(), optimizer.state_dict(),
                          capture_rng_state(),
                          is_best=True)

# 最终保存
ckpt_mgr.save(final_epoch, CONFIG,
              model.state_dict(), optimizer.state_dict(),
              capture_rng_state())
```

> ⚠️ RNG 状态必须包含 torch(CPU) + CUDA/HIP + numpy + python random 四者。数据切分、
> 数据增强、噪声注入依赖 numpy/python random; GPU 上的初始化/采样依赖 CUDA/HIP RNG。
> `capture_rng_state()` / `restore_rng_state()` 已自动处理这四者。

## 2. Pyro 特殊处理

Pyro 的参数存储在 `pyro.get_param_store()` 中。Pyro 1.9.x 恢复参数用
`set_state()`（旧文档中的 `load_state()` 不存在，照抄会直接 AttributeError）：

```python
# 保存
"model_state": pyro.get_param_store().get_state()
# 恢复
pyro.get_param_store().set_state(ckpt["model_state"])
# 重要: 在 CUDA/DCU 上, checkpoint 通常 load 到 CPU, 必须把参数移回训练设备
for name in list(pyro.get_param_store().get_all_param_names()):
    param = pyro.get_param_store().get_param(name)
    pyro.get_param_store().replace_param(name, param.detach().to(device), param)
```

Pyro 的 optimizer state 恢复较复杂，实践中通常重新创建 optimizer（或保存
`optimizer.optim_objs` 的状态并在恢复后重建）。RNG 状态仍用
`capture_rng_state()` / `restore_rng_state()`。

## 3. Checkpoint 最佳实践

| 实践 | 说明 |
|------|------|
| **定期保存** | 每 500-1000 epoch（或每 N 分钟） |
| **保存完整状态** | 参数 + optimizer + RNG + config |
| **保留最佳** | 基于验证集指标, 不是训练 loss |
| **保留最近 N 个** | `keep_recent_n` 控制磁盘占用，`ckpt_best.tar` 始终保留 |
| **完整性校验** | 每次 `save` 自动写 `.sha256` sidecar；`load` 从最新到最旧尝试，损坏自动回退到上一个可用 checkpoint |
| **自动清理** | 仅保留最近 N 个及其 sidecar, 防止磁盘爆满 |
| **云端备份** | 重要结果同步到云存储 |

## 4. CheckpointManager API

```python
CheckpointManager(save_dir="checkpoints", keep_recent_n=3, mode="min")
# mode: "min" — 指标越小越好 (loss/rmse)
#       "max" — 指标越大越好 (accuracy/ELBO/对数似然)
# save(epoch, config, model_state, optimizer_state, rng_state, is_best=False)
# load(path=None) -> ckpt | None     # path=None 时从最新到最旧尝试加载, 损坏自动回退
# update_best(epoch, val_metric) -> bool
```
