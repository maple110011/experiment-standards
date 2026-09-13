# CHARTER — <课题名>

> 课题启动时写一次。每次怀疑"要不要继续做这个课题"时回来重读。
> 触发重读的条件见 `references/cadence.md` §4。
> **每轮结束跑目标守卫**：`python scripts/goal_guard.py --charter CHARTER.md --ledgers ledgers/ --protocols protocols/ runs/ --decisions DECISIONS.md`
> 参照样张：`assets/samples/CHARTER-sample.md`

## 0. 目的（机读块 —— 目标守卫的唯一参照物，**不能省**）

<goals>
- `basis`: <解决的实际问题，一句话，可观测>
- `method`: <要摸清什么方法边界 / 陷阱 / 适用条件>
- `bridge`: <要从实践里沉淀成什么样的可研究方向>
</goals>

> ⚠️ **至少两个，建议三个。** 只写 `basis` ⇒ agent 会一路做工程而方法学零推进
> （**已实际发生过**：连续两轮纯竞赛工程，偏离完全静默）。
> `bridge` 是"做实际问题能长出理论洞见"这句话的可执行形态。
> 每个 `tag` 必须原样出现在台账条目的标题里，形如 `## M-3 [method] …`。
> → `references/goal-persistence.md`

## 1. 要解决的实际问题
<一句话。不是"研究 X"，而是"让 Y 在 Z 条件下能做到 W"。>

## 2. 成功判据（可观测）
<必须能被外部核对；至少一个数值。**每个目的都要有自己的判据** ——
只给 `basis` 写判据，等于默认其他目的没有验收。>

| 目的 | 判据 | 观测方式 |
|---|---|---|
| `basis` | <数值判据> | <谁怎么核对> |
| `method` | <如：≥1 条理论条目达到「具体方向」且被协议块执行过> | <...> |
| `bridge` | <如：每 3 块里 ≥1 块的方法学条目指向某条 T- 条目> | <...> |

## 3. 当前已知（带证据等级）
- `<台账编号>`（<等级>）<结论>

## 4. 当前未知（带 `?`，不得当作已知使用）
- <未知项> `?`

## 5. 评测噪声下界（开题必填，填数字不填形容词）
<来自 `scripts/score_noise_floor.py`。缺这一节，摘要卡的"不确定度"就没有来源。>

| 量 | 值 | 来源 |
|---|---|---|
| 测试集规模 | <N> | <...> |
| 正类数 / 正类比例 | <P 或扫描区间；未知就写"未知，扫描区间 a–b"> | <...> |
| 单次预测翻转的抖动 | <分数或指标单位> | `score_noise_floor.py` |
| **最小可检测效应（MDE）** | <数字> | <...> |

> 结论：小于 <MDE> 的变化不构成证据，一律记 `薄`。

## 6. 评测口径（跨方法可比性的前提）
<与 `bayes-dl-dcu` 的 `evaluation_config` 对齐；口径不一致就没法比较。>
- 主指标：<...>
- 本地验证协议：<分组方式，如按事件分组 LOEO>
- 阈值选择方式 / 是否用测试集调参：<...>
- 概率与样本落盘方式：<`experiment-standards` 的 `save_probs` / `save_regression_predictions`>

## 7. 三台账位置
- 问题台账：`ledgers/problem-<topic>.md`（条目形如 `## Q-1 [basis] …`）
- 方法台账：`ledgers/methods-<topic>.md`（`## M-1 [method] …`）
- 理论台账：`ledgers/theory-<topic>.md`（`## T-1 [method]` 或 `[bridge] …`）
- 决策日志：`DECISIONS.md`（人定的变更：批准/否决/封存/撤销）

> **条目标题里的 `[tag]` 不是装饰**：目标守卫靠它统计"每个目的推进了几次、
> 最近一次距今几个块"。**不打标记的条目无法参与对账**，守卫会列成 WARN。
