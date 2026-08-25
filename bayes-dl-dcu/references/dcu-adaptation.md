# 海光 DCU / ROCm / HIP 适配经验

## 设备访问

- 某些 agent shell 对 `/dev/kfd`、`/dev/dri/renderD128` 只读，`torch.cuda.is_available()` 会误报 False。
- 解决: 通过 JupyterLab kernel 执行 GPU 代码。仓库里有现成工具:
  `gpu-runner/jupyter_exec.py`。
- 长任务用 `setsid ... &` 后台运行，轮询 `results_partial.json` 和日志。

## 环境识别

- `torch.version.cuda` 为 None；`torch.version.hip` = 6.3.x。
- 架构: `torch.cuda.get_device_properties(0).gcnArchName` = `gfx936:sramecc+:xnack-`。
- 驱动: `hy-smi --showdriverversion`，当前 `Driver Version: 6.3.31-V1.5.3.beta`。
- 卡型号: `torch.cuda.get_device_name(0)` = `BW`，显存 64GB。

## 性能特征

- fp32 matmul: 2048→43.9 / 4096→52.5 / 8192→53.5 TFLOPS。
- MLP 训练步 (batch4096, hidden256): 1.55ms DCU vs 2530ms CPU。
- BNN SVI step (n=512, hidden20): 21.4ms DCU vs 129.6ms CPU。
- **首次调用新算子会触发内核编译（数百 ms），基准测试必须先 warmup。**

## Pyro 在 DCU 上的坑

- 模型内部先验参数必须显式创建在 `x.device` 上，否则 AutoNormal guide 参数留在 CPU。
- Checkpoint 恢复: `pyro.get_param_store().set_state()` 后参数通常在 CPU
  （因为 `torch.load(map_location="cpu")`），必须逐个 `.to(device)` 移回:
  ```python
  ps = pyro.get_param_store()
  for name in list(ps.get_all_param_names()):
      p = ps.get_param(name)
      ps.replace_param(name, p.detach().to(device), p)
  ```
- Pyro 1.9.x 恢复参数用 `set_state`，不是 `load_state`。

## 包管理

- 往 `es-eval/venv` 装包用 `--no-deps`，防止 PyPI torch 覆盖 HIP torch 2.9.0。
- 装完检查 `torch.version.hip == '6.3.26093'` 且 `torch.cuda.is_available() == True`（在 Jupyter kernel 里检查）。
- `laplace-torch` 需要 `curvlinops-for-pytorch==2.0.0`（3.x 无 `_base` 不兼容），
  还需要 `torchmetrics` 和 `et_xmlfile`（openpyxl 依赖）。

## 多输出回归注意

- `laplace-torch` 的 last-layer regression 对多输出模型（如时序一步预测 D 个序列）
  会形状不匹配；多输出场景先禁用 LLLA 或改造成逐输出。

## 长任务经验

- bash 会话有 300s 限制，长任务 `setsid` 后台 + 轮询。
- 每完成一个方法立即 `update_results_json`；进程被杀也有部分结果。
- Jupyter kernel 在启动它的 shell 被重置后仍会继续跑，注意清理空闲 kernel 释放显存。
