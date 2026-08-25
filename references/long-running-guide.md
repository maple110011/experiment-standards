# 长任务 / 大模型训练工程指南

> 长时间训练、大参数模型、多方法对比是实验工程最容易翻车的地方。本文把
> 血泪经验沉淀为 6 条纪律：先测基准、后台启动、增量落盘、分开监控、缓存数据、
> 大 batch 优先。全部框架无关；海光 DCU / ROCm 的具体细节见
> [`bayes-dl-dcu/references/dcu-adaptation.md`](../bayes-dl-dcu/references/dcu-adaptation.md)。

## 为什么长任务需要单独一套纪律

一次训练动辄 30 分钟到数小时，出错代价极高。长任务最常见的失败不是代码错，而是：
会话被重置、超时被杀、中途崩溃后什么都没留下、跑完发现 batch 选错了要重来。
这些都可以在**启动前**用少量工作规避。

## 1. 先做 1-epoch 基准，再决定全量配置

不要直接上几百个 epoch。先用最小配置（`--epochs 1` 或几步）测出三个数字：

- 单 epoch / 单 step 耗时 → 外推总训练时长
- 峰值显存（`torch.cuda.memory_allocated/reserved`）→ 判断会不会 OOM
- loss 下降速度 → 判断学习率是否在合理区间

> 为什么：一次 270M MLP 实验先测 1 epoch（77s）再启动，避免了全量配置跑 30
> 分钟才发现 batch 太小或 lr 不对。这一步的成本通常 <1 分钟，收益是省下数小时。

实测参考（海光 DCU 64GB）：270M MLP batch512 单 epoch 77s / 显存 5.2GB；
VGG16-BN(14.7M) batch128 约 10.7s/epoch。**64GB 显存对中小模型远不是瓶颈，
计算时间才是**——所以重点测时间，而不是只盯着显存。

## 2. 长任务必须后台启动 + 超时留余量

交互式 bash 会话通常有几十秒到几分钟的存活限制，前台跑长任务会被打断。
长任务一律后台启动，并让超时上限明显大于预计总时长：

```bash
# 通用: setsid 脱离会话, nohup 忽略挂断信号
setsid bash -c 'python train.py > /tmp/run.log 2>&1' &

# 受限 shell + DCU/ROCm: bash 里 torch.cuda.is_available() 可能是 False (假象),
# 必须通过 Jupyter kernel 执行 GPU 代码; --timeout 要留足余量
setsid bash -c 'python3 gpu-runner/jupyter_exec.py --file train.py --timeout 7200 > /tmp/run.log 2>&1' &
```

> 如果 skill 被部署到其它工作区，`gpu-runner/jupyter_exec.py` 不在工作区根目录时，
> 使用随 skill 分发的 `scripts/jupyter_exec.py`（与工作区版相同），复制到当前
> 工作区后同样调用。

> 为什么：Jupyter kernel 在启动它的 shell 被重置后仍会继续跑；但若超时参数
> 小于训练总时长，进程会被判超时。**轮询** `results_partial.json` 和日志
> （`tail -f`），而不是死等；这样即便中途被中断也能拿到部分结果。

## 3. 增量落盘是底线

每个方法/每个阶段完成**立即**写 `results_partial.json`；每个 epoch 写
`training/<method>_metrics.csv`。不要等最后一次性写结果——中途挂掉会全丢。
详细做法见 [recording-guide.md](./recording-guide.md)。

## 4. 显存与算力分开监控

显存充足 ≠ 速度快，两者要分开记录：

- **结果里记录 `gpu_memory_gb`**：每个方法完成后调用 `experiment_recorder.gpu_memory()`，
  把显存占用写进该方法的 results，用于评估资源消耗和换卡适配。
- **训练中定期打印** allocated/reserved 显存（`resilience-guide.md` §5），
  发现缓慢上涨就是内存泄漏信号。
- **温度/功耗**：DCU 上 `hy-smi` 可看，发现降频即说明散热/功耗墙（详见 dcu-adaptation）。

## 5. 大数据先转缓存

大表格/文本数据每次 `np.loadtxt`/`pd.read_csv` 重复解析会拖慢每个 epoch。
第一次加载后存成 `.npz`/`.pt` 缓存，训练循环直接读缓存：

```python
# 首次: np.savez_compressed("cache.npz", X=X, y=y)
# 之后: d = np.load("cache.npz"); X, y = d["X"], d["y"]
```

> 为什么：解析一次可能几十秒，缓存后读入亚秒级；对 40 万样本的 YearPredictionMSD
> 这类数据尤其明显。缓存的 sha256 记进 `dataset_info`（见 recording-guide §4）。

## 6. 大 batch 优先（配合学习率缩放）

只要显存放得下，优先加大 batch 提升吞吐；代价是收敛行为改变，需配合 lr 缩放。

- **lr 缩放**：batch 翻 N 倍，lr 线性（×N）或平方根（×√N）缩放，见
  [training-control.md](./training-control.md) §3。
- **先测吞吐再定 batch**：不同模型/算子的吞吐曲线不同；`2 的幂不是魔法`——
  实测 270M MLP 上 batch 8192 比 512 快 2.7 倍且 RMSE 更好（18.3 vs 29.7），
  但 CIFAR 小 CNN 上 batch 512 比 128 只快 1.34 倍且精度略降 0.5-1 点。
  每个模型都要实测，不能直接外推。
- **BDL 方法的 batch 敏感性不同**（MC Dropout/SGHMC 依赖小 batch 噪声、
  SWAG 需要更多 epochs 收集快照）：见
  [`bayes-dl-dcu/references/batch-size-guidance.md`](../bayes-dl-dcu/references/batch-size-guidance.md)。

## 7. 模型规模与卡型速查

| 场景 | 参数量 | 显存(fp32+Adam) | 单卡 64GB | 建议 |
|---|---|---|---|---|
| 表格/中小图 | <100M | <4GB | ✅ 轻松 | 当前卡即可 |
| 中图 CNN/Transformer | 100M–1B | 4–16GB | ✅ 可 | DCU/A100 40G |
| BERT/GPT-2 级 | 1B–3B | 16–48GB | ✅ 紧张 | A100 80G / DCU 多卡 |
| GPT-3 级 | 7B–70B | >48GB | ❌ | A100/H100 多卡 |
| 生产级 LLM | 70B+ | 多卡分片 | ❌ | H100/H200 集群 |

大模型训练方式建议：混合精度（bf16/fp16，先在 DCU 上做 1-epoch 测试是否支持）+
gradient checkpointing + AdamW；多卡用 ZeRO/FSDP；对预训练大模型做贝叶斯/不确定度，
优先 last-layer 方法而非全参数贝叶斯。

## 启动前检查清单

- [ ] 已用 1-epoch 基准测出时间/显存/loss 下降，并据此定 batch 和 epochs
- [ ] 长任务用 `setsid`/后台启动，`--timeout` > 预计总时长
- [ ] `results_partial.json` 会增量写入；`training/<method>_metrics.csv` 会按 epoch 写
- [ ] 每个方法会记录 `gpu_memory_gb` 和 `training_time_s`
- [ ] 大数据已转 `.npz` 缓存，sha256 已记入 dataset_info
- [ ] 代码快照 + 数据哈希 + 完整依赖版本已就绪（recording-guide）
- [ ] checkpoint 每 N epoch 保存且含 optimizer + RNG 全状态（checkpoint-guide）
