# 日志与环境记录

> **模板代码**: `assets/templates/environment_capture.py` — 可直接复制到项目中使用。

## 1. 运行环境记录 ⚠️

不同设备（笔记本CPU vs Colab GPU vs 计算卡）上耗时不可比，必须记录硬件。

```python
import json
from environment_capture import capture_environment

env = capture_environment()
json.dump(env, open("outputs/environment.json", "w"), indent=2,
          ensure_ascii=False, default=str)
json.dump({"seed": CONFIG["seed"]}, open("outputs/seed.json", "w"), indent=2)
```

`capture_environment()` 自动记录: CPU型号/核数、GPU型号/VRAM/架构、总RAM、
PyTorch/CUDA/HIP 版本、磁盘可用空间、运行时环境（Colab/Local）。支持
CUDA / ROCm(HIP, 含海光 DCU) / MPS / CPU-only 四种后端。依赖 `psutil`
（可选，未安装时跳过 CPU/内存/磁盘详细信息）。

## 2. 日志系统 ⚠️

三级日志架构 — 训练日志(完整) + 错误日志(单独) + 控制台:

```python
import logging, os

os.makedirs("outputs", exist_ok=True)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

# 控制台: INFO 及以上
ch = logging.StreamHandler(); ch.setLevel(logging.INFO); ch.setFormatter(fmt)
logger.addHandler(ch)

# 训练日志: DEBUG 及以上 (完整记录)
fh1 = logging.FileHandler("outputs/training.log", encoding="utf-8")
fh1.setLevel(logging.DEBUG); fh1.setFormatter(fmt)
logger.addHandler(fh1)

# 错误日志: ERROR 及以上 (单独文件, 空文件=无错误)
fh2 = logging.FileHandler("outputs/errors.log", encoding="utf-8")
fh2.setLevel(logging.ERROR); fh2.setFormatter(fmt)
logger.addHandler(fh2)
```

## 3. CSV 指标日志

⚠️ **续训时必须用追加模式 (`"a"`)，否则会覆盖之前的指标历史。**
`DictWriter` 的 `fieldnames` 与每个 `writerow` 的键必须完全一致。

```python
import csv, datetime

csv_file = open("outputs/metrics.csv", "a" if resume else "w", newline="")
csv_logger = csv.DictWriter(
    csv_file,
    fieldnames=["epoch", "train_loss", "val_metric", "lr", "timestamp"]
)
if resume is None:
    csv_logger.writeheader()

# 训练循环中:
csv_logger.writerow({
    "epoch": epoch,
    "train_loss": float(loss),
    "val_metric": val_metric,
    "lr": lr,
    "timestamp": datetime.datetime.now().isoformat(),
})
csv_file.flush()   # 每个 epoch 后刷盘, 防止训练中断丢失
```

## 4. 实验元数据

```python
import json
from datetime import datetime
from environment_capture import capture_environment

metadata = {
    "experiment_name": "my_experiment_v1",
    "date": datetime.now().isoformat(),
    "environment": capture_environment(),
    "config": CONFIG,
    "dataset": {"n_train": len(train_set), "input_dim": input_dim},
}
json.dump(metadata, open("outputs/experiment_metadata.json", "w"),
          indent=2, default=str)
```

> 也可直接用模板 `assets/templates/evaluation_report.py` 中的
> `generate_experiment_metadata()`。
