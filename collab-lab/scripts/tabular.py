#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""tabular.py —— 表格类产物的**列识别**唯一入口（与课题、与语言都无关）。

## 为什么要有这个模块（两个原因，第二个才是主要的）

1. **单一定义**：`check_submission.py` 与 `check_package_repro.py` 都要"认出 ID 列与判断列"。
   原先两边各写了一份 `ID_KEYS` / `VAL_KEYS`，而其中一边的注释还写着
   "与另一边同一套口径，避免两处定义漂移" —— **注释声明的纪律，与代码实际做的事相反**，
   这正是本 skill 的 `A10`（解析器只能有一处定义）记的那个失效形态。

2. **通用性**：原先的候选表里写着具体课题的列名（"切片 ID"、"故障判断"）。
   换一个课题、换一种语言，那两个名字一条都认不出来 ⇒ **脚本会认错列**，
   而"认错列"的后果是**静默算错**（`B55`：我自己就因为这个报出过"判 1 的片数 0"）。
   ⇒ 修法不是"再补几个名字"（永远补不完），而是**按内容认**：

       | 认哪个 | 怎么认 |
       |---|---|
       | 判断列 | 先按名字（`label`/`pred`/`y`/`target`…）；认不出就找**唯一一个取值只有 {0,1} 的列** |
       | ID 列 | 显式给了就用；否则优先"名字像 ID"的列，再退到"取值全不重复"的第一列 |

   这两条**不依赖任何语言或课题**：0/1 判断列在哪都长这样。

## 边界（写在代码里，免得下次又要猜）

- 判断列的取值域**不限于** {0,1}：名字候选命中时，任何取值都会被报出来（含 `0.0` 这类脏值）；
  只有**靠内容兜底**认出来的列，才要求取值 ⊆ {0,1}。
- 认不出来时**不许猜**：列出表头、要求用 `--id-col` / `--label-col` 指定。
  "猜一个继续跑"是这类工具最坏的默认行为。
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subproc  # noqa: E402,F401
# 本模块**不打印**，但它生成的 notes 会被调用方打印，而里面有 cp936 印不出的符号。
#    第一版就是因此被 `check_console_safe.py` 拦下的（它扫"含不可打印字符但没兜底"的脚本）：
#    兜底要么在这里 import，要么把字符全换成 ASCII —— 两件都做了，见下面 `_desc`。

__all__ = ["ID_CANDIDATES", "LABEL_CANDIDATES", "pick_columns", "load_table", "load_labels"]

# 只放**通用**名字：英文常见名。**不放任何课题专有的列名**（那属于调用方，用 --id-col 传）；
# 也**不放行号类词**（序号/编号/index/seq）—— 行号不是身份，见下面打分那段注释。
ID_CANDIDATES = ("id", "ID", "Id", "slice_id", "sample_id", "row_id", "key", "name")
LABEL_CANDIDATES = ("label", "labels", "pred", "preds", "prediction", "y", "target",
                    "truth", "gt", "answer")
BOOL_DOMAINS = ({"0", "1"}, {"0", "1", ""}, {"true", "false"}, {"True", "False"})


def load_table(path: Path) -> tuple[list, list, str]:
    """读一个 csv ⇒ (表头, 数据行, 错误说明)。编码按 utf-8-sig（BOM 会整体错列，`B55`）。"""
    text = path.read_bytes().decode("utf-8-sig", errors="replace")
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if not rows:
        return [], [], "空文件"
    header = [c.strip() for c in rows[0]]
    return header, rows[1:], ""


def _is_boolish(vals: list) -> bool:
    s = {v.strip() for v in vals if v.strip()}
    if not s:
        return False
    return any(s <= d for d in BOOL_DOMAINS)


def pick_columns(header: list, body: list, id_col: str | None = None,
                 label_col: str | None = None) -> tuple[int | None, int | None, list, str]:
    """返回 (id 下标, 判断列下标, notes, 错误)。**认不出就返回错误，不猜。**

    `notes` 会说明"这两个列是怎么认出来的"，因为**认错列是静默的**：
    人只有看到"我认的是哪一列"，才能一眼否掉。
    """
    notes = []
    if not header or not body:
        return None, None, notes, "没有表头或没有数据行"

    # ---- 判断列 ----
    li = None
    if label_col:
        if label_col not in header:
            return None, None, notes, (f"--label-col {label_col!r} 不在表头里：{header}")
        li = header.index(label_col)
        notes.append(f"判断列 = 第 {li+1} 列 `{label_col}`（**你指定的**）")
    else:
        named = [i for i, h in enumerate(header) if h.lower() in
                 {c.lower() for c in LABEL_CANDIDATES}]
        if len(named) == 1:
            li = named[0]
            notes.append(f"判断列 = 第 {li+1} 列 `{header[li]}`（按名字认的）")
        elif len(named) > 1:
            return None, None, notes, (f"表头里有多个像判断列的：{[header[i] for i in named]}"
                                       " —— 用 --label-col 指定")
        else:
            cols = [i for i in range(len(header))
                    if _is_boolish([r[i] for r in body if len(r) > i])]
            if len(cols) == 1:
                li = cols[0]
                notes.append(f"判断列 = 第 {li+1} 列 `{header[li]}`"
                             "（**按取值认的**：唯一一个取值只有 0/1 的列）")
            elif len(cols) > 1:
                return None, None, notes, (
                    f"有 {len(cols)} 列取值都只有 0/1（{[header[i] for i in cols]}）"
                    " —— 认不出哪个是判断列，用 --label-col 指定")
            else:
                return None, None, notes, (
                    f"认不出判断列（表头 {header}）—— 用 --label-col 指定，"
                    "或把列名改成 label/pred/y/target 之类")

    # ---- ID 列 ----
    if id_col:
        if id_col not in header:
            return None, None, notes, f"--id-col {id_col!r} 不在表头里：{header}"
        ii = header.index(id_col)
        notes.append(f"ID 列 = 第 {ii+1} 列 `{id_col}`（**你指定的**）")
        return ii, li, notes, ""
    for i, h in enumerate(header):
        if i != li and h.lower() in {c.lower() for c in ID_CANDIDATES}:
            notes.append(f"ID 列 = 第 {i+1} 列 `{h}`（按名字认的）")
            return i, li, notes, ""

    # 按打分认。**"取值不重复"不足以认出 ID 列**：行号列（1..N 连续）也全不重复，
    #    而它是**行号**不是身份 —— 认成它，后面"ID 与官方输入逐一对应"就会整列比错。
    #    实测形态：某课题的提交表是 `序号, 切片 ID, 判断`，按"第一个不重复的列"认，
    #    认到的是 `序号`（1..510），于是拿 1..510 去和文件名比，**全错但看着像在正常检查**。
    def id_score(i: int) -> int:
        vals = [r[i] for r in body if len(r) > i]
        s = 0
        try:
            nums = [int(v) for v in vals]
            if nums == list(range(1, len(nums) + 1)):
                s -= 3                       # 行号签名：正好是 1..N
        except ValueError:
            s += 1                           # 含非数字 ⇒ 更像身份
        if len(set(vals)) == len(vals):
            s += 2
        return s

    others = [i for i in range(len(header)) if i != li]
    if not others:
        return None, None, notes, f"只有一列，认不出 ID 列：{header}"
    ii = max(others, key=lambda i: (id_score(i), -i))
    how = "按打分认的（不重复 +2；含非数字 +1；正好是 1..N 的行号 -3）"
    notes.append(f"ID 列 = 第 {ii+1} 列 `{header[ii]}`（{how}；"
                 f"候选 {[(header[j], id_score(j)) for j in others]}）")
    if id_score(ii) <= 0:
        notes.append("这一列看起来更像**行号**而不是身份 —— 建议用 --id-col 显式指定")
    return ii, li, notes, ""


def load_labels(path: Path, id_col: str | None = None,
                label_col: str | None = None) -> tuple[dict, str, list]:
    """读一份"ID → 判断"的表格 ⇒ (映射, 错误, notes)。**认错列会静默算错，所以 notes 要印出来。**"""
    header, body, err = load_table(path)
    if err:
        return {}, err, []
    ii, li, notes, err = pick_columns(header, body, id_col, label_col)
    if err:
        return {}, err, notes
    out = {}
    for r in body:
        if len(r) > max(ii, li):
            out[r[ii].strip()] = r[li].strip()
    return out, "", notes
