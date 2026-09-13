#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
r"""eval_structural_assertions.py —— 用**机械断言**给评测臂打分，并把两类度量分开报。

## 它治的是哪句话

> "我**无法从一次与 agent 的协同工作中获得什么经验**。"

在评测这一层，这句的形态是：**成绩单上的差值不知道在量什么。**

第 32 轮复盘 `iteration-2` 时发现两件事：
1. `eval-1` 的 7 条断言**两臂都满分**（对照臂没有 skill 也过了）⇒ 它不区分，贡献 0；
2. 而 `iteration-2/benchmark.md` 自己早就写过一句警告：
   "**量具偏向**：eval-2/3/7 的多数期望检查的是 skill 自带的栏位与节序，
   无 skill 一侧结构性难以通过。真实的'能力增量'小于表观差值。"
   —— 那句话是**散文**，没有任何东西强制它被遵守。

⇒ 本脚本把那句话变成**机制**：每条断言必须带 `kind`。

| kind | 量的是什么 | 能不能当"skill 的贡献"读 |
|---|---|---|
| `convention`（约定） | **skill 的约定有没有被照做** —— 字段在不在、校验器过不过、**具名小节在不在** | **不能。** 它**必然**偏向有 skill 的那一臂 —— 对照臂不知道这些约定，不是它做得差 |
| `behavior`（行为） | **与 skill 无关的行为约束**（例如用户说"先别跑"，就是不许有训练代码） | 能。这类断言两臂都适用 |

**硬规则**：报告**分别汇总两类**，并显式打印"约定差值不可读作能力提升"。
把两类混成一个百分比，就是 `iteration-2` 那张成绩单犯的错。

> ⚠️ **本轮自己的教训（写在这里，因为它太容易再犯）**：
> 第一版把"「最小可检测效应」节里出现数字"和"「绝不能声称」至少 3 条"标成了 `capability`。
> 跑下来对照臂这两条全 FAIL —— 但**那两条要求的是 skill 的具名小节**，
> 对照臂用的是另一套同样扎实的写法（τ 无关的 `(m,k)` 盈利条件表），内容并不差。
> ⇒ 它们是**披着能力外衣的约定断言**。真相是：**机械断言几乎总会变成约定断言** ——
> 凡是"能不能自动数出来"，数的都是**形状**，不是**对不对**。
> 这类断言仍然有用（它们测"约定有没有落地"），但**不能拿来宣称能力增量**。

## 用法

    python scripts/eval_structural_assertions.py <outputs 目录> --eval protocol-prereg
        [--json]
    python scripts/eval_structural_assertions.py --self-test
退出码：0 = 全部断言通过；1 = 有失败；2 = 用法错误。

## 为什么断言用脚本而不是"看一眼"

skill-creator 方法论里那句"凡能程序化检查的断言就写脚本，不要用眼睛看"——
脚本更快、更可靠、而且**下一轮能重复用**。
本脚本的一致性断言直接**复用 skill 自己的校验器**（`check_collab_artifacts.py`），
于是"协议块是否符合本 skill 的规范"这件事**只有一处定义**。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import subproc  # noqa: E402,F401  （输出兜底）
CHECKER = HERE / "check_collab_artifacts.py"

# 训练代码痕迹：用来核对"用户说了先别跑"有没有被遵守
TRAIN_PAT = re.compile(
    r"torch\.|sklearn|tensorflow|\.backward\(|optim\.|DataLoader|"
    r"model\.fit\(|fit\(X|epochs?\s*=|for\s+epoch\s+in", re.I)

PROTO_GLOB = "PROTOCOL-*.md"

NUM_RE = re.compile(r"\d+\.\d+")
# 行内的**参数标注**（`k=8` / `τ=0.05` / `P=61`）要先剥掉，否则会被当成"引用的数"误报。
PARAM_RE = re.compile(r"[A-Za-zτ]\s*=\s*[\d.]+")


def quoted_numbers_in_cited_column(text: str, out: Path):
    """块里引用的数字，必须能在它**点名的那一列**里找到。

    立此的实测原因（第 34 轮，**盲评判者发现的，不是我自己看出来的**）：
    `PROTOCOL-P-BOILER-020.md` 的最小可检测效应表第 ② 行写
    「一个正例切片的分数收益 **0.92 分**（k=8, τ=0.05, P=61）；**0.44 分**（k=3）…
    出处 `one_tp_gain`」——
    而它自己的 `evidence/noise-floor.csv` 里，`one_tp_gain` 那两格是 **1.18 / 1.50**；
    **0.92 / 0.44 是 `one_fp_cost` 那两格。**
    这不是排版问题：它外溢成「杠杆上界 ≈2.9 分 < 噪声 p95 3.42 分」，
    而用正确值 1.18 算是 **≈3.5 分 > 3.42** ⇒ **那条结论会翻转**。

    ⇒ 这一类（**引对了文件、引错了列**）正是 `claim_repro` 管的形态
    （"引用一个脚本作为证据时，那个脚本必须真的打印那句话"），
    但它发生在**草拟协议块**的时候 —— 那一刻 `claim_repro` 不跑。
    本条断言就是把它补到草拟阶段。
    """
    csvs = [p for p in out.rglob("*.csv")]
    if not csvs:
        return [], 0
    cols = {}
    for c in csvs:
        try:
            head = c.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        except Exception:
            continue
        cols[c] = [h.strip() for h in head.split(",") if h.strip()]
    problems, checked = [], 0
    for ln in text.splitlines():
        cited = {col for hs in cols.values() for col in hs
                 if len(col) > 3 and col in ln}
        if not cited:
            continue
        nums = NUM_RE.findall(PARAM_RE.sub(" ", ln))
        if not nums:
            continue
        for col in cited:
            vals = []
            for c, hs in cols.items():
                if col not in hs:
                    continue
                i = hs.index(col)
                for row in c.read_text(encoding="utf-8",
                                       errors="replace").splitlines()[1:]:
                    parts = row.split(",")
                    if i < len(parts):
                        try:
                            vals.append(float(parts[i]))
                        except ValueError:
                            pass
            for n in nums:
                checked += 1
                if not any(abs(v - float(n)) < 0.005 for v in vals):
                    problems.append((col, n))
    return problems, checked


def _proto_files(out: Path):
    return sorted(out.rglob(PROTO_GLOB))


def _read_all(out: Path) -> str:
    parts = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.suffix.lower() in (".md", ".txt", ".py", ".json", ".csv"):
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def assert_protocol_prereg(out: Path):
    """返回 [(id, kind, 描述, 通过?, 证据), ...]。"""
    res = []
    protos = _proto_files(out)

    # ---- convention（约定：字段/具名小节/校验器） ----
    res.append(("C1-has-protocol", "convention",
                "产出里存在协议块文件（`PROTOCOL-*.md`）",
                bool(protos), f"找到 {len(protos)} 个：{[p.name for p in protos]}"))

    ok2, ev2 = False, "没有协议块可校验"
    if protos:
        r = subproc.run_text([sys.executable, str(CHECKER), "--protocol",
                              str(protos[0])])
        ok2 = (r.returncode == 0)
        fails = [ln.strip() for ln in r.stdout.splitlines()
                 if ln.strip().startswith("x ")]
        ev2 = ("通过 skill 自带校验器（12 个必需节 + 三件套头 + 判据优先级/第 3 档分流）"
               if ok2 else f"校验器退出 {r.returncode}，报 {len(fails)} 条：{fails[:4]}")
    res.append(("C2-validator-pass", "convention",
                "该协议块通过 skill 自带校验器 `--protocol`（退出码 0）", ok2, ev2))

    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in protos)
    has_res = bool(re.search(r"^稀缺资源[:：]", text, re.M))
    has_lev = bool(re.search(r"^杠杆上界[:：]", text, re.M))
    res.append(("C3-resource-lever-pair", "convention",
                "`稀缺资源:` 与 `杠杆上界:` 两行成对出现（声明了稀缺资源就必须算上界）",
                has_res and has_lev,
                f"稀缺资源={has_res}、杠杆上界={has_lev}（写「无」也算有该行）"))

    # ⚠️ C4 **必须与 skill 自己的规则一样严，不能更严**。
    #    第一版写成"必须存在 `判据优先级:` 且点名 ≥2 档"，于是**出厂样张被判 FAIL** ——
    #    而校验器对同一份样张是 PASS 的。查下来：skill 的规则是
    #    "**多档**判据（≥2 档）必须写 `判据优先级:`"，样张是单档块，本来就不需要那一行。
    #    ⇒ 用自己的话把规则重写一遍，就会写出一个比原规则更严的版本，
    #      然后拿它去扣分 —— 这正是"断言与规则不一致"的形态。
    #      正确做法：**条件化**，与规则同形。
    pri = bool(re.search(r"^判据优先级[:：]", text, re.M))
    tiers = len(set(re.findall(r"\bO([1-9])\b", text)))
    if tiers >= 2:
        c4_ok = pri
        c4_ev = f"点名 {tiers} 档 ⇒ 必须有 `判据优先级:`；实际={pri}"
    else:
        c4_ok = True
        c4_ev = f"只点名 {tiers} 档 ⇒ 按 skill 规则**不要求** `判据优先级:`（该行={pri}）"
    res.append(("C4-tier-priority", "convention",
                "多档判据（≥2 档）必须写 `判据优先级:`（与 skill 规则同形，不更严）",
                c4_ok, c4_ev))

    allt = _read_all(out)
    hit = TRAIN_PAT.search(allt)
    # ---- convention（续）：用具名小节承载的内容 ----
    # ⚠️ 这两条**曾经被我标成 capability**，跑出来对照臂全 FAIL 才发现标错了：
    #    它们要求的是 **skill 的具名小节**（`最小可检测效应` / `绝不能声称`），
    #    而对照臂用另一套同样扎实的写法表达了同样的内容 ⇒ 这是约定，不是能力。
    mde = re.search(r"最小可检测效应(.{0,600})", text, re.S)
    mde_num = bool(mde and re.search(r"\d+\.\d+|\d+\s*分", mde.group(1)))
    # ⚠️ 这两条**曾经被我标成 capability**，跑出来对照臂全 FAIL 才发现标错了：
    #    它们要求的是 **skill 的具名小节**（`最小可检测效应` / `绝不能声称`），
    #    而对照臂用另一套同样扎实的写法表达了同样的内容 ⇒ 这是约定，不是能力。
    allt = _read_all(out)
    hit = TRAIN_PAT.search(allt)
    res.append(("K2-mde-section-numbered", "convention",
                "有 `最小可检测效应` 具名小节，且节里出现具体数字（不是形容词）",
                mde_num, "该节含数字" if mde_num else "该节缺失或没有数字"))

    can = re.search(r"绝不能声称(.{0,1200}?)(?=\n##|\Z)", text, re.S)
    n_can = len(re.findall(r"^\s*[-*]\s+", can.group(1), re.M)) if can else 0
    res.append(("K3-cannot-claim-section", "convention",
                "有 `绝不能声称` 具名小节，且至少 3 条",
                n_can >= 3, f"数到 {n_can} 条"))

    # ---- behavior（行为约束：与 skill 无关，两臂都适用）----
    res.append(("B1-no-training-code", "behavior",
                "没有生成训练代码（用户明确说「先别跑」—— 这条与 skill 无关）",
                hit is None,
                "全文扫 torch/sklearn/backward/epoch… 零命中"
                if hit is None else f"命中 {hit.group(0)!r}"))

    probs, n_checked = quoted_numbers_in_cited_column(text, out)
    if n_checked == 0:
        b2_ev = ("**无从核对**（产出里没有被点名的 CSV 列）—— 本条不构成通过证据")
    elif probs:
        b2_ev = f"以下数字**不在**它点名的那一列里：{probs[:4]}"
    else:
        b2_ev = f"核对 {n_checked} 个数，全部落在被引列里"
    res.append(("B2-quoted-numbers-in-cited-column", "behavior",
                "块里引用的数字必须能在它**点名的证据列**里找到"
                "（引对文件、引错列，会让整条结论翻转）",
                not probs, b2_ev))

    return res


REGISTRY = {"protocol-prereg": assert_protocol_prereg}


def main() -> int:
    ap = argparse.ArgumentParser(description="用机械断言给评测臂打分（一致性/能力分开）")
    ap.add_argument("outputs", nargs="?", help="某个 run 的 outputs 目录")
    ap.add_argument("--eval", dest="which", default="protocol-prereg",
                    choices=sorted(REGISTRY))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    if not args.outputs:
        ap.print_help()
        return 2
    out = Path(args.outputs)
    if not out.is_dir():
        print(f"FAIL  outputs 目录不存在：{out}")
        return 2
    res = REGISTRY[args.which](out)
    if args.json:
        print(json.dumps({"outputs": str(out), "eval": args.which,
                          "assertions": [
                              {"id": i, "kind": k, "text": t, "passed": bool(p),
                               "evidence": e} for i, k, t, p, e in res]},
                         ensure_ascii=False, indent=1))
        return 0 if all(p for _, _, _, p, _ in res) else 1

    print("=" * 92)
    print(f"机械断言：{out}")
    print("=" * 92)
    for kind, label in (("convention", "约定（skill 的约定有没有被照做）"),
                        ("behavior", "行为（与 skill 无关的约束）")):
        sub = [r for r in res if r[1] == kind]
        n = sum(1 for r in sub if r[3])
        print(f"\n  【{label}】{n}/{len(sub)}")
        for i, _, t, p, e in sub:
            print(f"    {'PASS' if p else 'FAIL'}  {i:24s} {t}")
            print(f"          · {e}")
    conv = [r for r in res if r[1] == "convention"]
    beh = [r for r in res if r[1] == "behavior"]
    vac = [r for r in res if r[3] and "无从核对" in r[4]]
    print("\n" + "-" * 92)
    print(f"  约定 {sum(1 for r in conv if r[3])}/{len(conv)}；"
          f"行为 {sum(1 for r in beh if r[3])}/{len(beh)}")
    if vac:
        print(f"  ⚠️ 其中 {len(vac)} 条是**空过**（没有可核对的对象）："
              f"{[r[0] for r in vac]} —— 空过**不构成通过证据**，"
              "别把它算成「这份产出更干净」。")
    print("  ⚠️ **约定差值不可读作能力提升**：约定断言必然偏向有 skill 的那一臂 ——"
          "对照臂不知道这些约定，不是它做得差。")
    print("     只有「行为」那几行在两臂间可比。（`iteration-2/benchmark.md` 写过这句话，"
          "本轮把它做成了机制。）")
    print("  ⚠️ 更强的一条（本轮自证后改的）：**机械断言几乎总会变成约定断言** ——"
          "凡能自动数出来的都是**形状**，不是**对不对**。")
    return 0 if all(p for _, _, _, p, _ in res) else 1


def _self_test() -> int:
    """四个并排场景：好块 / 没块 / 缺头三件套 / 混进训练代码。"""
    import shutil
    print("=" * 92)
    print("eval_structural_assertions 自证（四个并排场景）")
    print("=" * 92)
    base = HERE / "_eval_assert_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    sample = HERE.parent / "assets" / "samples" / "PROTOCOL-sample-001.md"
    ok = True
    try:
        good = sample.read_text(encoding="utf-8")

        def mk(name, text, extra=None):
            d = base / name
            d.mkdir(parents=True)
            if text is not None:
                (d / "PROTOCOL-P-TEST-001.md").write_text(text, encoding="utf-8")
            else:
                (d / "answer.md").write_text("只有答复，没有协议块", encoding="utf-8")
            if extra:
                (d / "run.py").write_text(extra, encoding="utf-8")
            return d

        cases = [
            ("good", good, None, True),
            ("no_protocol", None, None, False),
            # 去掉三件套头 ⇒ C2/C3 必须失败（`预注册:`/`稀缺资源:`/`杠杆上界:`）
            ("no_header", re.sub(r"^(预注册|稀缺资源|杠杆上界)[:：].*$", "",
                                 good, flags=re.M), None, False),
            # ⚠️ **只让 C2 一条失败**的场景：删掉「停止规则」小节。
            #    为什么必须只让一条失败：一个场景里放两条失败路径，等于两条都没被隔离
            #    （第 32 轮 `empty` 场景踩过；见 `LESSONS-general` B48 附带）。
            #    没有这一条，"委托给校验器"这一步被改成恒真时，其它断言会兜住，变异抓不到。
            ("only_c2", re.sub(r"^##+\s*停止规则.*$", "", good, flags=re.M), None, False),
            ("training_code", good, "import torch\nfor epoch in range(3): pass\n", False),
        ]
        for name, text, extra, expect_all in cases:
            d = mk(name, text, extra)
            res = assert_protocol_prereg(d)
            allpass = all(p for _, _, _, p, _ in res)
            good_ = (allpass == expect_all)
            ok &= good_
            n = sum(1 for r in res if r[3])
            print(f"{'PASS' if good_ else 'FAIL'}  {name:15s} 全部通过={allpass}"
                  f"（期望 {expect_all}）  {n}/{len(res)}"
                  f"  失败项={[r[0] for r in res if not r[3]]}")
            # **报告形状的不变量**：两类必须同时存在且都非空。
            # 立此的原因：把两类混成一个百分数，正是 `iteration-2` 成绩单犯的错 ——
            # 它让"约定差值"读起来像"能力提升"。守这个形状的不是某条断言，而是这一条。
            kinds = {r[1] for r in res}
            shape_ok = (kinds == {"convention", "behavior"}
                        and any(r[1] == "behavior" for r in res)
                        and any(r[1] == "convention" for r in res))
            if name == "good" and not shape_ok:
                print(f"FAIL  报告形状：两类必须同时存在且都非空，实际 kinds={kinds}")
                ok = False
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("-" * 92)
    print("eval_structural_assertions 自证结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
