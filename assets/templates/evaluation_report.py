"""
结构化评估报告 — 生成 JSON 格式的 evaluation_report.json 和 experiment_metadata.json。

用法:
    from evaluation_report import generate_evaluation_report, generate_experiment_metadata
    generate_evaluation_report(metrics, env, CONFIG, "outputs/evaluation_report.json")
    generate_experiment_metadata(CONFIG, env, dataset_info, "outputs/experiment_metadata.json")
"""
import json
from datetime import datetime


def generate_evaluation_report(metrics, env, config, output_path):
    """生成结构化评估报告。metrics 中常用键:
    - 回归: test_rmse, test_mae, coverage_95pct
    - 分类: test_acc, test_nll, ece, brier
    - 训练: total_epochs, final_loss, early_stopped, training_time_seconds, best_epoch
    """
    report = {
        "experiment": config.get("experiment", "unnamed"),
        "timestamp": datetime.now().isoformat(),
        "environment": env,
        "config": config,
        "metrics": metrics,
        "training": {
            "total_epochs": metrics.get("total_epochs", 0),
            "final_loss": metrics.get("final_loss"),
            "early_stopped": metrics.get("early_stopped", False),
            "training_time_seconds": metrics.get("training_time_seconds", 0),
            "best_epoch": metrics.get("best_epoch", 0),
        },
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"评估报告已保存至 {output_path}")


def generate_experiment_metadata(config, env, dataset_info, output_path):
    """生成实验元数据 (环境 + config + 数据集规模)。"""
    metadata = {
        "experiment_name": config.get("experiment", "unnamed"),
        "date": datetime.now().isoformat(),
        "environment": env,
        "config": config,
        "dataset": dataset_info,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False, default=str)
    print(f"实验元数据已保存至 {output_path}")
