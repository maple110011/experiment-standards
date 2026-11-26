#!/usr/bin/env python3
r"""kaggle_cli.py - 在 DSH 沙箱里启动真正的 Kaggle CLI.

为什么要有这一层：沙箱里的 PATH 解析不到 MSYS 的 bash（Windows 的
C:\Windows\System32\bash.exe 是 WSL 存根，直接调用会报 0x80070042），
而 pip 的系统级安装又被沙箱拒绝。所以 CLI 装在 workspace 的
vendor/site 下，用当前 Python 解释器启动，配置目录指向 workspace。

用法：python scripts/kaggle_cli.py quota --format json
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VENDOR = ROOT / "vendor" / "site"

if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))
os.environ.setdefault("KAGGLE_CONFIG_DIR", str(ROOT / ".kaggle"))

sys.argv = ["kaggle"] + sys.argv[1:]
from kaggle.cli import main  # noqa: E402

main()
