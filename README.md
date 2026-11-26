# experiment-standards

一个给 AI 编程助手（Agent）用的 Skill 仓库，把普通 ML 训练脚本升级成「能断点续训、可复现、可跨设备比较、有标准化评估」的实验，并把「Agent 跑实验、人做判断」这件事变成有闸门的协作流程。里面有三个 Skill：

| Skill | 位置 | 做什么 |
|---|---|---|
| **experiment-standards** | 根目录 | 实验工程基础设施：checkpoint、日志、环境记录、早停、LR 调度、异常恢复、评估报告、长实验记录包 |
| **bayes-dl-dcu** | [`bayes-dl-dcu/`](./bayes-dl-dcu/) | 贝叶斯深度学习的方法公平对比协议、不确定度校准、分布偏移/OOD、海光 DCU 适配、大模型训练经验 |
| **collab-lab** | [`collab-lab/`](./collab-lab/) | 人机协作层：预注册协议块（跑之前先定判据）、五分钟摘要卡、决策卡与决策日志、问题/方法双台账、评测噪声下界 |

三者配合使用：`experiment-standards` 负责**可复现**，`bayes-dl-dcu` 负责**可比**，
`collab-lab` 负责**可判断**——把前两者的产物压缩成人类带宽能消化的形状，并强制
「跑完必须停下来等人回答」。

```
collab-lab  ← 人在回路：预注册 / 摘要 / 决策 / 台账
   ├── experiment-standards   ← L1 执行与记录（可复现）
   └── bayes-dl-dcu           ← 方法协议与校准指标（可比）
```

## 何时用 / 不用

**用（满足任一即可）**

- 训练脚本需要 checkpoint/断点续训、日志、环境记录、早停、异常恢复、评估报告
- 要跑长实验（几十分钟以上）或大模型，担心中途挂掉/超时，需要监控显存和算力
- **要建立远程接入**（CANNLab 昇腾 NPU、超算互联网/SCNet 海光 DCU、SSH 云主机、Kaggle 免费 GPU）——三种拓扑怎么选、凭据与隧道、`dsh web` 的 loopback/Host 栅栏、出网代理、持久盘、长命令载体、验证清单与回收
- 要多方法对比或写论文，需要标准化记录包、预测分布落盘、校准曲线/TensorBoard
- 要比较贝叶斯深度学习方法、做不确定度校准、在 DCU/HIP 上跑 PyTorch/Pyro（用 `bayes-dl-dcu`）
- **Agent 跑得比你读得快，结果一多就失去方向，或分不清是噪声还是真改进（用 `collab-lab`）**
- **想同时解决实际问题并积累方法层面的洞见（陷阱/适用边界/改进方向）（用 `collab-lab`）**

**不用**

- 纯一次性快速原型、不需要记录和复现的小实验
- 纯模型架构设计 / 推理方法选择（不属于本仓库三个 Skill 的范围）
- 单轮就能做完的工程任务（`collab-lab` 的闸门是为多轮探索设计的，单轮任务上只会变慢）

## 做什么

指导 AI 编程助手为训练脚本添加：

- **Checkpoint 管理** — 定期保存 / 断点续训 / 损坏自动回退 / sha256 sidecar / `mode="min"/"max"`
- **环境记录** — CPU/GPU/RAM/磁盘 + 完整依赖版本 + `hy-smi` 驱动版本，支持 CUDA / ROCm(HIP, 海光 DCU) / MPS
- **日志系统** — 训练日志与错误日志分离，CSV 指标，TensorBoard 曲线
- **训练控制** — Early Stopping + LR 调度（warmup / 阶梯 / cosine）+ batch↔lr 缩放
- **异常恢复** — NaN/Inf 检测、梯度裁剪、OOM 回退、Pyro 设备恢复
- **评估报告** — JSON 结构化输出，校准曲线（分类 reliability / 回归 coverage）
- **标准化输出目录** — 统一文件结构
- **大型实验记录包** — `experiment_recorder.py`：run manifest、代码快照、数据哈希、事件时间线、逐 epoch 指标、预测概率/均值方差/样本、切分索引、增量结果、分布偏移与温度缩放记录、TensorBoard、模型权重
- **长任务 / 大模型训练** — 1-epoch 基准先行、后台启动与超时余量、受限 shell 通过 Jupyter kernel 跑 GPU、显存/算力分开监控、数据缓存、batch 缩放、卡型选型
- **远程接入** — 有 SSH 就一条命令（`scripts/remote_job.sh`：doctor/submit/status/logs/stop/ship/fetch，远端只需 bash+setsid）；无 SSH 才把 dsh 装进容器（SCNet 就是这条兜底路）；三条拓扑（本地 DSH 命令通道 / 远端 dsh 常驻 / 本地 DSH + OpenSSH）、五段链路（凭据→建连→传输→存活→回收）、`dsh web` 的 loopback 与 Host 栅栏、SSH 隧道与平台自定义服务端口暴露、出网代理探测、DSH_HOME 文件化配置、`start.sh` 参数化 + `run.sh` 参数持久化、CANNLab CLI 的隧道与 job 协议、海光 DCU 容器里的 torch/依赖纪律、10 分钟验证清单、接新平台的 6 步复用表
- **人机协作回路**（`collab-lab`）— 三层回路（L1 执行记录 / L2 预注册协议块 / L3 摘要与决策）、严格闸门（一个闸门=一个协议块，跑完必须等回答）、摘要卡字段与字符预算、机制三分类（实现问题/调参问题/方法本身的性质）、**三级台账**（问题/方法/理论）与证据等级（稳定/薄/不稳/?）、**理论梯子**（把"实践需要而方法给不了、现有框架解释不了"的落差提炼成可研究的理论问题）、**探究地图**（按信息增量分五节：已确认/有冲突/单来源/已证伪/未探究——治"不知道走过了什么"）、**多 agent 汇总**（fan-out 五条纪律与冲突台账）、评测噪声下界与最小可检测效应、五分钟验收测试

## 适用框架

框架无关，内置 PyTorch 和 Pyro 示例。

## 文件结构

```
experiment-standards/
├── SKILL.md                          # Skill 1: 实验工程标准化（根目录）
├── README.md
├── assets/templates/                 # 可复用代码模板
│   ├── checkpoint_manager.py         # Checkpoint + 完整 RNG 状态
│   ├── early_stopper.py              # Early Stopping (min/max)
│   ├── environment_capture.py        # CUDA/HIP/MPS 环境采集
│   ├── evaluation_report.py          # 评估报告 / 实验元数据
│   └── experiment_recorder.py        # 大型实验记录包（含 TensorBoard）
├── scripts/
│   ├── jupyter_exec.py               # 受限 shell 通过 Jupyter kernel 跑 GPU 的助手
│   └── remote_job.sh                 # SSH 远端作业协议：提交/状态/日志/终止/取回
├── references/                       # Skill 1 参考文档
│   ├── checkpoint-guide.md
│   ├── training-control.md
│   ├── logging-guide.md
│   ├── output-spec.md
│   ├── resilience-guide.md
│   ├── recording-guide.md            # 大型实验记录标准
│   ├── long-running-guide.md         # 长任务/大模型训练工程
│   ├── remote-access.md              # 远程接入：选拓扑 / 五段链路 / 通道与信任 / 验证 / 复用
│   ├── cannlab-guide.md              # 本地 DSH 遥控昇腾 NPU（CANNLab CLI）
│   ├── scnet-guide.md                # SCNet 海光 DCU 接入：SSH 直连优先，容器内 dsh 兜底
│   └── kaggle-guide.md               # Kaggle 免费 T4：拓扑 A′，没有 SSH 的平台 API 批次作业
├── evals/
│   ├── evals.json                    # 测试 prompt（含远程接入场景）
│   └── run_evals.py                  # 自动单元测试 / 输出校验 / DCU 环境校验
├── bayes-dl-dcu/                     # Skill 2: 贝叶斯深度学习 / DCU 领域经验
│   ├── SKILL.md
│   ├── references/
│   │   ├── methods-and-results.md    # 方法公平对比协议
│   │   ├── dcu-adaptation.md
│   │   ├── batch-size-guidance.md
│   │   ├── large-model-experience.md
│   │   └── research-topics.md
│   └── evals/
│       └── evals.json
└── collab-lab/                       # Skill 3: 人机协作回路
    ├── SKILL.md
    ├── references/
    │   ├── protocol-block.md         # 预注册协议块：判据先于结果
    │   ├── digest-card.md            # 摘要卡字段、字符预算、失败模式
    │   ├── ledgers.md                # 三级台账：证据等级、洞见标准、"被用"测试
    │   ├── theory-ladder.md          # 理论梯子：从实际问题长出可研究的理论问题
    │   ├── experiment-map.md         # 探究地图与多 agent 汇总：五节地图、冲突台账、fan-out 纪律
    │   └── cadence.md                # 闸门强度、五分钟测试、破例条件
    ├── assets/
    │   ├── templates/                # 空壳模板（含占位符，复制后填写）
    │   │   ├── CHARTER.template.md
    │   │   ├── PROTOCOL.template.md
    │   │   ├── DIGEST.template.md
    │   │   ├── DECISIONS.template.md
    │   │   ├── LEDGER-problem.template.md
    │   │   ├── LEDGER-methods.template.md
    │   │   ├── LEDGER-theory.template.md
    │   │   ├── QUESTION-MAP.template.md
    │   │   └── CONTRADICTIONS.template.md
    │   └── samples/                  # 填写完成的样张（校验基准）
    │       ├── CHARTER-boiler.md
    │       ├── PROTOCOL-P-BOILER-001.md
    │       ├── DIGEST-P-BOILER-000.md
    │       ├── LEDGER-problem-boiler.md
    │       ├── LEDGER-methods-boiler.md
    │       ├── LEDGER-theory-boiler.md
    │       └── _negative/            # 故意违规，用于反向自检
    │           ├── DIGEST-bad.md
    │           └── LEDGER-theory-bad.md
    ├── scripts/
    │   ├── score_noise_floor.py      # 评测噪声下界 / 最小可检测效应
    │   ├── check_collab_artifacts.py # 产物校验 + 自检 + evals 执行器
    │   ├── conflict_scan.py          # 跨方向答案变体扫描（探究地图的原料）
    │   └── validate_frontmatter.py   # 三个 skill 的 frontmatter 规范校验
    └── evals/
        └── evals.json
```

## 快速使用

```bash
# 运行模板单元测试
python evals/run_evals.py

# 校验标准化输出目录
python evals/run_evals.py --check-outputs outputs

# 校验 DCU/HIP 环境记录
python evals/run_evals.py --check-dcu-env outputs/environment.json

# collab-lab：产物校验 / 自检 / 跑 evals（不依赖 shell，Windows PowerShell 5.1 也可用）
python collab-lab/scripts/check_collab_artifacts.py --self-test
python collab-lab/scripts/check_collab_artifacts.py --run-evals
python collab-lab/scripts/check_collab_artifacts.py --digest  runs/<exp>/DIGEST-P-XXX-001.md
python collab-lab/scripts/check_collab_artifacts.py --protocol protocols/PROTOCOL-P-XXX-002.md
python collab-lab/scripts/check_collab_artifacts.py --ledger  ledgers/methods-<topic>.md
python collab-lab/scripts/check_collab_artifacts.py --ledger  ledgers/theory-<topic>.md

# collab-lab：三个 skill 的 frontmatter 是否符合 skill 规范
python collab-lab/scripts/validate_frontmatter.py

# collab-lab：评测噪声下界（开题必做）
python collab-lab/scripts/score_noise_floor.py --n-test 510 --formula recall_exp_fpr --tau 0.05 --k 3
```

## 大型实验记录包（长实验必读）

长实验使用 `assets/templates/experiment_recorder.py`：

```python
from experiment_recorder import make_run_dir, log_event, log_epoch, \
    update_results_json, save_probs, save_regression_predictions, \
    save_split_indices, save_model_weights

run_dir = make_run_dir("runs", "my_experiment", config=CONFIG,
                       code_paths=[__file__], dataset_info={...})
log_event(run_dir, "data_loaded", n=len(train_set))
save_split_indices(run_dir, train_idx, val_idx, test_idx)
for epoch in range(num_epochs):
    ...
    log_epoch(run_dir, "MAP", epoch, loss=loss, val_acc=val_acc)
update_results_json(run_dir, "results_partial.json", "MAP", {"acc": acc})
save_probs(run_dir, "MAP", probs, y_true, num_classes)             # 分类
save_regression_predictions(run_dir, "MAP", mean, var, y_true)     # 回归
save_model_weights(run_dir, "MAP", model, is_best=True)
```

每个 run 目录包含：`run_manifest.json`、`code/`、`training/*.csv`、`predictions/`、
`results_partial.json`、`evaluation_report.json`、`tb/`（TensorBoard）、`figures/`。
