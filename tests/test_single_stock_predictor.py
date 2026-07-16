import numpy as np
import pandas as pd

from research.single_stock_predictor import FEATURE_COLUMNS, build_dataset, walk_forward_evaluate


def _daily(n=450):
    rng = np.random.default_rng(42)
    close = 10 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, n)))
    return pd.DataFrame({
        "open": close * 0.998,
        "high": close * 1.02,
        "low": close * 0.98,
        "close": close,
        "vol": rng.integers(100_000, 500_000, n),
    }, index=pd.bdate_range("2020-01-01", periods=n))


def test_unknown_future_labels_remain_missing():
    data = build_dataset(_daily())
    assert data["target"].tail(20).isna().all()
    assert data.dropna(subset=FEATURE_COLUMNS).index.max() == data.index.max()


def test_walk_forward_uses_horizon_embargo():
    data = build_dataset(_daily(600))
    folds, _ = walk_forward_evaluate(data, n_splits=3, horizon=20)
    assert len(folds) == 3
    assert (pd.to_datetime(folds["test_start"]) - pd.to_datetime(folds["train_end"])).dt.days.min() >= 20
