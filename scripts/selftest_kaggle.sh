#!/usr/bin/env bash
# selftest.sh - 不依赖账号，用假 CLI 回归 kaggle_job.py 的全部状态分支。
# 用法：bash pfn-compute-research/scripts/selftest.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/.." || exit 1
PYEXE="$(python -c "import sys;print(sys.executable)" | sed "s|\\\\|/|g")"
ST="$(python -c "import os;print(os.getcwd().replace(chr(92),chr(47)))")/.tmp/selftest"
rm -rf .tmp/selftest jobstate
mkdir -p .tmp/selftest
export KAGGLE_CLI_CMD="$PYEXE scripts/tests/fake_kaggle.py"
export FAKE_KAGGLE_STATE="$ST"
PASS=0
FAIL=0

check() {  # $1=名字 $2=期望退出码 $3...=命令
  local name="$1"; local want="$2"; shift 2
  "$@" >/dev/null 2>&1
  local got=$?
  if [ "$got" -eq "$want" ]; then
    echo "[PASS] $name (rc=$got)"
    PASS=$((PASS + 1))
  else
    echo "[FAIL] $name: 期望 rc=$want，实际 rc=$got"
    FAIL=$((FAIL + 1))
  fi
}

echo "== 1. 提交 + 正常完成 + 取回 =="
check "提交" 0 python scripts/kaggle_job.py submit --name smoke --file scripts/templates/kaggle_smoke.py
check "等到 finished" 0 python scripts/kaggle_job.py status --name smoke --wait 30 --interval 1
check "取回且 exit_code=0" 0 python scripts/kaggle_job.py fetch --name smoke

echo "== 2. 仍在运行时 --wait 超时应返回 2 =="
check "提交 failjob" 0 python scripts/kaggle_job.py submit --name failjob --file scripts/templates/kaggle_smoke.py
FAKE_ALWAYS_RUNNING=1
check "超时返回 2" 2 env FAKE_ALWAYS_RUNNING=1 python scripts/kaggle_job.py status --name failjob --wait 3 --interval 1
unset FAKE_ALWAYS_RUNNING

echo "== 3. 平台失败应返回 1 =="
check "平台 ERROR" 1 env FAKE_FAIL=1 python scripts/kaggle_job.py status --name failjob

echo "== 4. 产物 exit_code 非 0 应返回 1 =="
check "提交 badcode" 0 python scripts/kaggle_job.py submit --name badcode --file scripts/templates/kaggle_smoke.py
check "跑到完成" 0 python scripts/kaggle_job.py status --name badcode --wait 30 --interval 1
check "exit_code=2" 1 env FAKE_EXIT_CODE=2 python scripts/kaggle_job.py fetch --name badcode

echo "== 5. 状态归一化：名字带 fail 不能误判 =="
check "提交 failcode" 0 python scripts/kaggle_job.py submit --name failcode --file scripts/templates/kaggle_smoke.py
check "RUNNING 不被名字误导" 2 env FAKE_ALWAYS_RUNNING=1 python scripts/kaggle_job.py status --name failcode --wait 2 --interval 1

echo "== 6. 列表能列出以上作业 =="
check "list" 0 python scripts/kaggle_job.py list

echo "== 7. 未登录路径（用真 CLI，可选）=="
unset KAGGLE_CLI_CMD FAKE_KAGGLE_STATE
python scripts/kaggle_job.py doctor >/dev/null 2>&1
DOC_RC=$?
if [ "$DOC_RC" -eq 0 ]; then
  echo "[INFO] 真 CLI 已登录，doctor 返回 0（说明阶段 1 的账号已就绪）"
else
  echo "[INFO] 真 CLI 未登录，doctor 返回 $DOC_RC（符合预期，账号还没配）"
fi

rm -rf .tmp/selftest jobstate
echo "----------------------------------------"
echo "通过: $PASS  失败: $FAIL"
[ "$FAIL" -eq 0 ]
