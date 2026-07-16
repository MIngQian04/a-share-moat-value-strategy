"""Leakage-aware technical-factor model for one A-share security.

The module deliberately keeps the modelling surface small: every feature only
uses information known at that day's close, the final incomplete label is
removed, and each walk-forward split has a 20-session embargo.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

import numpy as np
import pandas as pd
from sklearn.feature_selection import SelectKBest, mutual_info_classif
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


HORIZON = 20
THRESHOLD = 0.08
FEATURE_COLUMNS = [
    "ret_5d",
    "ret_20d",
    "rsi_14",
    "price_position_20d",
    "macd_hist_atr",
    "atr_pct_14",
    "realized_vol_20d",
    "volume_z_20d",
    "volume_trend_20d",
]


@dataclass(frozen=True)
class ModelResult:
    folds: pd.DataFrame
    selected_features: list[str]
    latest_probability: float
    latest_signal: str
    latest_date: pd.Timestamp


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    losses = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return 100 - (100 / (1 + gains / losses.replace(0, np.nan)))


def build_dataset(daily: pd.DataFrame, horizon: int = HORIZON, threshold: float = THRESHOLD) -> pd.DataFrame:
    """Return a chronological frame with point-in-time factors and nullable labels."""
    df = daily.copy().sort_index()
    required = {"open", "high", "low", "close", "vol"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Daily data missing columns: {sorted(missing)}")

    close, high, low, vol = (df[name].astype(float) for name in ("close", "high", "low", "vol"))
    returns = close.pct_change()
    typical_price = (high + low + close) / 3
    true_range = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = true_range.rolling(14, min_periods=14).mean()
    ema_fast = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema_slow = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()

    df["ret_5d"] = close.pct_change(5)
    df["ret_20d"] = close.pct_change(20)
    df["rsi_14"] = (_rsi(close) - 50) / 50
    rolling_low, rolling_high = low.rolling(20).min(), high.rolling(20).max()
    df["price_position_20d"] = (close - rolling_low) / (rolling_high - rolling_low).replace(0, np.nan) - 0.5
    df["macd_hist_atr"] = (macd - macd_signal) / atr.replace(0, np.nan)
    df["atr_pct_14"] = atr / close
    df["realized_vol_20d"] = returns.rolling(20).std() * np.sqrt(252)
    log_vol = np.log1p(vol)
    df["volume_z_20d"] = (log_vol - log_vol.rolling(20).mean()) / log_vol.rolling(20).std().replace(0, np.nan)
    df["volume_trend_20d"] = vol.rolling(5).mean() / vol.rolling(20).mean().replace(0, np.nan) - 1
    df["vwap_proxy_gap"] = close / typical_price - 1
    df["future_return"] = close.shift(-horizon) / close - 1
    # Keep the unknown tail as NaN: converting it with astype(int) would create false negatives.
    df["target"] = np.where(df["future_return"].notna(), (df["future_return"] > threshold).astype(int), np.nan)
    return df


def _pipeline(k: int) -> Pipeline:
    return Pipeline([
        ("scaler", StandardScaler()),
        ("select", SelectKBest(partial(mutual_info_classif, random_state=42), k=k)),
        ("model", LogisticRegression(max_iter=2_000, class_weight="balanced", random_state=42)),
    ])


def walk_forward_evaluate(dataset: pd.DataFrame, n_splits: int = 5, horizon: int = HORIZON) -> tuple[pd.DataFrame, list[str]]:
    """Expanding-window evaluation with a label-horizon embargo."""
    labelled = dataset.dropna(subset=FEATURE_COLUMNS + ["target"]).copy()
    n = len(labelled)
    test_size = n // (n_splits + 1)
    rows: list[dict[str, object]] = []
    for fold in range(1, n_splits + 1):
        test_start = n - (n_splits - fold + 1) * test_size
        test_end = test_start + test_size
        train_end = test_start - horizon
        if train_end <= 100:
            raise ValueError("Not enough history for requested splits and embargo")
        train, test = labelled.iloc[:train_end], labelled.iloc[test_start:test_end]
        k = min(5, len(FEATURE_COLUMNS))
        pipe = _pipeline(k)
        pipe.fit(train[FEATURE_COLUMNS], train["target"].astype(int))
        probability = pipe.predict_proba(test[FEATURE_COLUMNS])[:, 1]
        prediction = (probability >= 0.5).astype(int)
        y_test = test["target"].astype(int)
        rows.append({
            "fold": fold,
            "train_end": train.index[-1].date().isoformat(),
            "test_start": test.index[0].date().isoformat(),
            "test_end": test.index[-1].date().isoformat(),
            "n_train": len(train),
            "n_test": len(test),
            "positive_rate": y_test.mean(),
            "accuracy": accuracy_score(y_test, prediction),
            "balanced_accuracy": balanced_accuracy_score(y_test, prediction),
            "precision": precision_score(y_test, prediction, zero_division=0),
            "roc_auc": roc_auc_score(y_test, probability) if y_test.nunique() == 2 else np.nan,
        })
    final_pipe = _pipeline(min(5, len(FEATURE_COLUMNS)))
    final_pipe.fit(labelled[FEATURE_COLUMNS], labelled["target"].astype(int))
    mask = final_pipe.named_steps["select"].get_support()
    return pd.DataFrame(rows), list(np.asarray(FEATURE_COLUMNS)[mask])


def fit_and_predict(dataset: pd.DataFrame, n_splits: int = 5) -> ModelResult:
    folds, selected = walk_forward_evaluate(dataset, n_splits=n_splits)
    labelled = dataset.dropna(subset=FEATURE_COLUMNS + ["target"])
    available = dataset.dropna(subset=FEATURE_COLUMNS)
    latest = available.iloc[-1:]
    pipe = _pipeline(min(5, len(FEATURE_COLUMNS)))
    pipe.fit(labelled[FEATURE_COLUMNS], labelled["target"].astype(int))
    probability = float(pipe.predict_proba(latest[FEATURE_COLUMNS])[0, 1])
    signal = "看多" if probability >= 0.60 else "中性" if probability >= 0.40 else "偏空"
    return ModelResult(folds, selected, probability, signal, latest.index[0])
