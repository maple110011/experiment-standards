"""
Early Stopping — 基于验证集指标 (不是训练 loss) 的早停
用法:
    stopper = EarlyStopper(patience=15, min_delta=1e-4)
    for epoch in range(...):
        if stopper(val_metric):
            print(f"Early stopping at epoch {epoch}")
            break
"""
class EarlyStopper:
    def __init__(self, patience=15, min_delta=1e-4, mode="min"):
        self.patience = patience
        self.min_delta = min_delta
        self.mode = mode
        self.best = float("inf") if mode == "min" else float("-inf")
        self.counter = 0
        self.should_stop = False

    def __call__(self, metric):
        if self.mode == "min":
            improved = metric < self.best - self.min_delta
        else:
            improved = metric > self.best + self.min_delta
        if improved:
            self.best = metric
            self.counter = 0
        else:
            self.counter += 1
            if self.counter >= self.patience:
                self.should_stop = True
        return self.should_stop
