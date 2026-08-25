#!/usr/bin/env python3
"""
experiment-standards skill 的自动评测脚本。

用法:
  python evals/run_evals.py                            # 运行模板单元测试
  python evals/run_evals.py --check-outputs DIR        # 校验标准化输出目录
  python evals/run_evals.py --check-dcu-env ENV_JSON   # 校验 DCU/ROCm 环境记录
"""
import os, sys, json, tempfile, argparse
import torch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "assets", "templates"))

RESULTS = []

def check(name, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print(f"PASS  {name}")
    except Exception as e:
        RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        print(f"FAIL  {name}  -> {type(e).__name__}: {e}")

# ---------------------------------------------------------------------------
# 模板单元测试
# ---------------------------------------------------------------------------
def test_early_stopper_min():
    from early_stopper import EarlyStopper
    s = EarlyStopper(patience=2, min_delta=0.0, mode="min")
    assert s(1.0) is False and s.best == 1.0
    assert s(0.5) is False and s.best == 0.5
    assert s(0.9) is False
    assert s(0.9) is True

def test_early_stopper_max():
    from early_stopper import EarlyStopper
    s = EarlyStopper(patience=2, min_delta=0.0, mode="max")
    assert s(0.5) is False and s.best == 0.5
    assert s(0.9) is False and s.best == 0.9
    assert s(0.8) is False
    assert s(0.8) is True

def test_ckpt_save_load_roundtrip():
    from checkpoint_manager import CheckpointManager, capture_rng_state
    with tempfile.TemporaryDirectory() as tmp:
        m = CheckpointManager(os.path.join(tmp, "ckpt"), keep_recent_n=3)
        ms = {"w": torch.randn(3)}
        m.save(epoch=10, config={"lr": 0.01}, model_state=ms,
               optimizer_state={}, rng_state=capture_rng_state())
        ck = m.load()
        assert ck is not None and ck["epoch"] == 10
        assert torch.allclose(ck["model_state"]["w"], ms["w"])
        assert "numpy" in ck["rng_state"] and "python" in ck["rng_state"]

def test_ckpt_cleanup_keeps_recent_and_best():
    from checkpoint_manager import CheckpointManager
    with tempfile.TemporaryDirectory() as tmp:
        m = CheckpointManager(os.path.join(tmp, "ckpt"), keep_recent_n=3)
        for e in [0, 500, 1000, 1500]:
            m.save(epoch=e, config={}, model_state={}, optimizer_state={}, rng_state={})
        m.save(epoch=2000, config={}, model_state={}, optimizer_state={}, rng_state={}, is_best=True)
        files = os.listdir(os.path.join(tmp, "ckpt"))
        epoch_files = [f for f in files if f.startswith("ckpt_epoch") and f.endswith(".tar")]
        assert len(epoch_files) == 3, sorted(epoch_files)
        assert "ckpt_best.tar" in files

def test_ckpt_mode_max():
    from checkpoint_manager import CheckpointManager
    with tempfile.TemporaryDirectory() as tmp:
        m = CheckpointManager(os.path.join(tmp, "ckpt"), mode="max")
        assert m.update_best(0, 0.9) is True and m.best_val_metric == 0.9
        assert m.update_best(1, 0.8) is False

def test_environment_capture_keys():
    from environment_capture import capture_environment
    env = capture_environment()
    for key in ["platform", "hostname", "python_version", "cpu", "gpu",
                "packages", "torch_config", "runtime"]:
        assert key in env, f"missing {key}"
    assert env["packages"]["torch"] == torch.__version__
    assert "available" in env["gpu"]

def test_ckpt_damaged_fallback():
    from checkpoint_manager import CheckpointManager
    with tempfile.TemporaryDirectory() as tmp:
        m = CheckpointManager(os.path.join(tmp, "ckpt"), keep_recent_n=5)
        m.save(epoch=10, config={}, model_state={}, optimizer_state={}, rng_state={})
        # 放一个更新的但已损坏的 checkpoint, load 应自动回退到 epoch 10
        with open(os.path.join(tmp, "ckpt", "ckpt_epoch999.tar"), "w") as f:
            f.write("not a torch archive")
        ck = m.load()
        assert ck is not None and ck["epoch"] == 10

def test_experiment_recorder_basic():
    import tempfile, os, json
    from experiment_recorder import (make_run_dir, log_event, log_epoch,
                                     update_results_json, save_probs)
    with tempfile.TemporaryDirectory() as tmp:
        # 创建一个临时代码文件用于快照
        code_file = os.path.join(tmp, "train.py")
        with open(code_file, "w") as f:
            f.write("print('hello')\n")
        run_dir = make_run_dir(tmp, "exp_test", config={"lr": 0.01},
                               code_paths=[code_file], env={"gpu": "none"})
        assert os.path.exists(os.path.join(run_dir, "run_manifest.json"))
        assert os.path.exists(os.path.join(run_dir, "code", "train.py"))
        with open(os.path.join(run_dir, "run_manifest.json")) as f:
            manifest = json.load(f)
        assert manifest["config"] == {"lr": 0.01}
        assert "train.py" in manifest["code_files"]
        log_event(run_dir, "test_event", a=1)
        assert os.path.exists(os.path.join(run_dir, "events.jsonl"))
        log_epoch(run_dir, "MAP", 0, loss=0.5)
        assert os.path.exists(os.path.join(run_dir, "training", "MAP_metrics.csv"))
        update_results_json(run_dir, "results_partial.json", "MAP", {"acc": 0.9})
        with open(os.path.join(run_dir, "results_partial.json")) as f:
            partial = json.load(f)
        assert partial["methods"]["MAP"]["acc"] == 0.9
        import numpy as np
        save_probs(run_dir, "MAP", np.zeros((4, 3)), np.arange(4), 3)
        assert os.path.exists(os.path.join(run_dir, "predictions", "MAP_probs.npy"))
        assert os.path.exists(os.path.join(run_dir, "predictions", "MAP_ytrue.npy"))

def test_experiment_recorder_extra_outputs():
    import tempfile, os, json
    import numpy as np
    from experiment_recorder import (make_run_dir, save_regression_predictions,
                                     save_split_indices, update_shift_results_json,
                                     save_temperature_scaling, save_model_weights)
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = make_run_dir(tmp, "exp_extra", config={}, env={"gpu": "none"})
        save_regression_predictions(run_dir, "MAP", np.zeros(4), np.ones(4), np.arange(4))
        assert os.path.exists(os.path.join(run_dir, "predictions", "MAP_mean.npy"))
        assert os.path.exists(os.path.join(run_dir, "predictions", "MAP_var.npy"))
        save_split_indices(run_dir, [0, 1], [2], [3])
        assert os.path.exists(os.path.join(run_dir, "split_indices.npz"))
        update_shift_results_json(run_dir, "gaussian", "MAP", {"acc": 0.8})
        with open(os.path.join(run_dir, "evaluation_shift.json")) as f:
            assert json.load(f)["shifts"]["gaussian"]["MAP"]["acc"] == 0.8
        save_temperature_scaling(run_dir, "MAP", 1.2, {"ece": 0.1}, {"ece": 0.05})
        assert os.path.exists(os.path.join(run_dir, "calibration_temperature.json"))
        class M:
            def state_dict(self):
                return {"w": np.zeros(1)}
        save_model_weights(run_dir, "MAP", M())
        assert os.path.exists(os.path.join(run_dir, "checkpoints", "MAP_best.pt"))

# ---------------------------------------------------------------------------
# 输出目录校验
# ---------------------------------------------------------------------------
REQUIRED_FILES = [
    "environment.json", "seed.json", "experiment_metadata.json",
    "training.log", "errors.log", "metrics.csv",
    "checkpoints/ckpt_best.tar", "best_model.pt",
    "evaluation_report.json",
]

def check_outputs_dir(outdir):
    missing = [f for f in REQUIRED_FILES if not os.path.isfile(os.path.join(outdir, f))]
    if missing:
        raise AssertionError(f"missing required files: {missing}")
    # JSON 可解析
    for jf in ["environment.json", "seed.json", "experiment_metadata.json", "evaluation_report.json"]:
        with open(os.path.join(outdir, jf)) as f:
            json.load(f)
    # CSV 有 header 且每行字段数与 header 一致
    import csv
    with open(os.path.join(outdir, "metrics.csv"), newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise AssertionError("metrics.csv is empty")
    ncols = len(rows[0])
    for i, row in enumerate(rows[1:], 1):
        if len(row) != ncols:
            raise AssertionError(f"metrics.csv line {i}: {len(row)} cols != header {ncols}")
    print(f"PASS  output check: {len(REQUIRED_FILES)} required files present, JSON/CSV valid")

def check_dcu_env(env_json):
    with open(env_json) as f:
        env = json.load(f)
    gpu = env.get("gpu", {})
    tc = env.get("torch_config", {})
    if not gpu.get("available"):
        print("SKIP  DCU env check: gpu.available is False (not on DCU?)")
        return
    assert gpu.get("backend") == "hip", f"backend should be hip, got {gpu.get('backend')}"
    dev = gpu.get("device_0", {})
    assert "gcn_arch" in dev, f"device_0 should have gcn_arch, got {dev}"
    assert tc.get("hip_version"), f"hip_version missing: {tc}"
    print("PASS  DCU env check: backend/hip/gcn_arch recorded correctly")

# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-outputs", default=None)
    ap.add_argument("--check-dcu-env", default=None)
    args = ap.parse_args()

    if args.check_outputs:
        check_outputs_dir(args.check_outputs)
        sys.exit(0)
    if args.check_dcu_env:
        check_dcu_env(args.check_dcu_env)
        sys.exit(0)

    for name, fn in [
        ("early_stopper min", test_early_stopper_min),
        ("early_stopper max", test_early_stopper_max),
        ("checkpoint save/load roundtrip", test_ckpt_save_load_roundtrip),
        ("checkpoint cleanup keeps recent+best", test_ckpt_cleanup_keeps_recent_and_best),
        ("checkpoint mode=max", test_ckpt_mode_max),
        ("environment_capture keys", test_environment_capture_keys),
        ("checkpoint damaged fallback", test_ckpt_damaged_fallback),
        ("experiment_recorder basic", test_experiment_recorder_basic),
        ("experiment_recorder extra outputs", test_experiment_recorder_extra_outputs),
    ]:
        check(name, fn)

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"{passed}/{len(RESULTS)} passed")
    sys.exit(0 if passed == len(RESULTS) else 1)
