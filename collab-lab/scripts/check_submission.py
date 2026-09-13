#!/usr/bin/env -S python -u
# -*- coding: utf-8 -*-
r"""check_submission.py —— **花额度之前，先机械核对提交包。**

## 它治的是哪一句话

> "我**无法利用** agent 所写代码产出的结果和数据。"

在这一层，它的形态最贵：**提交是不可逆的，而"包对不对"此前只靠一次临时自查。**
额度是这个课题里唯一的稀缺资源（`杠杆上界` 就是为它立的字段），
可"包里到底是什么"却**没有任何常驻机制**在核对 ——
一份写坏了的 CSV（列错位、片数不对、ID 对不上测试集）会**照样被传上去**。

实测（第 37 轮，就在写本脚本时）：我用一段顺手写的 inline Python 读自己的
`result.csv`，因为编码取错，**列整体错位**，于是脚本报出"判 1 的片数 0、取值集合是 510 个 test ID"
—— 一个**完全伪造的结论**。这正说明：**"我自己看一眼"不构成核对。**

## 它核对什么（每一条都是"传上去就改不回来"的事）

| # | 检查 | 为什么 |
|---|---|---|
| 1 | CSV 能被解析，且**表头就是官方那三列** | 列名错 ⇒ 平台可能直接拒收或按错列读 |
| 2 | 行数 = 测试切片数 + 1（表头） | 少一行就是漏交，多一行就是多余 |
| 3 | 判 1 的片数 **恰好等于**声明的 k | k 是提交策略的核心参数，写错等于换了策略 |
| 4 | 取值集合 ⊆ {0, 1} | 出现 `0.0` / `True` / 空值都不行 |
| 5 | 序号是 1..N 连续且无重复 | 平台按序号对齐时错位会静默毁掉整份提交 |
| 6 | 切片 ID **与官方测试集逐一对应**（给了 `--test-dir` 才查） | ID 拼错/漏片是最隐蔽的错法 |
| 7 | `result.zip` 里的 CSV 与磁盘上的**逐字节一致** | 打包后又改了 csv 是很常见的事故 |
| 8 | 若给了 `--score-npz` 与 `--score-key`：被判 1 的片 **正是分数最高的 k 片** | 保证"包里这份排序"与"我报告的那个分数"是同一个对象 |
| 9 | 给了 `--code-zip/--code-dir` 时：**代码包**结构、README 命令唯一、依赖带版本、`required` 参数都在命令里 | 见下 |

## 代码包那一半（`--code-zip` / `--code-dir`）：第 41 轮补的

上面 1–8 条有一条共同的盲区：**它们全都不打开代码包**。于是恰恰是最不可逆的那一类错
——"交上去的代码复现不出交上去的结果"（**取消资格**那一档）——
成了唯一没有任何常驻机制在核对的错。第 41 轮一次踩了三份（两份已经交出去了）：

那些包里的 README 运行命令**是从别的包复制来的**，`predict.py` 的默认参数也是复制的。
后果按 README 复现出来的是**别人那份结果**：一份交上去 11 个正类、复现成 34 个；
另一份交上去 150 个、复现成 34 个（差 184 行）。三份的入口脚本**静态看一条毛病都没有**
（它自己的用法注释是对的），只有真跑一遍才看得出来。于是本脚本把这件事拆成两半：

- **能机械化的**（这里做，不需要数据）：结构、README 命令唯一、依赖带版本、`required` 参数齐全；
- **不能机械化的**（要真数据才能跑）：交给 `check_package_repro.py`，
  它按 README 原文跑一遍、与提交结果逐行比，并留下 `repro-check.json`。

本脚本对这一半的要求是：**记录必须在、必须是 PASS、且必须与当前这份 csv 对得上**
（`submitted_sha256` 对不上 ⇒ 记录过期 ⇒ FAIL）。记录不能让谁"证明"什么，
但它让"没跑过"这件事**无法保持沉默**，也让"改了 csv 忘了重跑"当场暴露。

用法：
    python scripts/check_submission.py --csv result.csv [--zip result.zip] \
        --expect-pos 150 [--test-dir <官方 test 目录>] \
        [--score-npz <npz> --score-key sG] \
        [--code-zip submission_code.zip | --code-dir code/]
    python scripts/check_submission.py --self-test
退出码：0 = 全部通过（可以提交）；1 = 有 FAIL（**不许提交**）；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subproc  # noqa: E402,F401
import tabular  # noqa: E402  （列识别只定义一处：见该模块"为什么要有这个模块"）
import check_package_repro as cpr  # noqa: E402  （入口/README 的解析只定义一处）

# ⚠️ 这里**不再**写死任何课题的列名。原先写的是 `("切片 ID", …, "故障判断", …)` ——
# 换一个课题、换一种语言就一条都认不出来，而"认错列"的后果是**静默算错**（`B55` 实测过）。
# 现在按内容认（唯一一个取值只有 0/1 的列），并且**认不出来就要求显式指定**，不许猜。


def _ver_constrained(line: str) -> bool:
    """依赖行里有没有版本约束。

    兼容三种写法：`numpy==2.4.6` / `numpy>=2.0` / poetry 的 `numpy = "^2.0"`、`"~2.0"`。
    """
    return any(op in line for op in ("==", ">=", "<=", "~=", ">", "<", "^", "~"))


def check_code_package(pkg: Path, csv_path: Path) -> tuple[list, list, dict]:
    """代码包那一半：结构 + README 命令唯一 + 依赖带版本 + 复现记录对得上。

    这里**不跑**代码（跑不了：没有数据）。跑的那一半见 `check_package_repro.py`，
    它留下的 `repro-check.json` 在本函数里被核。⇒ 见模块 docstring 的"代码包那一半"。
    """
    fails, notes, stats = [], [], {"code_pkg": str(pkg)}
    if not pkg.exists():
        return [f"找不到代码包：{pkg}"], notes, stats
    root, tmp = cpr.load_package(pkg)
    try:
        entry, all_py = cpr.find_entry(root)
        stats["entry"] = entry
        stats["py_count"] = len(all_py)
        if entry is None:
            fails.append(f"代码包里找不到唯一的入口脚本（.py：{all_py}）"
                         " —— 复现者不知道该跑哪个")
            return fails, notes, stats
        readme = cpr.find_readme(root)
        if readme is None:
            fails.append("代码包里没有 README —— 复现者不知道该跑哪条命令")
            return fails, notes, stats
        cmds = cpr.parse_commands(readme.read_text(encoding="utf-8", errors="replace"), entry)
        stats["readme_commands"] = cmds
        if not cmds:
            fails.append(f"{readme.name} 里没有跑 {entry} 的命令")
            return fails, notes, stats
        if len(cmds) > 1:
            fails.append(f"{readme.name} 里给了 {len(cmds)} 条不同的运行命令"
                         f"（{[c[:46] for c in cmds]}）—— 复现者不知道该跑哪条；"
                         "**只留那条能复现提交结果的**")
        else:
            notes.append(f"README 只有一条运行命令：{cmds[0][:78]}")

        # required=True 的参数必须在命令里出现（少一个 ⇒ 照文档跑必然报错）
        cmd = cmds[0]
        src = ""
        for p in root.rglob(entry):
            src = p.read_text(encoding="utf-8", errors="replace")
            break
        if src:
            miss = [k for k, v in cpr.arg_defaults(src).items()
                    if v["required"] and k not in cmd]
            if miss:
                fails.append(f"入口脚本里标了 `required=True` 的参数没写进 README 命令：{miss}"
                             " ⇒ 照说明跑会直接报缺参数")

        # 依赖清单必须存在且带版本（"列明依赖及**对应版本**"是复现的前提）
        deps = [p for p in root.rglob("*")
                if p.name.lower() in ("requirements.txt", "pyproject.toml",
                                      "environment.yml", "environment.yaml", "pipfile")]
        if not deps:
            fails.append("代码包里没有依赖清单（requirements.txt 等）")
        else:
            d = deps[0]
            lines = [ln.strip() for ln in d.read_text(encoding="utf-8", errors="replace").splitlines()]
            real = [ln for ln in lines if ln and not ln.startswith("#") and not ln.startswith("[")]
            bare = [ln for ln in real if not _ver_constrained(ln)]
            stats["deps"] = d.name
            if bare:
                fails.append(f"{d.name} 里有 {len(bare)} 行没写版本（{bare[:4]}）"
                             " —— 规范要求列明依赖及**对应版本**")
            else:
                notes.append(f"依赖清单 {d.name} 每行都带版本约束（{len(real)} 行）")

        # 复现记录：必须在、必须 PASS、必须与**当前这份 csv** 对得上
        rec_path = csv_path.parent / "repro-check.json"
        if not rec_path.exists():
            fails.append(f"没有复现记录 {rec_path.name} —— 用 `check_package_repro.py "
                         "--write-record` 生成（它按 README 原文真跑一遍并与提交结果逐行比）")
        else:
            import json
            try:
                rec = json.loads(rec_path.read_text(encoding="utf-8"))
            except Exception as e:
                rec = None
                fails.append(f"{rec_path.name} 读不出来：{e}")
            if rec is not None:
                stats["record"] = rec.get("verdict", "?")
                if rec.get("fails"):
                    fails.append(f"复现记录里 {len(rec['fails'])} 条不过："
                                 f"{str(rec['fails'][0])[:110]}")
                if rec.get("command") and cmds and rec["command"] not in cmds:
                    fails.append("复现记录里跑的命令与 README 现在写的那条**不是同一条**"
                                 f"（记录 {rec['command'][:60]!r}）⇒ 记录过期，重跑一次")
                now = hashlib.sha256(csv_path.read_bytes()).hexdigest()
                if rec.get("submitted_sha256") and rec["submitted_sha256"] != now:
                    fails.append("复现记录对的是**另一份** csv（sha256 对不上）"
                                 " ⇒ 记录过期：改过 csv 就要重跑 check_package_repro")
                elif not rec.get("submitted_sha256"):
                    fails.append("复现记录里没有 submitted_sha256，无法判断是否过期")
                if not fails and rec.get("row_identical"):
                    notes.append(f"复现记录与当前 csv 一致（{rec.get('checked_at')}，"
                                 f"正类 {rec.get('positives', '?')}）")
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    return fails, notes, stats


def check(csv_path: Path, zip_path: Path | None, expect_pos: int | None,
          test_dir: Path | None, npz: Path | None, score_key: str,
          id_col: str | None = None, label_col: str | None = None):
    """返回 (fails, notes, stats)。"""
    fails, notes = [], []
    raw = csv_path.read_bytes()
    # ⚠️ 编码：读写都按 utf-8-sig（有些模板带 BOM），
    #    否则**列会整体错位** —— 本脚本的作者本人就这么骗过自己一次（`B55`）。
    text = raw.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return ["CSV 是空的"], notes, {}
    header = [c.strip() for c in rows[0]]
    body_all = [r for r in rows[1:] if any(c.strip() for c in r)]
    i_id, i_val, cnotes, cerr = tabular.pick_columns(header, body_all, id_col, label_col)
    notes.extend(cnotes)                 # **认的是哪两列**必须印出来：认错列是静默的
    if cerr:
        fails.append(cerr)
        return fails, notes, {"header": header}
    body = body_all
    ids = [r[i_id].strip() for r in body]
    vals = [r[i_val].strip() for r in body]
    stats = {"rows": len(body), "header": header, "pos": None}

    if not body:
        fails.append("表里没有数据行")
        return fails, notes, stats
    n_pos = sum(1 for v in vals if v == "1")
    stats["pos"] = n_pos
    stats["value_set"] = sorted(set(vals))
    bad = sorted({v for v in vals if v not in ("0", "1")})
    if bad:
        fails.append(f"判断列（`{header[i_val]}`）出现了 0/1 之外的值：{bad[:6]}")
    if expect_pos is not None and n_pos != expect_pos:
        fails.append(f"判 1 的行数是 {n_pos}，而声明的 k = {expect_pos} —— "
                     "k 是提交策略的核心参数，写错等于换了策略")
    if len(set(ids)) != len(ids):
        dup = sorted({x for x in ids if ids.count(x) > 1})
        fails.append(f"ID 列（`{header[i_id]}`）有重复：{dup[:6]}")
    # 序号连续性（只在表里真有序号列时查）
    iseq = header[0]
    if iseq not in (header[i_id], header[i_val]):
        try:
            seq = [int(r[0]) for r in body]
            if seq != list(range(1, len(seq) + 1)):
                fails.append("第一列不是 1..N 连续序号（平台按序号对齐时会静默错位）")
        except (ValueError, IndexError):
            notes.append(f"第一列 `{iseq}` 不是整数序号，跳过连续性检查")

    if test_dir is not None:
        official = sorted(p.stem for p in test_dir.glob("*.csv"))
        if not official:
            fails.append(f"--test-dir 里没有 *.csv：{test_dir}")
        else:
            miss = [x for x in official if x not in set(ids)]
            extra = [x for x in ids if x not in set(official)]
            if miss:
                fails.append(f"官方输入里有 {len(miss)} 个没被提交：{miss[:6]}")
            if extra:
                fails.append(f"提交里有 {len(extra)} 个不在官方输入里的 ID：{extra[:6]}")
            if not miss and not extra:
                notes.append(f"ID 与官方输入逐一对应（{len(official)} 个）")

    if zip_path is not None:
        if not zip_path.exists():
            fails.append(f"找不到 zip：{zip_path}")
        else:
            with zipfile.ZipFile(zip_path) as z:
                names = [n for n in z.namelist() if n.lower().endswith(".csv")]
                if not names:
                    fails.append("zip 里没有 csv")
                else:
                    inner = z.read(names[0])
                    if inner != raw:
                        fails.append(f"zip 里的 {names[0]} 与磁盘上的 csv **逐字节不一致** "
                                     "—— 打包后又改了 csv 是很常见的事故")
                    else:
                        notes.append(f"zip 里的 {names[0]} 与磁盘 csv 逐字节一致")
    if npz is not None:
        try:
            import numpy as np
            d = np.load(npz, allow_pickle=True)
            if score_key not in d:
                fails.append(f"npz 里没有 {score_key!r}（有 {list(d.keys())}）")
            else:
                s = d[score_key].astype(float)
                order = np.argsort(-s)[:n_pos]
                top = {f"test_{i + 1:03d}" for i in order}
                got = {x for x, v in zip(ids, vals) if v == "1"}
                if top != got:
                    fails.append(f"被判 1 的片**不是** {score_key} 分数最高的 {n_pos} 片"
                                 f"（差集 {sorted(top ^ got)[:6]}）—— "
                                 "那这份提交与你在报告里说的排序不是同一个对象")
                else:
                    notes.append(f"判 1 的 {n_pos} 片正是 {score_key} 的 top-{n_pos}")
        except Exception as e:
            fails.append(f"读 npz 失败：{e}")
    return fails, notes, stats


def main() -> int:
    ap = argparse.ArgumentParser(description="提交包机械核对（花额度之前必跑）")
    ap.add_argument("--csv")
    ap.add_argument("--zip", dest="zip_path")
    ap.add_argument("--expect-pos", type=int)
    ap.add_argument("--test-dir")
    ap.add_argument("--score-npz")
    ap.add_argument("--score-key", default="sG")
    ap.add_argument("--code-zip", dest="code_zip", help="提交的代码包（zip）")
    ap.add_argument("--code-dir", dest="code_dir", help="代码包目录（未打包时用）")
    ap.add_argument("--id-col", dest="id_col",
                    help="ID 列名（默认按名字认，认不出就按取值认；两边都认不出会报错）")
    ap.add_argument("--label-col", dest="label_col",
                    help="判断列名（默认按名字认，认不出就找唯一取值 ⊆{0,1} 的列）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    if not args.csv:
        ap.print_help()
        return 2
    if args.score_npz and not args.score_key:
        print("FAIL  给了 --score-npz 就必须同时给 --score-key"
              "（npz 里那个数组叫什么名字，只有你知道）")
        return 2
    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"FAIL  找不到 {csv_path}")
        return 2
    fails, notes, stats = check(
        csv_path,
        Path(args.zip_path) if args.zip_path else None,
        args.expect_pos,
        Path(args.test_dir) if args.test_dir else None,
        Path(args.score_npz) if args.score_npz else None,
        args.score_key,
        args.id_col, args.label_col)
    code_pkg = Path(args.code_zip or args.code_dir) if (args.code_zip or args.code_dir) else None
    cfails, cnotes, cstats = ([], [], {})
    if code_pkg is not None:
        cfails, cnotes, cstats = check_code_package(code_pkg, csv_path)
    print("=" * 84)
    print(f"提交包核对：{csv_path}")
    print("=" * 84)
    print(f"  表头 {stats.get('header')}；数据行 {stats.get('rows')}；"
          f"判 1 {stats.get('pos')}；取值 {stats.get('value_set')}")
    for x in notes:
        print(f"  - {x}")
    if code_pkg is not None:
        print(f"  代码包 {cstats.get('code_pkg')}；入口 {cstats.get('entry')}；"
              f"依赖 {cstats.get('deps')}；复现记录 {cstats.get('record')}")
        for x in cnotes:
            print(f"  - {x}")
    for x in list(fails) + list(cfails):
        print(f"  x {x}")
    if fails or cfails:
        print("-" * 84)
        print(f"⇒ **{len(fails) + len(cfails)} 条不过 ⇒ 不许提交**"
              "（额度不可逆；先改包再重跑本脚本）")
        return 1
    print("-" * 84)
    print("⇒ 全部通过：这份包可以提交。")
    return 0


def _self_test() -> int:
    """六个并排场景：好包 / 列名错 / 片数错 / 取值错 / zip 不一致 / 序号断。"""
    print("=" * 84)
    print("check_submission 自证（六个并排场景）")
    print("=" * 84)
    base = Path(__file__).resolve().parent / "_submission_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    ok = True

    def mk(name, rows, header="seq,id,label", zip_content=None):
        d = base / name
        d.mkdir(parents=True)
        p = d / "result.csv"
        p.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
        if zip_content is not None:
            with zipfile.ZipFile(d / "result.zip", "w") as z:
                z.writestr("result.csv", zip_content)
        return p

    good_rows = [f"{i},{f'test_{i:03d}'},{1 if i <= 3 else 0}" for i in range(1, 11)]
    # ⚠️ 每个场景**只让一条检查失败**（`B28` ②）：一个场景同时踩两条，
    #    等于两条都没被隔离。第一版就有两处踩了：`good` 的期望写反、
    #    `seq_broken` 顺带把片数也写错了，于是它"因为别的原因"FAIL，没测到序号检查。
    seq_broken_rows = (["11,test_001,1"]
                       + [f"{i + 10},test_{i:03d},{1 if i in (2, 3) else 0}"
                          for i in range(2, 11)])
    cases = [
        # 名字, 行, 表头, zip 内容, 声明的 k, 期望退出码
        # 表头一律用**通用英文名**：本脚本不许认识任何课题的列名。
        ("good", good_rows, "seq,id,label", None, 3, 0),
        # **通用性场景**：表头一个英文字都没有（非英文课题）⇒ 靠"唯一取值 ⊆{0,1} 的列"
        # 认出判断列、靠打分认出 ID 列（`序号` 是行号、`编号` 才是身份）⇒ 必须通过。
        # 这一条是"换一个课题还能用"的机械证据。
        ("cjk_auto", [f"{i},test_{i:03d},{1 if i <= 3 else 0}" for i in range(1, 11)],
         "序号,编号,判断", None, 3, 0),
        # 表头与取值**都**认不出判断列 ⇒ 必须拒收（**不许猜一列继续跑**）。
        # 注意：`seq,A,B` 且 B 列取值恰好是 0/1 时**不算认不出** —— 那是按内容认出来了
        # （上面 `cjk_auto` 就是这条路）。所以这里要让取值也认不出来。
        ("cant_tell_label", [f"{i},alpha_{i},gamma_{i}" for i in range(1, 11)],
         "seq,A,B", None, 3, 1),
        ("bad_count", good_rows, "seq,id,label", None, 5, 1),
        ("bad_value", [f"{i},test_{i:03d},{(1 if i <= 3 else 0)}" for i in range(1, 10)]
         + ["10,test_010,0.0"], "seq,id,label", None, 3, 1),
        ("zip_mismatch", good_rows, "seq,id,label", "完全不同\n", 3, 1),
        # 序号断：行数与取值都对，**只有序号**错 ⇒ 单独测那一条
        ("seq_broken", seq_broken_rows, "seq,id,label", None, 3, 1),
    ]
    try:
        for name, rows, header, zc, k, exp in cases:
            p = mk(name, rows, header, zc)
            fails, notes, stats = check(
                p, (p.parent / "result.zip") if zc is not None else None, k, None, None, None)
            code = 1 if fails else 0
            good = (code == exp)
            ok &= good
            print(f"{'PASS' if good else 'FAIL'}  {name:13s} 退出码 {code}（期望 {exp}）"
                  + (f"  首条：{fails[0][:70]}" if fails else "  全过"))

        # ---- 代码包那一半（第 41 轮补的）：六个场景，每个只让一条检查失败 ----
        import hashlib
        import json as _json
        print("-" * 84)
        print("代码包那一半（README 命令 / 依赖版本 / 复现记录）")
        good_cmd = "python predict.py --data_dir ./data --output ./result.csv --top_k 3"

        def mkcodepkg(name, *, cmds, deps="numpy>=2.0\n", extra_required=False,
                      record="ok"):
            d = base / name
            d.mkdir(parents=True, exist_ok=True)
            rows = [f"{i},test_{i:03d},{1 if i <= 3 else 0}" for i in range(1, 11)]
            csvp = d / "result.csv"
            csvp.write_text("seq,id,label\n" + "\n".join(rows) + "\n",
                            encoding="utf-8")
            code = d / "code"
            code.mkdir(parents=True, exist_ok=True)
            (code / "predict.py").write_text(
                'import argparse\nap = argparse.ArgumentParser()\n'
                'ap.add_argument("--data_dir", required=True)\n'
                'ap.add_argument("--output", required=True)\n'
                + ('ap.add_argument("--top_k", type=int, required=True)\n'
                   if extra_required else
                   'ap.add_argument("--top_k", type=int, default=3)\n')
                + 'if __name__ == "__main__":\n    pass\n', encoding="utf-8")
            (code / "requirements.txt").write_text(deps, encoding="utf-8")
            (code / "README.md").write_text(
                "# 说明\n\n```bash\n" + "\n```\n\n```bash\n".join(cmds) + "\n```\n",
                encoding="utf-8")
            if record is not None:
                rec = {"tool": "check_package_repro.py", "command": cmds[0],
                       "submitted_sha256": hashlib.sha256(csvp.read_bytes()).hexdigest(),
                       "row_identical": True, "positives": 3,
                       "checked_at": "2026-01-01T00:00:00"}
                if record == "stale":
                    rec["submitted_sha256"] = "0" * 64
                if record == "failed":
                    rec["fails"] = ["复现结果与提交结果不一致"]
                (d / "repro-check.json").write_text(
                    _json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            return code, csvp

        # 每个场景只破坏一条：多命令 / 依赖无版本 / 缺记录 / 记录过期 / required 参数没写进命令。
        # 每一项还钉**它必须因为哪个原因失败**（`must_catch`）——只钉退出码是不够的：
        # M58 那次实测，把"记录缺失"这条判断关掉之后，"读不出来"那条兜底又报了 FAIL，
        # 退出码一模一样 ⇒ 变异"没被抓住"，而缺陷其实还在。
        # 钉住原因 ⇒ 判断被拆掉、或原因被换成别的，都会当场现形。
        code_cases = [
            ("code_ok", dict(cmds=[good_cmd]), 0, ""),
            ("code_two_cmds", dict(cmds=[good_cmd,
                                         good_cmd.replace("--top_k 3", "--top_k 1")]),
             1, "条不同的运行命令"),
            ("code_no_versions", dict(cmds=[good_cmd], deps="numpy\n"), 1, "没写版本"),
            ("code_no_record", dict(cmds=[good_cmd], record=None), 1, "没有复现记录"),
            ("code_rec_stale", dict(cmds=[good_cmd], record="stale"), 1, "另一份"),
            ("code_req_arg", dict(cmds=["python predict.py --data_dir ./data "
                                        "--output ./result.csv"], extra_required=True),
             1, "required=True"),
        ]
        for name, kw, exp, must in code_cases:
            code_dir, csvp = mkcodepkg(name, **kw)
            cfails, _, _ = check_code_package(code_dir, csvp)
            code = 1 if cfails else 0
            blob = " ".join(cfails)
            caught = (must in blob) if must else (not cfails)
            good = (code == exp) and caught
            ok &= good
            print(f"{'PASS' if good else 'FAIL'}  {name:13s} 退出码 {code}（期望 {exp}）"
                  + (f"  首条：{cfails[0][:64]}" if cfails else "  全过")
                  + ("" if caught else f"  **但没钉住原因 {must!r}**"))
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("-" * 84)
    print("check_submission 自证结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
