#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
r"""claim_repro.py —— **每个"头条数字"都要有一条能跑出它的命令**。

## 它治的是哪一句话

> "我**无法利用** agent 所写代码产出的结果和数据。"

`INDEX.md`（`artifact_index.py`）回答了"这个数字背后的**文件**在哪"，
但它回答不了下一个问题：**"我怎么自己把它跑出来？"**
一个数字如果只有"某个 JSON 里有"这条线索，人还是只能相信 agent 的转述。

本脚本让每个头条数字带一条**可执行的复现命令**与一个**期望子串**，然后真的去跑。
跑不出来 ⇒ 那个数字**不该被引用**。

## 三类声明（**必须分清**，混在一起就会失去意义）

| kind | 含义 | 处理 |
|---|---|---|
| `reproducible` | 有命令能跑出来 | 执行；期望子串不在输出里 ⇒ **FAIL** |
| `external` | 来自**仓库外**且不可复算（榜单分数、官方文档、人工抄录） | **不执行**，报 INFO 并写明来源 |
| `slow` | 可跑但耗时（>2 分钟） | **默认不跑**（`--include-slow` 才跑），报 INFO |

⇒ 把"外部来源"混进"可复算"里，会让人以为所有数字都能自己验证；
   把"慢"混进"快"里，会让人因为怕等而不跑这个脚本。**两者都要分开报。**

## 清单是**显式**的（不是扫描出来的）

与 `artifact_index.py` 的豁免表同一条理由：**一份会过时的启发式比一份需要维护的显式清单更危险**。
清单文件长这样：

    {"claims": [
      {"id": "M-1-AUC", "number": "0.7497", "kind": "reproducible",
       "command": ["python", "T2_unit_composition_audit.py"], "expect": "0.7497",
       "note": "M-1 主口径决策区的 AUC(μ)"},
      {"id": "LB-D", "number": "40.4294", "kind": "external",
       "source": "竞赛榜单人工记录（SUBMISSION-PLAN-convention.md §8.6）",
       "note": "无法在本地复算"}
    ]}

用法：
    python scripts/claim_repro.py --manifest <清单.json> [--cwd <工作区>]
        [--only ID] [--include-slow] [--timeout 180] [--list]
        [--self-test]
    `--cwd` 缺省 = 清单所在目录（清单里的命令按"相对清单"写）。
退出码：0 = 所有被执行的声明都复现；1 = 有 FAIL；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subproc  # noqa: E402,F401  （子进程编码只有这一处定义）

KINDS = ("reproducible", "external", "slow")


def run_claim(c: dict, cwd: Path, timeout: float):
    """返回 (status, detail)。status ∈ {PASS, FAIL, INFO}。"""
    cmdline = c["command"]
    # 显式规则：字符串按空格切（**不支持引号**；路径含空格时请用列表），列表原样使用。
    args = list(cmdline) if isinstance(cmdline, (list, tuple)) else cmdline.split()
    # `{skill}` 占位符 = **本脚本所在的 skill 根目录**。
    #
    # 立此的实测原因（第 40 轮）：把课题工作区从 skill 仓库里搬出去之后，
    # 清单里两条写死的相对路径（`../../collab-lab/scripts/...`）**立刻失效**，
    # 连带 7 条声明 FAIL。⇒ **项目清单不该硬编码 skill 的位置** ——
    # 工作区会搬、skill 会搬，而"skill 在哪"只有 skill 自己知道。
    # 要指向 skill 自己的脚本，就写 `"{skill}/scripts/foo.py"`。
    args = [a.replace("{skill}", str(Path(__file__).resolve().parent.parent)) for a in args]
    if args and args[0] in ("python", "python3"):
        args[0] = sys.executable
    try:
        r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8",
                                "PYTHONUTF8": "1"})
    except subprocess.TimeoutExpired:
        return "FAIL", f"超时（>{timeout:.0f}s）"
    out = (r.stdout or "") + (r.stderr or "")
    # ⚠️ 子串匹配会**误过**：第一次跑真实清单时，声明 "P ∈ [62,383]" 的期望子串写成 "62"，
    #    结果匹配到了另一行里的 "213.6217" —— 数字是子串就容易这样。
    #    ⇒ 需要精确时用 `expect_regex`（仍保留 `expect` 作为简单情形）。
    if c.get("expect_regex"):
        m = re.search(c["expect_regex"], out, re.M)
        if m is None:
            return "FAIL", f"输出里找不到正则 {c['expect_regex']!r}（退出码 {r.returncode}）"
        return "PASS", m.group(0).strip()[:88]
    if "expect" not in c:
        return "FAIL", "清单条目既没有 expect 也没有 expect_regex"
    if c["expect"] not in out:
        return "FAIL", f"输出里找不到期望子串 {c['expect']!r}（退出码 {r.returncode}）"
    line = next((ln.strip() for ln in out.splitlines() if c["expect"] in ln), "")
    return "PASS", line[:88]


def main() -> int:
    ap = argparse.ArgumentParser(description="头条数字的可复现性检查")
    ap.add_argument("--manifest", required=False)
    # `--cwd` 缺省 = **清单自己所在目录**，而不是"我当前站在哪"。
    # 立此的原因（第 28 轮实跑记录）：清单里写的命令是 `T2_unit_composition_audit.py`
    # 这类**相对清单**的名字，而我在工作区根目录执行 ⇒ 9 条声明整片 FAIL
    # （退出码 2、输出为空），看上去像"数字复现不出来"，实际只是**站的目录不对**。
    # 这类误报最坏的地方是：它把"环境问题"伪装成"证据链问题"
    # ⇒ 缺省值必须由清单自身决定，否则每次都得靠人记住 `--cwd`，而"记住"没有东西能校验。
    ap.add_argument("--cwd", default=None,
                    help="执行命令的工作目录；缺省 = 清单文件所在目录")
    ap.add_argument("--only", default=None)
    ap.add_argument("--include-slow", action="store_true")
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return _self_test()
    if not args.manifest:
        ap.print_help()
        return 2
    mp = Path(args.manifest)
    if not mp.exists():
        print(f"FAIL  找不到清单：{mp}")
        return 2
    data = json.loads(mp.read_text(encoding="utf-8-sig"))
    claims = data.get("claims", [])
    # 缺省工作目录 = 清单所在目录（`--cwd` 可覆盖）。
    cwd = Path(args.cwd) if args.cwd else mp.resolve().parent
    if not cwd.is_dir():
        print(f"FAIL  工作目录不存在：{cwd}")
        return 2

    print("=" * 88)
    print(f"头条数字的可复现性：{mp}（{len(claims)} 条声明）")
    print(f"执行工作目录：{cwd}")
    print("=" * 88)
    if args.list:
        print(f"  {'id':16s} {'kind':13s} {'number':>10s}  说明")
        for c in claims:
            print(f"  {c.get('id', '?'):16s} {c.get('kind', '?'):13s} "
                  f"{str(c.get('number', '')):>10s}  {c.get('note', '')[:44]}")
        return 0

    n_fail = n_pass = n_info = 0
    for c in claims:
        cid = c.get("id", "?")
        if args.only and cid != args.only:
            continue
        kind = c.get("kind", "reproducible")
        if kind not in KINDS:
            print(f"FAIL  {cid:16s} 未知 kind={kind!r}（允许 {KINDS}）")
            n_fail += 1
            continue
        if kind == "external":
            print(f"INFO  {cid:16s} {str(c.get('number', '')):>10s}  "
                  f"外部来源，不可复算：{c.get('source', '（未写来源）')[:52]}")
            n_info += 1
            continue
        if kind == "slow" and not args.include_slow:
            print(f"INFO  {cid:16s} {str(c.get('number', '')):>10s}  "
                  f"慢（>2 分钟），默认不跑：{c.get('command', '')[:44]}")
            n_info += 1
            continue
        status, detail = run_claim(c, cwd, args.timeout)
        print(f"{status:5s} {cid:16s} {str(c.get('number', '')):>10s}  {detail}")
        if status == "PASS":
            n_pass += 1
        else:
            n_fail += 1
    print("-" * 88)
    print(f"复现 {n_pass} 条；FAIL {n_fail} 条；不执行（外部/慢）{n_info} 条")
    if n_fail:
        print("⇒ 有数字跑不出来：**在修好之前不要引用它**（或者把它如实改成 external/slow）。")
        return 1
    print("⇒ 所有被执行的声明都复现了。")
    return 0


def _self_test() -> int:
    """三个并排场景：能复现 / 期望子串不在输出里 / 外部来源不执行。"""
    import shutil
    import tempfile
    print("=" * 88)
    print("claim_repro 自证（四场景：可复现 / 复现失败 / 外部来源 / 缺省工作目录跟着清单走）")
    print("=" * 88)
    base = Path(__file__).resolve().parent / "_claim_repro_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    ok = True
    try:
        good = base / "good.json"
        good.write_text(json.dumps({"claims": [
            {"id": "ok", "number": "42", "kind": "reproducible",
             "command": [sys.executable, "-c", "print(42)"], "expect": "42"}]},
            ensure_ascii=False), encoding="utf-8")
        bad = base / "bad.json"
        bad.write_text(json.dumps({"claims": [
            {"id": "no", "number": "43", "kind": "reproducible",
             "command": [sys.executable, "-c", "print(42)"], "expect": "43"}]},
            ensure_ascii=False), encoding="utf-8")
        ext = base / "ext.json"
        ext.write_text(json.dumps({"claims": [
            {"id": "lb", "number": "40.43", "kind": "external",
             "source": "榜单人工记录"}]}, ensure_ascii=False), encoding="utf-8")
        for tag, f, want in (("reproducible_ok", good, 0),
                             ("reproducible_fail", bad, 1),
                             ("external_only", ext, 0)):
            r = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                "--manifest", str(f)],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace")
            got = (r.returncode == want)
            print(f"{'PASS' if got else 'FAIL'}  {tag:20s} 退出码 {r.returncode}"
                  f"（期望 {want}）")
            ok &= got
        # 场景 4：**缺省工作目录必须跟着清单走**。
        # 清单在 `sub/` 下、命令写成相对清单的 `probe.py`，而进程站在**别处**。
        # 缺省若还是 "."，这条会以退出码 2 假失败（找不到文件）—— 正是第 28 轮实跑踩到的坑。
        sub = base / "sub"
        sub.mkdir()
        (sub / "probe.py").write_text("print(7)\n", encoding="utf-8")
        local = sub / "local.json"
        local.write_text(json.dumps({"claims": [
            {"id": "rel", "number": "7", "kind": "reproducible",
             "command": [sys.executable, "probe.py"], "expect": "7"}]},
            ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                            "--manifest", str(local)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(base))
        got = (r.returncode == 0)
        print(f"{'PASS' if got else 'FAIL'}  {'cwd_follows_manifest':20s} 退出码 "
              f"{r.returncode}（期望 0；站在 {base.name}/ 下跑 sub/ 里的清单）")
        if not got:
            for ln in (r.stdout or "").splitlines():
                if ln.startswith(("FAIL", "INFO")):
                    print(f"        | {ln.strip()[:92]}")
        ok &= got
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("-" * 88)
    print("claim_repro 自证结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
