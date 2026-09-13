#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
r"""check_run_integrity.py —— **跑评测之前，先确认"跑出来的东西还在"。**

## 它治的是哪句话

> "我**无法利用** agent 所写代码产出的结果和数据。"

在评测这一层，这句话的形态是：**评测跑完了，但被打分的那份产出不是完整的那份。**

第 32 轮实测（`iteration-2` 的成绩单）：
- `eval-1/with_skill/run-1/outputs/` **是空的** ⇒ 记成"无产出"，整条 eval 从成绩单里消失；
- `eval-6/with_skill/run-1/outputs/` **少 3 个文件**（缺 `answer.md` / 摘要卡 / 方案），
  而**同一 run 的完整副本就在隔壁** `eval-6/with_skill/outputs/`（9 个文件）。
  打分打的是那个残缺副本 ⇒ 5 条断言里 2 条"无法判定" ⇒ 3/5。

⇒ 后果不是"少了一条数据"，而是**成绩单给出了一个错误结论**：
`eval-6` 恰好是那条"我已经跟不上了、很抗拒继续做"的题 ——
也就是本 skill 立文要治的那个症状。它在旧成绩单上显示成"skill 毫无增益（+0.00）"，
而真实原因是**我在 agent 还在写的时候就重构了目录**。

## 它检查什么（三条，都是机械的）

1. `outputs/` 非空；
2. `eval_metadata.json` 里声明的 `required_outputs` 全部存在且非空；
3. **同一 run 不允许有两份不一致的产出副本**（`<arm>/outputs/` 与
   `<arm>/run-*/outputs/` 同时存在且文件集合不同 ⇒ FAIL）。
   第 3 条是第 32 轮那个真实事故的直接形式。

## 判定与处置

`OK` = 可以打分；`INVALID` = **不许打分，必须重跑**。
⇒ **空产出绝不记为 0 分**：0 分是"做了但没做对"，空产出是"这次测量没发生"。
把后者记成前者，等于用一次事故去降低 skill 的分数 —— 那正是旧成绩单犯的错。

用法：
    python scripts/check_run_integrity.py <iteration 目录> [--json]
    python scripts/check_run_integrity.py --self-test
退出码：0 = 所有 run 都 OK；1 = 有 INVALID；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subproc  # noqa: E402,F401  （自身输出也不许崩）


def _files(d: Path) -> set:
    if not d.is_dir():
        return set()
    return {p.name for p in d.iterdir() if p.is_file() and p.stat().st_size > 0}


def check_run(run_dir: Path, arm_dir: Path, meta: Path | None = None):
    """返回 `(hard, soft)`：hard = 必须重跑；soft = 可打分但没核对过完整性。

    ⚠️ 两者**必须分开**。第 32 轮第一次跑在 `iteration-2` 上时，
    "找不到 eval_metadata.json" 把 16 个 run 全判成 INVALID ——
    而那批老 run 是在这个约定存在**之前**跑的，它们本身没问题。
    真正的两个硬问题（一个空目录、一份不一致的副本）被埋在 16 行噪声里。
    ⇒ 与 `D4`（校验器误报比不报更糟）同一条：**会让报告被忽略的判定，等于没有判定。**
    """
    hard, soft = [], []
    outs = run_dir / "outputs"
    if not outs.is_dir():
        return [f"没有 outputs/ 目录：{outs}"], []
    got = _files(outs)
    if not got:
        hard.append("outputs/ 是空的 —— **空产出不许记 0 分**，必须重跑"
                    "（0 分是「做了没做对」，空产出是「这次测量没发生」）")
    req: list = []
    cands = [p for p in (meta, arm_dir / "eval_metadata.json") if p is not None]
    src = next((p for p in cands if p.exists()), None)
    if src is None:
        soft.append("没有 eval_metadata.json ⇒ **未核对**「声明的必需产出是否都在」"
                    "（老 iteration 在此约定之前，属正常；新 iteration 应补上）")
    else:
        try:
            req = json.loads(src.read_text(encoding="utf-8-sig")).get(
                "required_outputs", []) or []
        except Exception as e:
            hard.append(f"{src.name} 读不动：{e}")
    missing = [f for f in req if f not in got]
    if missing:
        hard.append(f"声明必需的产出缺失或为空：{missing}")
    # 第 3 条：同一 run 的另外一份副本。
    # ⚠️ 候选里**必须包含 arm 层的 `outputs/`** —— 第 32 轮的事故正是
    #    `eval-6/with_skill/outputs/`（arm 层，9 个文件）与
    #    `eval-6/with_skill/run-1/outputs/`（5 个文件）不一致。
    #    只比 `run-*/outputs` 之间会漏掉它（自证的 two_copies 场景当场抓到）。
    cds = [arm_dir / "outputs"] + sorted(arm_dir.glob("run-*/outputs"))
    for other in cds:
        if other.resolve() == outs.resolve():
            continue
        o = _files(other)
        if o and o != got:
            hard.append(
                f"同一 run 有两份**不一致**的产出副本：本目录 {len(got)} 个文件，"
                f"{other.parent.name}/outputs 有 {len(o)} 个（差集 "
                f"{sorted(o ^ got)[:4]}）—— 打分前必须先确定哪一份是准的，"
                "并把另一份删掉（第 32 轮的事故就是这个形态）")
    return hard, soft


def scan(iteration: Path):
    """扫 `iteration-N/eval-*/<arm>/[run-*]/outputs`。

    ⚠️ **只认名字以 `eval` 开头的目录**。第一次跑时没有这个约束，
    于是 `iteration-3/submissions/`（竞赛提交包）被当成 6 个 "arm"，
    报了 6 条"没有 outputs/"—— **而它们根本不是评测 run**。
    ⇒ 与 `B44` / `D4` 同一条：会让报告被忽略的误报等于没有报告。
    （iteration 目录按约定只放 `eval-*`；要放别的东西就得在这里写明豁免。）
    """
    rows = []
    evals = sorted(p for p in iteration.iterdir()
                   if p.is_dir() and p.name.lower().startswith("eval"))
    if not evals:
        print(f"WARN  {iteration} 下没有 `eval*` 目录 —— 是不是扫错地方了？")
    for ev in evals:
        meta = ev / "eval_metadata.json"
        for arm in sorted(p for p in ev.iterdir() if p.is_dir()):
            if arm.name == "outputs":
                continue
            if (arm / "run-1").is_dir():
                run_dirs = sorted(p for p in arm.glob("run-*") if p.is_dir())
            elif (arm / "outputs").is_dir():
                run_dirs = [arm]
            else:
                rows.append((arm, ["没有 outputs/ 也没有 run-*/outputs"], []))
                continue
            for rd in run_dirs:
                hard, soft = check_run(rd, arm, meta)
                rows.append((rd, hard, soft))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="评测 run 的产出完整性门禁")
    ap.add_argument("iteration", nargs="?", help="iteration-N 目录")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    if not args.iteration:
        ap.print_help()
        return 2
    it = Path(args.iteration)
    if not it.is_dir():
        print(f"FAIL  目录不存在：{it}")
        return 2
    rows = scan(it)
    bad = [r for r in rows if r[1]]
    soft_n = sum(1 for r in rows if r[2] and not r[1])
    if args.json:
        print(json.dumps([{"run": str(r), "hard": h, "soft": s} for r, h, s in rows],
                         ensure_ascii=False, indent=1))
        return 1 if bad else 0
    print("=" * 88)
    print(f"评测产出完整性：{it}（{len(rows)} 个 run）")
    print("=" * 88)
    for rd, hard, soft in rows:
        tag = "INVALID   " if hard else ("UNVERIFIED" if soft else "OK        ")
        print(f"  {tag} {rd}")
        for p in hard:
            print(f"          ✗ {p}")
        for p in soft:
            print(f"          · {p}")
    print("-" * 88)
    if bad:
        print(f"⇒ **{len(bad)}/{len(rows)} 个 run 不许打分**（空产出 / 副本不一致 / 缺声明文件）："
              "先修产出，再 grading。")
        if soft_n:
            print(f"   （另有 {soft_n} 个只是**未核对**，不是错误 —— 老 iteration 没有元数据属正常）")
        return 1
    print(f"⇒ {len(rows)} 个 run 没有硬问题，可以打分"
          + (f"；其中 {soft_n} 个未核对声明产出。" if soft_n else "。"))
    return 0


def _self_test() -> int:
    """四个并排场景：完整 / 空 / 缺声明文件 / 两份副本不一致。

    ⚠️ 单场景抓不住"检查恒真或恒假"（`B28` 第 ② 项）：四个里两个是"不该报"。
    临时目录写在脚本旁边（不用 `tempfile`：Windows 沙箱下清理会 chmod 失败）。
    """
    import shutil
    print("=" * 88)
    print("check_run_integrity 自证（四个并排场景）")
    print("=" * 88)
    base = Path(__file__).resolve().parent / "_run_integrity_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    ok = True
    try:
        def mk(name, files, req, extra_copy=None):
            it = base / name
            ev = it / "eval-0"
            arm = ev / "with_skill"
            (arm / "run-1" / "outputs").mkdir(parents=True)
            # 元数据写在 **eval 目录**（skill-creator 的约定）
            ev.joinpath("eval_metadata.json").write_text(
                json.dumps({"required_outputs": req}, ensure_ascii=False), encoding="utf-8")
            for f in files:
                (arm / "run-1" / "outputs" / f).write_text("x" * 20, encoding="utf-8")
            if extra_copy is not None:
                (arm / "outputs").mkdir(parents=True, exist_ok=True)
                for f in extra_copy:
                    (arm / "outputs" / f).write_text("y" * 20, encoding="utf-8")
            return it

        cases = [
            ("complete", ["answer.md", "PROTOCOL-P-001.md"],
             ["answer.md", "PROTOCOL-P-001.md"], None, False),
            # ⚠️ `empty` 的 `required_outputs` **必须是空的**。
            #    第一版写成 `["answer.md"]`，于是"空产出"与"缺声明文件"**两条检查同时命中** ——
            #    变异把"空产出"那条关掉时，场景**照样**报 INVALID（被另一条兜住），
            #    变异测试于是报"未被抓到"。这正是 `B28` 第 ② 项的形态：
            #    **一个场景里放两条失败路径，等于两条都没被隔离。**
            ("empty", [], [], None, True),
            ("missing_declared", ["answer.md"], ["answer.md", "DIGEST.md"], None, True),
            ("two_copies", ["answer.md"], ["answer.md"],
             ["answer.md", "DIGEST.md", "PLAN.md"], True),
        ]
        for name, files, req, extra, expect_bad in cases:
            it = mk(name, files, req, extra)
            rows = scan(it)
            got_bad = bool(rows and rows[0][1])
            good = (got_bad == expect_bad)
            ok &= good
            print(f"{'PASS' if good else 'FAIL'}  {name:18s} 判 INVALID={got_bad}"
                  f"（期望 {expect_bad}）")
            if not good:
                for p in (rows[0][1] if rows else []):
                    print(f"        | {p[:96]}")
        # 场景 5（反向）：**没有元数据的老 run 不许判 INVALID**，只能算"未核对"。
        # 立此的原因：第一版把 iteration-2 的 16 个老 run 全判成 INVALID，
        # 真正的两个硬问题被埋掉 —— 会让报告被忽略的判定等于没有判定（`D4`）。
        it = base / "no_metadata"
        arm = it / "eval-0" / "with_skill"
        (arm / "run-1" / "outputs").mkdir(parents=True)
        (arm / "run-1" / "outputs" / "answer.md").write_text("x" * 20, encoding="utf-8")
        rows = scan(it)
        hard, soft = (rows[0][1], rows[0][2]) if rows else ([], [])
        good = (not hard) and bool(soft)
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  {'no_metadata':18s} 判 INVALID=False 且 未核对=True"
              f"（实际 hard={bool(hard)} soft={bool(soft)}）")
        # 场景 6（反向）：**不是 eval 的目录不许被当成评测 run**。
        # 立此的原因：第一版没有这个约束，于是 `iteration-3/submissions/` 下 6 个竞赛提交包
        # 被报成"没有 outputs/" —— 6 条误报把 2 条真报埋了。
        it = base / "non_eval_dirs"
        (it / "weights").mkdir(parents=True)
        (it / "weights" / "w.npz").write_text("x" * 10, encoding="utf-8")
        ev = it / "eval-0" / "with_skill"
        (ev / "run-1" / "outputs").mkdir(parents=True)
        it.joinpath("eval-0").joinpath("eval_metadata.json").write_text(
            json.dumps({"required_outputs": ["answer.md"]}, ensure_ascii=False),
            encoding="utf-8")
        (ev / "run-1" / "outputs" / "answer.md").write_text("x" * 20, encoding="utf-8")
        rows = scan(it)
        good = (len(rows) == 1 and not rows[0][1])
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  {'non_eval_dirs':18s} 只扫 eval*（实际扫到 "
              f"{len(rows)} 个 run，其中 INVALID {sum(1 for r in rows if r[1])} 个）")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("-" * 88)
    print("check_run_integrity 自证结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
