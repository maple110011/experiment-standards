# 大参数模型训练经验

## 已测规模

| 模型 | 参数量 | 数据 | 单 epoch | 显存峰值 | 备注 |
|---|---|---|---|---|---|
| compact CNN | 0.8M | CIFAR-10 | ~3s | <1GB | 快速基准 |
| VGG16-BN | 14.7M | CIFAR-10 | ~10.7s | 1.87GB | SGD+cosine+aug，约 38min 完成 4 方法 |
| MLP 90-128-128-1 | ~0.6M | YearPredictionMSD | ~5.7s | 0.24GB | 大样本小模型 |

## 结论

1. **64GB 显存对小模型/中等模型远不是瓶颈**；14.7M 模型峰值仅 1.87GB。
2. **计算时间才是瓶颈**；DCU 单卡跑 VGG16-BN 约 10.7s/epoch（batch 128）。
3. 大模型训练必须用 `setsid` 后台 + 增量落盘；总时长 30min+ 是常态。
4. 优化器选择影响大：VGG 用 SGD momentum 0.9 + cosine lr + weight decay 5e-4
   效果良好；Adam 训练的 SWAG 在 VGG 上欠训练。
5. 数据增强对 CIFAR 级图像很关键（随机裁剪+翻转）。
6. 大模型上 LLLA 全量 last-layer 会过慢；改用 diag/kron 或子采样。

## 长任务监控清单

- 启动前: 确认 `results_partial.json` 会增量写入、`training/<method>_metrics.csv` 会按 epoch 写。
- 启动: `setsid bash -c 'python3 gpu-runner/jupyter_exec.py --file script.py --timeout 7200 ...' &`
- 运行中: `tail -f /tmp/run.log` 和 `find ... -name results_partial.json`。
- 完成后: 检查 evaluation_report.json、predictions/、events.jsonl 是否齐全。

## 更新：270M MLP 大实验（YearPredictionMSD）

- 模型 MLP 90-16384-16384-1, 270M 参数。
- 1-epoch 基准: 77s (batch 512), 显存 allocated 2.25GB / reserved 5.4GB。
- 结论: 270M 模型在本卡可训练；30 epochs 单模型约 38min。
- 更大模型/生产场景的卡型与训练方式见 `LARGE_SCALE_ENGINEERING.md`（仓库根目录）。
