#!/usr/bin/env -S python -u
# -*- coding: utf-8 -*-
r"""make_blind_pair.py —— 造一对**去标识**的盲评副本，并**证明它真的盲**。

## 它治的是哪一句话

> "我**无法利用** agent 所写代码产出的结果和数据。"

在这一层，它的形态是：**盲评不盲。**
第 34 轮实测：`eval-1/without_skill/answer.md:28` 里写着自己的产出路径
（`…\eval-1\without_skill\outputs`）—— 只要把那个目录原样交给评判者，
**它一眼就知道哪一份是"没有 skill 的那一份"**。
（同一次里 skill 臂零泄漏 ⇒ 泄漏是**单向**的，方向上让对照臂显得更可疑，结论同样被污染。）

而且这件事**不能靠人记着**：泄漏可能出现在任何一份产出的任何一行里，
包括 agent 自己写的"访问范围声明"里 —— 那种声明**越多越容易泄漏**，
于是"越严谨的产出越容易被认出身份"，这正好与评测要测的东西反向。

## 它做四件事

1. 把两份产出复制到 `<out>/A` 与 `<out>/B`；
2. 把内容里出现的臂名（任何 `--token`，含自动加上的目录名）换成中性词，**逐条记录**；
3. 随机分配 A/B（`--seed` 可复现）；
4. **泄漏自检**：写完后**再扫一遍**，任何原有 token 还在 ⇒ 报 `FAIL` 并退出 1。

## 两条硬规则（做成检查，不是纪律）

- **映射文件不许写在盲评目录里面**（写了就等于把答案放在卷子里）⇒ 直接拒绝；
- **映射文件本身也要过泄漏检查的反面检查**：它必须**不在** `<out>` 之下。

用法：
    python scripts/make_blind_pair.py --a <臂1 outputs> --b <臂2 outputs> \
        --out <盲评目录> --mapping <映射.json> [--seed 3405] \
        [--token with_skill] [--token without_skill]
    python scripts/make_blind_pair.py --self-test
退出码：0 = 盲评对已生成且**证实无泄漏**；1 = 有泄漏或映射位置非法；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subproc  # noqa: E402,F401

TEXT_EXT = (".md", ".txt", ".py", ".json", ".csv", ".html", ".yaml", ".yml")


def _tokens_from(a: Path, b: Path, extra):
    """默认 token = 两个臂目录各自的**名字**（`with_skill` / `without_skill` 这类）。"""
    toks = set(extra or [])
    for p in (a, b):
        for anc in [p.name] + [q.name for q in p.parents[:2]]:
            if anc and anc not in (".", "outputs", "run-1"):
                toks.add(anc)
    return sorted(t for t in toks if len(t) > 3)


def _scan_leak(out: Path, toks) -> list:
    """扫**所有**文件（不只是文本）—— 按字节找 token。

    ⚠️ 第一版只扫 `TEXT_EXT`。那意味着一个 `.bin`/`.npz`/`.zip` 里带着臂名时，
    **既不会被替换、也不会被报出** —— 而产出里出现二进制是常态（权重、缓存、提交包）。
    二进制不能安全地改，所以这里的正确行为不是"改它"，而是**拒绝放行**：
    让调用者自己决定改名/剔除该文件。
    """
    hits = []
    for p in sorted(out.rglob("*")):
        if not p.is_file():
            continue
        raw = p.read_bytes()
        for tok in toks:
            if tok.encode("utf-8") in raw:
                kind = "" if p.suffix.lower() in TEXT_EXT else "（**非文本文件**，不能安全改写）"
                hits.append(f"{p.relative_to(out)} 里仍有 {tok!r}{kind}")
    return hits


WORD_RE = __import__("re").compile(r"[A-Za-z_][A-Za-z0-9_]{7,}")


def fingerprints(a: Path, b: Path, top: int = 20):
    """**只在一边出现的词** —— 它们是"身份指纹"的候选。

    ⚠️ 为什么必须有这一步：泄漏自检**只能查你声明过的 token**。
    自证场景当场证明了这一点 —— 一份写着 `UNKNOWN_MARK_9` 的产出
    （token 表里没有它）**照样通过**了泄漏检查。
    ⇒ 声明是**有界**的，所以再给一份**无界**的复核线索：
    把"只在一侧出现的长词"列出来让人扫一眼。
    这不是"检查通过"，是"**把该看的东西端到你面前**"。
    """
    def words(p: Path):
        s = set()
        for f in sorted(p.rglob("*")):
            if f.is_file() and f.suffix.lower() in TEXT_EXT:
                s |= set(WORD_RE.findall(
                    f.read_text(encoding="utf-8", errors="replace")))
        return s
    wa, wb = words(a), words(b)
    only_a = sorted(wa - wb, key=lambda x: (-len(x), x))[:top]
    only_b = sorted(wb - wa, key=lambda x: (-len(x), x))[:top]
    return only_a, only_b


def build(a: Path, b: Path, out: Path, mapping: Path, seed: int, extra_tokens):
    if mapping.resolve().is_relative_to(out.resolve()):
        return None, [f"映射文件写在盲评目录里了（{mapping}）—— "
                      "那等于把答案放进卷子；请换到 <out> 之外"]
    toks = _tokens_from(a, b, extra_tokens)
    arms = ["A", "B"]
    random.Random(seed).shuffle(arms)
    assign = dict(zip(arms, [a, b]))
    if out.exists():
        shutil.rmtree(out)
    changes = []
    for lab, src in assign.items():
        dst = out / lab
        dst.mkdir(parents=True)
        for p in sorted(src.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(src)
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            if p.suffix.lower() in TEXT_EXT:
                t = p.read_text(encoding="utf-8", errors="replace")
                for tok in toks:
                    if tok in t:
                        changes.append({"label": lab, "file": str(rel),
                                        "replaced": tok, "with": "<ARM>",
                                        "count": t.count(tok)})
                        t = t.replace(tok, "<ARM>")
                (dst / rel).write_text(t, encoding="utf-8")
            else:
                shutil.copy2(p, dst / rel)
    leaks = _scan_leak(out, toks)
    mapping.parent.mkdir(parents=True, exist_ok=True)
    mapping.write_text(json.dumps(
        {"assignment": {k: str(v) for k, v in assign.items()},
         "seed": seed, "tokens": toks, "sanitization": changes,
         "leak_check": "FAIL" if leaks else "PASS",
         "note": "本文件故意放在盲评目录之外；评判者只应拿到 <out>/A 与 <out>/B。"},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return assign, leaks


def main() -> int:
    ap = argparse.ArgumentParser(description="造一对去标识的盲评副本并证明它真的盲")
    ap.add_argument("--a")
    ap.add_argument("--b")
    ap.add_argument("--out")
    ap.add_argument("--mapping")
    ap.add_argument("--seed", type=int, default=3405)
    ap.add_argument("--token", action="append", default=[])
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    if not all([args.a, args.b, args.out, args.mapping]):
        ap.print_help()
        return 2
    a, b = Path(args.a), Path(args.b)
    for p in (a, b):
        if not p.is_dir():
            print(f"FAIL  臂目录不存在：{p}")
            return 2
    assign, leaks = build(a, b, Path(args.out), Path(args.mapping),
                          args.seed, args.token)
    if assign is None:
        for x in leaks:
            print(f"FAIL  {x}")
        return 1
    print("=" * 88)
    print(f"盲评对已生成：{args.out}")
    for lab, src in assign.items():
        n = sum(1 for _ in (Path(args.out) / lab).rglob("*") if _.is_file())
        print(f"  {lab}  <-  {src}   （{n} 个文件）")
    print(f"  映射：{args.mapping}（在盲评目录之外）")
    # ⚠️ 指纹必须算在**去标识之后的那两份**上，而且按**盲标 A/B** 标注。
    #    第一版算在**原始臂**上、却用"只在 A 侧 / 只在 B 侧"这种盲标说法印出来 ——
    #    结果是：① 已经替换掉的 token（`with_skill` / `without_skill`）又出现在报告里；
    #    ② "A 侧"实际指命令行 `--a`，与盲标 A **不是同一个东西**，看的人会对错号。
    #    ⇒ 复核线索只有算在"评判者真正拿到的那两份"上才有意义。
    only_a, only_b = fingerprints(Path(args.out) / "A", Path(args.out) / "B")
    print("\n■ 身份指纹复核（**去标识之后**仍只在一侧出现的长词 —— 请逐条确认是否暴露身份）")
    print(f"  A 侧：{only_a[:12]}")
    print(f"  B 侧：{only_b[:12]}")
    print("  ⚠️ 泄漏自检**只能查你声明过的 token** —— 未声明的标识查不出来，"
          "所以这一节不是可选装饰。")
    print("-" * 88)
    if leaks:
        print(f"⇒ **泄漏自检未通过**：{len(leaks)} 处")
        for x in leaks:
            print(f"   · {x}")
        print("   → 盲评不许开始：先补 `--token` 或改产出，再重跑。")
        return 1
    print("⇒ 泄漏自检通过：盲评目录里已找不到任何臂标识。")
    return 0


def _self_test() -> int:
    """五个并排场景：干净对 / 有泄漏 / 映射写在里面（必须拒绝）/ 同种子可复现 / 换种子会交换。"""
    print("=" * 88)
    print("make_blind_pair 自证（五个并排场景）")
    print("=" * 88)
    base = Path(__file__).resolve().parent / "_blind_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    ok = True
    try:
        arm1 = base / "eval-0" / "with_skill" / "outputs"
        arm2 = base / "eval-0" / "without_skill" / "outputs"
        for d, txt in ((arm1, "答案，路径 experiment/x/with_skill/outputs"),
                       (arm2, "答案，没有任何标识")):
            d.mkdir(parents=True)
            (d / "answer.md").write_text(txt, encoding="utf-8")

        # 1 干净对：默认 token 取自目录名 ⇒ 泄漏必须被清掉
        assign, leaks = build(arm1, arm2, base / "b1", base / "m1.json", 3405, [])
        good = (not leaks)
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  干净对：泄漏={leaks}  分配={assign}")

        # 2 未声明的标识：**泄漏自检查不出来**（它只查声明过的 token）——
        #   这一条**故意断言"查不出来"**，因为那是事实；同时断言**指纹复核能把它端出来**。
        #   （第一版把这条写成"必须报出泄漏"，于是自证 FAIL —— 那个 FAIL 是对的：
        #     它说明"声明式检查"天生有界。把边界写成断言，比假装没有边界好。）
        (arm2 / "answer.md").write_text("答案 UNKNOWN_MARK_9", encoding="utf-8")
        assign, leaks = build(arm1, arm2, base / "b3", base / "m3.json", 3405, [])
        # 指纹必须算在**去标识之后**的副本上（与 main() 一致）
        only_a, only_b = fingerprints(base / "b3" / "A", base / "b3" / "B")
        good = (not leaks) and any("UNKNOWN_MARK_9" in x for x in (only_a + only_b))
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  未声明的标识：泄漏自检={leaks}（应为空），"
              f"指纹复核命中={any('UNKNOWN_MARK_9' in x for x in (only_a + only_b))}")

        # 3 非文本文件里带着臂名 ⇒ 泄漏扫描**必须报出**（不能安全改写，故只报不放行）。
        #   立此的原因：第一版的扫描只覆盖 `TEXT_EXT` —— 产出现实里常有二进制
        #   （权重 npz、缓存、提交包），那里面的臂名既不会被替换也不会被报出。
        (arm2 / "cache.dat").write_bytes(b"\x00\x01with_skill\x02\x03")
        assign, leaks = build(arm1, arm2, base / "b3b", base / "m3b.json", 3405, [])
        good = any("非文本" in x for x in leaks)
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  非文本泄漏必须报出：leaks={leaks}")
        (arm2 / "cache.dat").unlink()

        # 4 映射写在盲评目录里 ⇒ 必须拒绝
        assign, errs = build(arm1, arm2, base / "b4", base / "b4" / "map.json",
                             3405, [])
        good = (assign is None and bool(errs))
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  映射写在里面必须被拒：{errs}")

        # 4/5 同种子可复现、换种子会交换
        a4, _ = build(arm1, arm2, base / "b5", base / "m5.json", 7, [])
        a5, _ = build(arm1, arm2, base / "b6", base / "m6.json", 7, [])
        a6, _ = build(arm1, arm2, base / "b7", base / "m7.json", 8, [])
        good = (a4 == a5)
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  同种子可复现：{a4} vs {a5}")
        good = (a4 != a6)
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  换种子会换分配：seed7={a4} seed8={a6}")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("-" * 88)
    print("make_blind_pair 自证结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
