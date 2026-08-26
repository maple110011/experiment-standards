# 大参数模型训练经验

> 本文记录大参数模型训练的一般性工程经验。海光 DCU 的适配细节见
> [dcu-adaptation.md](./dcu-adaptation.md)；模型规模与卡型速查见
> [long-running-guide.md](../../references/long-running-guide.md) §7。

## 核心经验

1. **显存不是第一瓶颈，计算时间是**：中小模型（<100M 参数）在 64GB 级加速卡上
   显存占用远低于上限；重点测时间（1-epoch 基准），而不是只盯显存。
2. **必须后台 + 增量落盘**：大模型单 epoch 动辄数十秒、总时长 30min+ 是常态，
   用 `setsid` 后台启动并增量写 `results_partial.json`
   （见 [long-running-guide.md](../../references/long-running-guide.md) §2-3）。
3. **优化器选择影响大**：CNN 类模型 SGD momentum + cosine lr + weight decay 通常
   效果好；Adam 训练的 SWAG 可能欠训练。
4. **数据增强对图像很关键**（随机裁剪 + 翻转）。
5. **大模型上避免全量 last-layer Laplace**：改用 diag/kron 或子采样。

## 长任务监控清单

- 启动前: 确认 `results_partial.json` 会增量写入、`training/<method>_metrics.csv` 会按 epoch 写。
- 启动: `setsid bash -c 'python3 scripts/jupyter_exec.py --file script.py --timeout 7200 ...' &`
- 运行中: `tail -f /tmp/run.log` 和 `find ... -name results_partial.json`。
- 完成后: 检查 evaluation_report.json、predictions/、events.jsonl 是否齐全。
