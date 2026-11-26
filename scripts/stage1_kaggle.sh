#!/usr/bin/env bash
# stage1_kaggle.sh - Kaggle 闭环一键验证（阶段 1）
#
# 做的事：体检 -> 提交冒烟 kernel -> 等它跑完 -> 拉日志 -> 取回产物 -> 校验 exit_code。
# 用法（在仓库根目录）：
#   bash pfn-compute-research/scripts/stage1_kaggle.sh
#   bash pfn-compute-research/scripts/stage1_kaggle.sh mysmoke 1800
# 环境变量：
#   TIMEOUT   提交给 Kaggle 的 kernel 超时秒数，默认 1800
#   WAIT      本地等待秒数，默认 3600
#   NAME      作业名，默认 smoke
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/.." || exit 1
NAME="${1:-smoke}"
TIMEOUT="${TIMEOUT:-1800}"
WAIT="${WAIT:-3600}"
PY="python"
OUT="$PWD/jobstate/$NAME/out"

echo "########## 1/5 体检 ##########"
"$PY" scripts/kaggle_job.py doctor || {
  echo "[FAIL] 体检没过：先按 scripts/README.md 的「账号准备」完成 Kaggle 注册、手机验证与登录。"
  exit 1
}

echo "########## 2/5 提交冒烟 kernel ##########"
"$PY" scripts/kaggle_job.py submit --name "$NAME" --file scripts/templates/kaggle_smoke.py --timeout-seconds "$TIMEOUT" || exit 2

echo "########## 3/5 等待完成 ##########"
"$PY" scripts/kaggle_job.py status --name "$NAME" --wait "$WAIT" --interval 30
STATUS_RC=$?
if [ "$STATUS_RC" -eq 2 ]; then
  echo "[WARN] 还在跑；可用下面命令继续看："
  echo "  python scripts/kaggle_job.py status --name $NAME --wait $WAIT"
  exit 2
elif [ "$STATUS_RC" -ne 0 ]; then
  echo "[FAIL] 作业失败；先看日志："
  echo "  python scripts/kaggle_job.py logs --name $NAME"
  exit 3
fi

echo "########## 4/5 日志（末尾 40 行）##########"
"$PY" scripts/kaggle_job.py logs --name "$NAME" 2>&1 | tail -40

echo "########## 5/5 取回产物 ##########"
"$PY" scripts/kaggle_job.py fetch --name "$NAME"
FETCH_RC=$?

echo "########## 结果 ##########"
echo "作业名   : $NAME"
echo "产物目录 : $OUT"
RESULT_JSON="$OUT/result.json"
RESULT_WIN="$(cygpath -w "$RESULT_JSON" 2>/dev/null || echo "$RESULT_JSON")"
if [ -f "$RESULT_JSON" ]; then
  "$PY" - "$RESULT_WIN" <<'PY'
import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
env = r.get("environment", {}) or {}
print("exit_code:", r.get("exit_code"))
for k in ("cuda_available", "cuda_device_name", "cuda_device_count", "torch", "hostname", "user"):
    if k in env:
        print(k + ":", env[k])
PY
fi
if [ "$FETCH_RC" -eq 0 ]; then
  echo "[PASS] 闭环完成：提交 -> 状态 -> 日志 -> 取回 全通，exit_code=0"
else
  echo "[FAIL] 产物取回或 exit_code 校验失败（fetch rc=$FETCH_RC）"
fi
exit "$FETCH_RC"
