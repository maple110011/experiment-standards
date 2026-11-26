#!/usr/bin/env python3
"""fake_kaggle.py - 假 Kaggle CLI，用于自测 kaggle_job.py 的状态机.

用法:
  KAGGLE_CLI_CMD="<python> <本文件>" python scripts/kaggle_job.py status --name smoke
行为由环境变量控制:
  FAKE_KAGGLE_STATE  状态目录（push/status 计数器、calls.log）
  FAKE_ALWAYS_RUNNING=1  永远返回 RUNNING（测 --wait 超时）
  FAKE_FAIL=1            返回 ERROR（测失败分支）
  FAKE_EXIT_CODE=N       output 下载的 result.json 里的 exit_code
"""
import json
import os
import sys
from pathlib import Path

state = Path(os.environ.get("FAKE_KAGGLE_STATE", "/tmp/fake-kaggle"))
state.mkdir(parents=True, exist_ok=True)
args = sys.argv[1:]

with open(state / "calls.log", "a", encoding="utf-8") as f:
    f.write("FAKE kaggle " + " ".join(args) + "\n")


def bump(name):
    p = state / name
    n = int(p.read_text().strip() or "0") if p.exists() else 0
    n += 1
    p.write_text(str(n))
    return n


cmd = args[0] if args else ""
if cmd in ("--version", "-v"):
    print("Kaggle CLI 2.2.5 (fake)")
elif cmd == "config":
    print("- username: testuser")
    print("- path: fake")
elif cmd == "quota":
    print(json.dumps({"gpu": {"weekly": 30, "used": 1.5, "remaining": 28.5},
                      "tpu": {"weekly": 20, "used": 0, "remaining": 20}}))
elif cmd == "kernels":
    sub = args[1] if len(args) > 1 else ""
    if sub == "push":
        n = bump("push_count")
        print("Kernel version %d successfully pushed. Please check progress at "
              "https://www.kaggle.com/code/testuser/smoke" % n)
    elif sub == "status":
        n = bump("status_count")
        if os.environ.get("FAKE_ALWAYS_RUNNING") == "1":
            st = "KernelWorkerStatus.RUNNING"
        elif os.environ.get("FAKE_FAIL") == "1":
            st = "KernelWorkerStatus.ERROR"
        elif n <= 2:
            st = "KernelWorkerStatus.RUNNING"
        else:
            st = "KernelWorkerStatus.COMPLETE"
        print('%s has status "%s"' % (args[2], st))
    elif sub == "logs":
        print("=== fake kernel log ===")
        print("epoch 0 loss 1.2300")
        print("epoch 1 loss 1.1000")
    elif sub == "output":
        dest = Path(".")
        rest = args[2:]
        for i, a in enumerate(rest):
            if a in ("-p", "--path") and i + 1 < len(rest):
                dest = Path(rest[i + 1])
        dest.mkdir(parents=True, exist_ok=True)
        code = int(os.environ.get("FAKE_EXIT_CODE", "0"))
        (dest / "result.json").write_text(json.dumps(
            {"exit_code": code, "ok": code == 0, "metrics": {"note": "fake"}},
            ensure_ascii=False, indent=2), encoding="utf-8")
        (dest / "run.log").write_text("fake log line\n", encoding="utf-8")
        (dest / "environment.json").write_text('{"gpu": "fake"}', encoding="utf-8")
        print("Downloading fake output to", dest)
    elif sub == "list":
        print("testuser  smoke  fake  1")
    else:
        print("fake: unsupported kernels subcommand " + sub, file=sys.stderr)
        sys.exit(1)
else:
    print("fake: unsupported command " + cmd, file=sys.stderr)
    sys.exit(1)
