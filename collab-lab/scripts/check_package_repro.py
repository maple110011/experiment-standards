#!/usr/bin/env -S python -u
# -*- coding: utf-8 -*-
r"""check_package_repro.py —— **代码包能不能复现它自己交的那份结果？**

## 它治的是哪一句话

> "我不知道 agent 在干嘛，也不知道它为什么要这样干……甚至看不懂它的输出结果、回报结果。"

这一层是那句话最贵的一种形态：**提交的代码包与提交的结果不是同一个对象，而没人会发现。**
官方流程是"把你的代码包解开、照你的说明复现一遍"，写得很清楚：

`提交规范` §三(四)1 —— "复现结果与提交结果不一致" ⇒ **取消晋级资格**。

于是"README 里那条运行命令"不是文档，**它是一个接口**。而它此前**没有任何常驻机制**在核对：
`check_submission.py` 只核 CSV 与 zip，**从不打开代码包**。结果就是：最不可逆的那一类错，
恰好是唯一没被机械化的一类。（这正是 `M-7`"偏离是静默的"的又一次现身。）

## 实测：这个缺陷一次踩了三份包（第 41 轮）

六份提交里，**三份的 README 运行命令复现不出它自己交的那份结果**：

- 一份交上去是 **11 个正类**，照 README 复现出 **34 个**（差 23 行）；
- 一份交上去是 **34 个**，照 README 复现出的是**另一组 34 个**（集合不同，不是行数问题）；
- 一份交上去是 **150 个**，照 README 复现出 **34 个**（差 184 行）。

成因一律相同：**README 的运行命令是从上一个包复制过来的**，入口脚本里的默认参数也是复制的；
其中一份的 README 甚至自己跟自己矛盾（页脚注释写的是这个包的真实参数，命令写的却是上一个包的）。
三份里有两份**已经交上去了** —— 而按提交规范，"复现结果与提交结果不一致"是取消资格那一档。

⇒ 人要犯的错是"复制"，机制要挡的也必须是"复制"：
静态看那些 `predict.py` **一条都挑不出毛病**（它们自己的用法注释是对的），**只有真跑一遍**才看得出来。

## 它为什么可以做到"与赛题无关"

"解开包 → 把说明里的数据目录指到真数据 → 照说明原文跑 → 与已提交的结果对齐"
——这套流程**不含任何赛题知识**：数据目录是参数，比对的是包自己的结果。
所以它是 skill 的脚本，而不是工作区里的一次性脚本。

## 五条检查

| # | 检查 | 挡的是什么 |
|---|---|---|
| R1 | 找到**入口脚本**（有 `argparse` 且有 `__main__` 的那个 `.py`） | 包里没有能跑的东西 |
| R2 | 找到 README，且里面有指向入口脚本的运行命令 | 说明与代码对不上号 |
| R3 | 运行命令**唯一** | 多条命令 ⇒ 复现者不知道该跑哪条（上面那三份的原形） |
| R4 | **原样**解开、按 README 原文跑，退出码 0 | 命令本身跑不起来 |
| R5 | 产出与已提交结果**逐行相同**（按 ID 列对齐；列名由 `tabular.py` 按内容认，或调用方指定） | 复现结果 ≠ 提交结果 ⇒ 取消资格 |

外加 R6（**只记不判**）：规范示例那条"两参数最小命令"能不能跑通 ——
官方示例是那样给的，跑不通值得记一笔，但规范允许你按自己的说明跑，所以不算 FAIL。

**已知边界（写清楚，免得下次又靠猜）**：R1/R2 认的是 `python <脚本>.py …` 这种命令形状。
若某个课题的复现命令不是这个形状（`python -m pkg.train`、`Rscript`、`make run`…），
本脚本**认不出来** —— 它会报"README 里没有跑入口脚本的命令"，那是**边界**不是缺陷。
扩展方式：把 `CMD_RE` 做成可配的命令形状，或给 `--entry` 一个显式的完整命令。
（本 skill 的首个实例就是前一种形状，所以当时没有暴露这个边界。）

## 三条纪律（都是踩出来的）

1. **junction/symlink 清理必须删链接本身，不能递归删目录。**
   本机是 Windows；`mklink /J` 建出来的 junctions 在 `os.scandir` 里**看起来就是普通目录**。
   所以这里用 `os.rmdir()`（`RemoveDirectoryW` 只摘链接）而**不是** `rmtree`：
   一旦递归进去，删掉的是**赛题数据**（不是副本）。
   ⚠️ 但要说实话：实测本机 Python 3.14.5 的 `shutil.rmtree` **不会**跟进 junction
   （并排试过：`rmtree(host)` 之后 target 的 5 个 csv 一个不少），
   所以这一条现在是**防御性**的、不是"当场挡下了一次事故"。立它的理由是
   **不依赖 `rmtree` 的实现细节**（旧版本 / 别的工具 / `cmd /c rmdir /S` 都会跟进）。
   自证里钉的是**不变量本身**："跑完之后目标数据一个没少"。
2. **子进程与本进程的编码都交给 `subproc`** —— 见该模块；本脚本不再自己写 `env=`。
3. **临时目录不能用 `tempfile.mkdtemp()`** —— 见 `mktmp()`：
   它按 `0o700` 建目录，而本机（DSH 沙箱 workspace-write）**拒绝往 `0o700` 的目录里再建东西**。

用法：
    python scripts/check_package_repro.py --pkg <包目录或 zip> --data-dir <测试数据目录>
        [--submitted <已提交的 result.csv>] [--entry predict.py] [--data-rel data]
        [--write-record] [--json]
    python scripts/check_package_repro.py --self-test
退出码：0 = 复现一致；1 = 有 FAIL（**这份包按规范会被取消资格**）；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subproc  # noqa: E402
import tabular  # noqa: E402  （列识别只定义一处：见该模块"为什么要有这个模块"）

CMD_RE = re.compile(r"^[ \t]*python[ \t]+([\w./\\-]+\.py)[ \t]+(.*)$", re.M)


def mktmp(prefix: str) -> Path:
    """建一个**真的能往里写**的临时目录。

    ⚠️ 不要用 `tempfile.mkdtemp()`：它按 `0o700` 建目录，而本机
    （DSH 沙箱 workspace-write）**拒绝往 `0o700` 的目录里再建任何东西**
    （`WinError 5 拒绝访问`）——于是"临时目录"里一个文件都放不下。
    实测并排（同一个父目录）：`mode 0o777` 嵌套 OK、`0o755` 嵌套 OK、`0o700` PermissionError。

    这不是洁癖：`mkdtemp` 的失败**发生在用完临时目录的时候**，
    表现为"解包解不开 / 复制不过去"，看着像环境坏了，而不是像本脚本的检查失败。
    """
    for base in (Path(tempfile.gettempdir()), Path.cwd()):
        for i in range(100):
            d = base / f"{prefix}{os.getpid()}_{i}"
            try:
                d.mkdir(mode=0o755)
            except FileExistsError:
                continue
            except OSError:
                break                      # 这个 base 不可用，换下一个
            # 再确认一次"真能写"——本机踩过的就是这个坑
            try:
                probe = d / ".writable"
                probe.write_text("1", encoding="utf-8")
                probe.unlink()
                return d
            except OSError:
                continue
    raise RuntimeError("建不出可写的临时目录（TEMP 与 cwd 都不行）")


# ---------------------------------------------------------------- 包的结构

def load_package(pkg: Path) -> tuple[Path, str]:
    """把包变成"一个目录"。zip 就地解开到**包外的**临时目录。

    返回 (目录, 临时目录或 "")。临时目录必须由调用方清理。
    """
    if pkg.is_dir():
        return pkg, ""
    if not pkg.exists():
        raise SystemExit(f"FAIL  找不到包：{pkg}")
    # ⚠️ 临时目录必须建在**包外面**：上一轮把包复制进自己里面，得到 RecursionError。
    tmp = mktmp("pkg_repro_")
    with zipfile.ZipFile(pkg) as z:
        z.extractall(tmp)
    return _flatten(tmp), str(tmp)


def _flatten(root: Path) -> Path:
    """zip 里若只有一层同名目录，钻进去（两种情况都要能跑）。"""
    items = [p for p in root.iterdir() if not p.name.startswith("__MACOSX")]
    if len(items) == 1 and items[0].is_dir():
        return items[0]
    return root


def find_entry(root: Path, want: str | None = None) -> tuple[str | None, list[str]]:
    """找入口脚本：显式给了就用它；否则取"有 argparse 且有 __main__"的 .py。"""
    pys = sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    names = [p.name for p in pys]
    if want:
        return (want if want in names else None), names
    hits = [p.name for p in pys
            if "argparse" in p.read_text(encoding="utf-8", errors="replace")
            and "__main__" in p.read_text(encoding="utf-8", errors="replace")]
    return (hits[0] if len(hits) == 1 else None), names


def find_readme(root: Path) -> Path | None:
    for p in sorted(root.rglob("*.md")):
        if p.name.lower().startswith("readme"):
            return p
    return None


def parse_commands(text: str, entry: str) -> list[str]:
    """抽出所有"跑这个入口脚本"的命令，**保持出现顺序、去重**。"""
    out, seen = [], set()
    for m in CMD_RE.finditer(text):
        if Path(m.group(1).replace("\\", "/")).name != entry:
            continue
        cmd = f"python {m.group(1)} {m.group(2).strip()}".strip()
        if cmd not in seen:
            seen.add(cmd)
            out.append(cmd)
    return out


def arg_defaults(src: str) -> dict:
    """从源码里读 `add_argument("--x", ..., default=Y, required=True)` 的关键信息。"""
    out = {}
    for m in re.finditer(r'add_argument\(\s*"(--[\w-]+)"(.*?)\)\s*\n', src, re.S):
        name, body = m.group(1), m.group(2)
        dv = re.search(r"default=([^,)\s]+)", body)
        out[name] = {"default": dv.group(1) if dv else None,
                     "required": "required=True" in body}
    return out


# ---------------------------------------------------------------- 跑与比对

def link_data(run_dir: Path, name: str, target: Path) -> tuple[bool, str]:
    """把 run_dir/<name> 做成指向 target 的**链接**（Windows 用 junction）。"""
    link = run_dir / name
    if os.name == "nt":
        r = subproc.run_text(["cmd", "/c", "mklink", "/J", str(link), str(target)])
        ok = r.returncode == 0
    else:
        try:
            os.symlink(target, link)
            ok = True
        except OSError as e:                      # pragma: no cover
            ok, r = False, e
    return ok, ("" if ok else str(getattr(r, "stdout", r)))


def unlink_data(link: Path) -> None:
    """**只摘链接，不递归**。

    `rmtree` 在 Windows 上会把 junction 当成普通目录递归进去 ——
    那删掉的是**真数据**。`os.rmdir()` 走 `RemoveDirectoryW`，只摘链接本身。
    """
    if not link.exists() and not os.path.lexists(link):
        return
    try:
        os.rmdir(link)
    except OSError:
        # 兜底：cmd 的 rmdir 对 junction 同样是"摘链接"（**不带 /S**）
        subproc.run_text(["cmd", "/c", "rmdir", str(link)])


def load_labels(csv_path: Path, id_col: str | None = None,
                label_col: str | None = None) -> tuple[dict, str]:
    """读"ID → 判断"两列。**实现只有一处**（`tabular.py`），本函数只是转发。

    ⚠️ 这里原先有一份自己的 `ID_KEYS` / `VAL_KEYS`，注释还写着"与 check_submission
    同一套口径，避免两处定义漂移" —— 而**代码实际就是两份副本**，注释声明的纪律
    与代码做的事相反。这正是本 skill 的 `A10` 记的那个失效形态。
    """
    labels, err, _ = tabular.load_labels(csv_path, id_col, label_col)
    return labels, err


def compare(got: Path, want: Path) -> tuple[bool, bool, str]:
    """返回 (逐行相同, 逐字节相同, 说明)。"""
    if not got.exists():
        return False, False, "没有产出结果文件"
    g, eg = load_labels(got)
    w, ew = load_labels(want)
    if eg or ew:
        return False, False, f"读不出来：{eg or ew}"
    if g == w:
        same = got.read_bytes() == want.read_bytes()
        return True, same, f"逐行相同（{len(g)} 行，正类 {sum(1 for v in g.values() if v == '1')}）"
    diff = [k for k in set(g) | set(w) if g.get(k) != w.get(k)]
    pg = sum(1 for v in g.values() if v == "1")
    pw = sum(1 for v in w.values() if v == "1")
    return False, False, (f"不同 {len(diff)} 行（复现正类 {pg} vs 提交正类 {pw}）；"
                          f"首例 {diff[0] if diff else '-'}")


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_package(pkg: Path, data_dir: Path, submitted: Path, entry: str | None,
                data_rel: str) -> dict:
    """跑一遍复现。返回一份机器可读的记录（也是 `repro-check.json` 的内容）。"""
    root, tmp = load_package(pkg)
    rec: dict = {"tool": "check_package_repro.py", "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "pkg": str(pkg), "data_dir": str(data_dir), "fails": [], "notes": []}
    try:
        if not root.exists():
            rec["fails"].append(f"解包后没有内容：{root}")
            return rec
        entry, all_py = find_entry(root, entry)
        if entry is None:
            rec["fails"].append(f"找不到唯一的入口脚本（包里的 .py：{all_py}）")
            return rec
        rec["entry"] = entry
        readme = find_readme(root)
        if readme is None:
            rec["fails"].append(f"包里没有 README（{root}）")
            return rec
        rec["readme"] = readme.name
        cmds = parse_commands(readme.read_text(encoding="utf-8", errors="replace"), entry)
        if not cmds:
            rec["fails"].append(f"{readme.name} 里没有跑 {entry} 的命令"
                                " —— 复现者不知道该怎么跑")
            return rec
        rec["readme_commands"] = cmds
        if len(cmds) > 1:
            rec["fails"].append(
                f"{readme.name} 里给了 {len(cmds)} 条不同的运行命令（{cmds}）—— "
                "复现者不知道该跑哪条；**只留那条能复现提交结果的**，其余删掉")
            return rec
        cmd = cmds[0]
        rec["command"] = cmd

        # 命令里的 --output / 数据目录名，用来安排运行现场
        m_out = re.search(r"--output[= ]+(\S+)", cmd)
        out_name = Path(m_out.group(1)).name if m_out else "result.csv"
        run_dir = mktmp("pkg_run_")
        link = None
        try:
            shutil.copytree(root, run_dir / "pkg", dirs_exist_ok=True)
            work = run_dir / "pkg"
            data_names = set(re.findall(r"--data_dir[= ]+(\S+)", cmd)) or {"./" + data_rel}
            dn = Path(list(data_names)[0]).name or data_rel
            if not (work / dn).exists():
                link = work / dn
                ok, why = link_data(work, dn, data_dir)
                if not ok:
                    rec["fails"].append(f"没法把 `{dn}` 指到真数据：{why[:160]}")
                    return rec
                rec["notes"].append(f"`{dn}` 用链接指向真数据目录（未复制）")
            r = subproc.run_text(cmd, cwd=work, shell=True)
            rec["exit"] = r.returncode
            if r.returncode != 0:
                tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
                rec["fails"].append(f"按 README 原文跑，退出码 {r.returncode}：{' / '.join(tail)[:300]}")
                return rec
            got = work / out_name
            ok_row, ok_byte, why = compare(got, submitted)
            rec["submitted"] = str(submitted)
            rec["submitted_sha256"] = sha256(submitted)
            rec["row_identical"], rec["byte_identical"] = ok_row, ok_byte
            if got.exists():
                rec["reproduced_sha256"] = sha256(got)
                labels = load_labels(got)[0]
                rec["rows"] = len(labels)
                rec["positives"] = sum(1 for v in labels.values() if v == "1")
            if not ok_row:
                rec["fails"].append(
                    f"复现结果与提交结果不一致：{why} ⇒ 按 `提交规范` §三(四)1 "
                    "**取消晋级资格**；先改包（或改说明）再重跑本脚本")
            else:
                rec["notes"].append(f"复现一致：{why}"
                                    + ("" if ok_byte else "（字节序不同，无碍）"))

            # R6：规范示例那条两参数最小命令 —— 只记不判
            mini = f"python {entry} --data_dir ./{dn} --output ./result.min.csv"
            r2 = subproc.run_text(mini, cwd=work, shell=True)
            mok, _, mwhy = compare(work / "result.min.csv", submitted)
            rec["min_command"] = {"command": mini, "exit": r2.returncode, "row_identical": mok}
            rec["notes"].append(
                f"规范示例那条最小命令：退出码 {r2.returncode}，"
                + ("结果一致" if mok else f"不一致（{mwhy}）")
                + ("—— 若评审按规范示例直接跑就会失败，建议让默认值就能复现"
                   if (r2.returncode != 0 or not mok) else ""))
        finally:
            if link is not None:
                unlink_data(link)
            shutil.rmtree(run_dir, ignore_errors=True)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        # `verdict` 只在这里算一次：上面的返回路径有五条（找不到入口/没有 README/没有命令/
        # 命令不唯一/跑挂/比对不一致），在每条上各写一遍必然有一天漏一条。
        # 放在 `finally` 里 ⇒ 任何返回路径都带着结论，且**结论与 fails 不可能不一致**。
        rec["verdict"] = "FAIL" if rec.get("fails") else "PASS"
    return rec


# ---------------------------------------------------------------- 自证

def _self_test() -> int:
    """并排四个场景，每个**只让一条检查失败**（`B28` ②）。

    并且断言：跑完之后，被链接的数据目录**一个文件都没少**（`unlink_data` 那条纪律）。
    """
    print("=" * 84)
    print("check_package_repro 自证（四个并排场景 + 数据目录未被删除）")
    print("=" * 84)
    base = mktmp("pkg_repro_selftest_")
    data = base / "data"
    data.mkdir()
    for i in range(1, 6):
        (data / f"test_{i:03d}.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    n_before = len(list(data.glob("*.csv")))

    def mkpkg(name, *, cmd, default="3", readme=True, extra_cmd=None):
        d = base / name
        (d / "models").mkdir(parents=True)
        (d / "models" / "m.npz").write_bytes(b"x")
        (d / "requirements.txt").write_text("numpy\n", encoding="utf-8")
        body = ('import argparse\n'
                'ap = argparse.ArgumentParser()\n'
                'ap.add_argument("--data_dir", required=True)\n'
                'ap.add_argument("--output", required=True)\n'
                f'ap.add_argument("--top_k", type=int, default={default})\n'
                'a = ap.parse_args()\n'
                'k = 0 if a.top_k is None else a.top_k\n'
                'rows = [f"{i},test_{i:03d},{1 if i <= k else 0}" for i in range(1, 5)]\n'
                'open(a.output, "w", encoding="utf-8").write('
                '"seq,id,label\\n" + "\\n".join(rows) + "\\n")\n'
                'if __name__ == "__main__":\n    pass\n')
        (d / "predict.py").write_text(body, encoding="utf-8")
        if readme:
            txt = ("# 说明\n\n## 运行命令\n```bash\n" + cmd + "\n```\n"
                   + (f"\n```bash\n{extra_cmd}\n```\n" if extra_cmd else ""))
            (d / "README.md").write_text(txt, encoding="utf-8")
        return d

    # 每份"已提交结果"都用该包自己的脚本跑一遍生成，保证期望值独立于被测逻辑
    def submit(pkg, top_k):
        out = base / f"{pkg.name}.submitted.csv"
        env_out = subproc.run_text(
            f'python predict.py --data_dir {data} --output {out} --top_k {top_k}',
            cwd=pkg, shell=True)
        assert env_out.returncode == 0, env_out.stderr
        return out

    cases = []
    good = mkpkg("good", cmd="python predict.py --data_dir ./data --output ./result.csv --top_k 3")
    cases.append(("good", good, submit(good, 3), 0))

    # ① README 命令与提交结果不符（B/D 的原形：命令是复制的）
    mism = mkpkg("mismatch", cmd="python predict.py --data_dir ./data --output ./result.csv --top_k 3")
    cases.append(("mismatch", mism, submit(mism, 1), 1))

    # ② README 给了两条不同命令（C4/D 的原形）
    two = mkpkg("two_cmds",
                cmd="python predict.py --data_dir ./data --output ./result.csv --top_k 3",
                extra_cmd="python predict.py --data_dir ./data --output ./result.csv --top_k 1")
    cases.append(("two_cmds", two, submit(two, 3), 1))

    # ③ 命令退出码非 0（D 修之前：两参数最小命令 exit 2 的那一类）
    brk = mkpkg("nonzero", readme=True, default="None",
                cmd="python predict.py --data_dir ./data --output ./result.csv")
    (brk / "predict.py").write_text(
        (brk / "predict.py").read_text(encoding="utf-8").replace(
            'a = ap.parse_args()',
            'a = ap.parse_args()\nif a.top_k is None:\n    ap.error("必须给出 --top_k")'),
        encoding="utf-8")
    cases.append(("nonzero", brk, submit(brk, 3), 1))

    # ④ 没有 README
    nr = mkpkg("no_readme", readme=False,
               cmd="python predict.py --data_dir ./data --output ./result.csv --top_k 3")
    cases.append(("no_readme", nr, submit(nr, 3), 1))

    ok = True
    try:
        for name, pkg, sub, exp in cases:
            rec = run_package(pkg, data, sub, None, "data")
            code = 1 if rec["fails"] else 0
            # `verdict` 必须与 `fails` 一致（它是给别的脚本读的那个字段，写错就白写）
            vok = rec.get("verdict") == ("FAIL" if rec["fails"] else "PASS")
            good_case = (code == exp) and vok
            ok &= good_case
            head = rec["fails"][0][:64] if rec["fails"] else "全过"
            print(f"{'PASS' if good_case else 'FAIL'}  {name:10s} 退出码 {code}（期望 {exp}）"
                  f"  verdict={rec.get('verdict')}  {head}")
        # 纪律：链接清理不得删掉真数据
        n_after = len(list(data.glob("*.csv")))
        intact = (n_after == n_before) and n_after > 0
        ok &= intact
        print(f"{'PASS' if intact else 'FAIL'}  {'data_intact':10s} "
              f"跑完 {len(cases)} 份包后，被链接的数据目录仍有 {n_after} 个 csv"
              f"（跑前 {n_before}）")
    finally:
        for p in base.iterdir():                     # 兜底：先摘可能的链接再删
            if os.path.isdir(p) and os.path.isjunction(p):
                unlink_data(p)
        shutil.rmtree(base, ignore_errors=True)
    print("-" * 84)
    print("check_package_repro 自证结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


# ---------------------------------------------------------------- 入口

def main() -> int:
    ap = argparse.ArgumentParser(description="代码包自复现核对（花额度/交包之前必跑）")
    ap.add_argument("--pkg", help="代码包：目录或 zip")
    ap.add_argument("--data-dir", help="README 里 `./data` 该指向的那个目录（真数据）")
    ap.add_argument("--submitted", help="已提交的 result.csv（默认取包旁边的同名文件）")
    ap.add_argument("--entry", help="入口脚本名（默认自动找）")
    ap.add_argument("--data-rel", default="data", help="命令里数据目录的名字（默认 data）")
    ap.add_argument("--write-record", action="store_true",
                    help="把结果写成 <包>/repro-check.json（供 check_submission.py 核）")
    ap.add_argument("--json", action="store_true", help="只输出 json")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    if not args.pkg or not args.data_dir:
        ap.print_help()
        return 2
    pkg = Path(args.pkg)
    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        print(f"FAIL  --data-dir 不是目录：{data_dir}")
        return 2
    submitted = Path(args.submitted) if args.submitted else pkg.parent / "result.csv"
    if not submitted.exists():
        print(f"FAIL  找不到已提交结果：{submitted}（用 --submitted 指定）")
        return 2
    rec = run_package(pkg, data_dir, submitted, args.entry, args.data_rel)
    if args.write_record:
        target = pkg.parent / "repro-check.json"
        target.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        rec["wrote"] = str(target)
    if args.json:
        print(json.dumps(rec, ensure_ascii=False, indent=2))
    else:
        print("=" * 84)
        print(f"代码包自复现核对：{pkg}")
        print("=" * 84)
        print(f"  入口 {rec.get('entry')}；README {rec.get('readme')}")
        print(f"  命令 {rec.get('command')}")
        print(f"  退出码 {rec.get('exit')}；提交哈希 {str(rec.get('submitted_sha256'))[:12]}"
              f"；复现哈希 {str(rec.get('reproduced_sha256'))[:12]}")
        for x in rec.get("notes", []):
            print(f"  - {x}")
        for x in rec["fails"]:
            print(f"  x {x}")
        print("-" * 84)
        if rec["fails"]:
            print(f"⇒ **{len(rec['fails'])} 条不过**：这份包按 `提交规范` §三(四)1 会被取消晋级资格")
            return 1
        print("⇒ 通过：README 那条命令复现出了你交上去的那份结果。")
    return 1 if rec["fails"] else 0


if __name__ == "__main__":
    sys.exit(main())
