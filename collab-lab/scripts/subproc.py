#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""子进程调用的**唯一**入口，兼**自身输出**的兜底：把"编码"这件事收在一处。

## 为什么需要它（读的一侧：立此模块的那次失效）

`check_collab_artifacts.py --self-test` 会 spawn 一堆 fixtures 脚本并读取它们的
stdout 来做断言。这些脚本打印中文。Windows 上 Python 的 stdout **不是管道时**
用控制台编码，**是管道时用区域编码**（本机 `cp936`）——

```
python -c "import sys; print(sys.stdout.encoding)"     # 直接跑: utf-8
python -c "... | Out-String"                            # 被管道: gbk   ← 子进程就是这种
```

于是父进程用 `encoding="utf-8"` 去解码子进程的 `cp936` 中文输出 ⇒
`UnicodeDecodeError` ⇒ `subprocess` 的 reader 线程崩掉 ⇒ **`r.stdout` 变成 `None`**
⇒ 调用点 `r.stdout.splitlines()` 抛 `AttributeError` ⇒ **整个自检带 traceback 死掉**。

**为什么这比"自检报 FAIL"严重得多**：报 FAIL 是一个能被读到的信号；
带 traceback 死掉是一个**看起来像环境问题的崩溃**，人会绕过它——
于是"规则可执行性自检"这条判据本身失效了，而失效得**无人察觉**。
这与 `M-7`（偏离是静默的）是同一个形态：一个只在有人记得设环境变量时才起作用的
检查，等于没有检查。

## 写的一侧：同一天撞上的另一半

立本模块的**同一天**又撞上它的另一半：给守卫加了一条新判据，那条判据的 FAIL
提示里含一个 `⇒`（U+21D2）—— **cp936 里没有这个字符** ⇒ `UnicodeEncodeError`
⇒ **守卫在"报告失败"的那一行崩掉**。
一个"只在控制台能编码你写的字时才报得出错"的守卫，等于没有守卫。

## 三条纪律

1. **子进程必须被显式要求用 UTF-8 写 stdout**（`PYTHONIOENCODING` + `PYTHONUTF8`），
   **不能依赖调用者当前的环境**——环境变量不是接口的一部分。
2. **解码失败必须降级成"报错"而不是"崩溃"**（`errors="replace"`），
   并**永不返回 `None`**（`run_text` 保证 stdout 是 `str`）。
3. **自己的输出也不许崩**（`harden_streams()`，**import 本模块即生效**）：
   控制台能印的中文照旧印，印不出的字符（`⇒`、emoji、替换字符…）降级成 `?`，
   **永不抛异常**。⇒ 任何会打印给人看的入口脚本都应 `import subproc`。

## 单一定义

与 `goal_guard.py` 里的 `BLOCK_GOAL_RE` 同一条理由：两个脚本消费同一份输出时，
**解析/编码设置必须只有一处定义**。曾经有过一次"两处副本不同步"的静默失效，
所以这里不再让每个调用点各写一遍 `env=`。
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading

__all__ = ["utf8_env", "run_text", "run_inherit", "harden_streams"]


def harden_streams() -> None:
    """让本进程**永远能报告**：不可编码的字符降级，而不是抛 `UnicodeEncodeError`。"""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")   # type: ignore[union-attr]
        except Exception:
            pass


harden_streams()


def utf8_env() -> dict:
    """返回一份"强制 UTF-8 stdio"的环境变量副本。

    两个变量都设：
    - `PYTHONIOENCODING=utf-8`：直接指定 stdio 编码；
    - `PYTHONUTF8=1`：打开 Python 的 UTF-8 模式（同时影响文件系统编码等）。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def run_text(cmd, **kw):
    """跑子进程并**必定**返回一个 `str` stdout。

    - 默认 `capture_output=True, text=True, encoding="utf-8", errors="replace"`；
    - 总是注入 UTF-8 环境（调用点若显式给了 `env=`，在它之上再覆盖编码项）；
    - 返回 `CompletedProcess`，但把 `stdout`/`stderr` 兜底成 `""`
      —— 这样调用点写 `r.stdout.splitlines()` 永远不会炸。
    """
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("encoding", "utf-8")
    kw.setdefault("errors", "replace")
    kw["env"] = {**utf8_env(), **kw.get("env", {})}
    r = subprocess.run(cmd, **kw)
    if r.stdout is None:
        r.stdout = ""
    if r.stderr is None:
        r.stderr = ""
    return r


def run_inherit(cmd, **kw):
    """不捕获输出、直接继承控制台（子进程自己要打给人看时用）。"""
    kw["env"] = {**utf8_env(), **kw.get("env", {})}
    return subprocess.run(cmd, **kw)


PROBE = ("import sys; sys.stdout.write('中文探针:' + (sys.stdout.encoding or '?'))")


def _raw_env() -> dict:
    """把本模块注入的两个变量摘掉 —— 用来复现"调用者没设环境"的现场。"""
    return {k: v for k, v in os.environ.items()
            if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}


def _self_test() -> int:
    """自证：本模块要挡的那个失效**真的能被复现、也真的被挡住**。

    两次调用同一个探针，只差"有没有注入 UTF-8 环境 / 有没有 errors=replace"：
      · **不注入 + 不设 errors** —— 复现原始崩溃形态（stdout 变 None）；
      · **注入 + errors=replace**   —— 读出正确的中文，且 stdout 永不为 None。
    两侧并排，才能证明"注入不是装饰"、"errors 不是装饰"
    （单侧只能证明其中一半，这正是 `E`/staleness fixtures 用过的并排手法）。
    """
    print("=" * 70)
    print("subproc 自证：子进程编码必须被强制为 UTF-8，且解码失败不得崩父进程")
    print("=" * 70)
    ok = True
    env = _raw_env()

    # ① 故障侧：不注入、不设 errors ⇒ 复现崩溃（stdout is None）
    #
    # ⚠️ 这段是**故意触发**失效的，Python 会在 reader 线程里打一份 traceback 到 stderr。
    #    那份 traceback 会把一次"PASS"印得像崩了 —— 而"噪声里的假危险"会训练人忽略
    #    traceback，正是本模块要防的东西。所以只在这一段里静音线程异常钩子。
    crashed = False
    orig_hook = getattr(threading, "excepthook", None)
    try:
        threading.excepthook = lambda _a: None
        bad = subprocess.run([sys.executable, "-c", PROBE], capture_output=True,
                             text=True, encoding="utf-8", env=env)
        crashed = (bad.stdout is None) or ("中文探针" not in bad.stdout)
    except UnicodeDecodeError:
        crashed = True
    finally:
        if orig_hook is not None:
            threading.excepthook = orig_hook
    if crashed:
        print("PASS  故障侧：不注入 UTF-8 时，读取子进程输出会失败"
              "（stdout 变 None / 解码异常）—— 这就是立本模块的那个失效")
    else:
        print("NOTE  故障侧：本机子进程即使不注入也输出 UTF-8，"
              "该失效在本环境不可复现（机制仍保留，不影响正确性）")

    # ② 正常侧：注入 + errors=replace ⇒ 中文正确、stdout 恒为 str
    r = run_text([sys.executable, "-c", PROBE])
    good = ("中文探针" in r.stdout) and ("utf-8" in r.stdout) and isinstance(r.stdout, str)
    print(f"{'PASS' if good else 'FAIL'}  正常侧：{r.stdout.strip()!r}")
    ok &= good

    # ③ 降级侧：注入环境但故意把 errors 去掉，并喂一个 GBK 字节流
    #    —— 证明"errors=replace"承担的是"失败而非崩溃"这一半
    r3 = subprocess.run([sys.executable, "-c",
                         "import sys; sys.stdout.buffer.write('中文'.encode('gbk'))"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", env=env)
    degraded = isinstance(r3.stdout, str)
    # 诊断信息里**不要**直接印替换字符：它在 GBK 控制台上会二次抛 UnicodeEncodeError
    #（这正是本模块第三条纪律的来由）。用 unicode_escape 转成纯 ASCII 再印。
    shown = r3.stdout.encode("unicode_escape").decode("ascii")
    print(f"{'PASS' if degraded else 'FAIL'}  降级侧：非 UTF-8 字节被替换而非抛异常"
          f"（stdout={shown}）")
    ok &= degraded

    print("-" * 70)
    print("subproc 自证结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_self_test())
