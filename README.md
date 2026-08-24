# experiment-standards

为机器学习训练脚本添加标准化实验基础设施的 Agent Skill。

## 做什么

指导 AI 编程助手为训练脚本添加：
- **Checkpoint 管理** — 定期保存/断点续训/自动清理
- **环境记录** — CPU/GPU/RAM 硬件信息自动采集
- **日志系统** — 训练日志与错误日志分离
- **训练控制** — Early Stopping + 学习率调度 (warmup/decay/cosine)
- **异常恢复** — NaN/Inf 检测、梯度爆炸处理、自动回退
- **评估报告** — JSON 格式结构化输出
- **标准化输出目录** — 统一文件结构

## 适用框架

框架无关，内置 PyTorch 和 Pyro 示例。

## 文件结构

```
experiment-standards/
├── SKILL.md                          # Skill 主文件
├── README.md
├── assets/templates/                 # 可复用代码模板
│   ├── checkpoint_manager.py
│   ├── early_stopper.py
│   └── environment_capture.py
├── references/                       # 详细参考文档
│   ├── checkpoint-guide.md
│   ├── training-control.md
│   ├── logging-guide.md
│   ├── output-spec.md
│   └── resilience-guide.md
└── evals/
    └── evals.json                    # 测试用例
```
