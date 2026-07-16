"""Point-in-time factor discovery for a solar-equipment stock."""
from __future__ import annotations

from functools import partial
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_selection import SelectKBest, mutual_info_classif
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

HORIZON, THRESHOLD = 20, 0.08
FEATURES = ["stock_ret_5", "stock_ret_20", "market_rel_5", "market_rel_20", "peer_rel_5", "peer_rel_20",
            "pb_z_252", "pb_change_20", "turnover_z_60", "volume_ratio", "net_flow_5", "large_flow_5",
            "net_flow_z_60", "realized_vol_20"]

def build_frame(stock: pd.DataFrame, basic: pd.DataFrame, moneyflow: pd.DataFrame,
                market: pd.Series, peers: pd.DataFrame) -> pd.DataFrame:
    df = stock[["close", "vol", "amount"]].copy().sort_index()
    ret = df.close.pct_change()
    market_ret = market.sort_index().pct_change().reindex(df.index)
    peer_ret = peers.sort_index().pct_change().mean(axis=1).reindex(df.index)
    basic = basic.reindex(df.index)
    flow = moneyflow.reindex(df.index)
    df["stock_ret_5"], df["stock_ret_20"] = df.close.pct_change(5), df.close.pct_change(20)
    df["market_rel_5"] = df["stock_ret_5"] - market_ret.rolling(5).sum()
    df["market_rel_20"] = df["stock_ret_20"] - market_ret.rolling(20).sum()
    df["peer_rel_5"] = df["stock_ret_5"] - peer_ret.rolling(5).sum()
    df["peer_rel_20"] = df["stock_ret_20"] - peer_ret.rolling(20).sum()
    pb = basic.pb.replace([np.inf, -np.inf], np.nan)
    df["pb_z_252"] = (pb - pb.rolling(252).mean()) / pb.rolling(252).std()
    df["pb_change_20"] = pb.pct_change(20)
    turnover = basic.turnover_rate
    df["turnover_z_60"] = (turnover - turnover.rolling(60).mean()) / turnover.rolling(60).std()
    df["volume_ratio"] = basic.volume_ratio
    net = flow.net_mf_amount / df.amount.replace(0, np.nan)
    large = (flow.buy_lg_amount + flow.buy_elg_amount - flow.sell_lg_amount - flow.sell_elg_amount) / df.amount.replace(0, np.nan)
    df["net_flow_5"], df["large_flow_5"] = net.rolling(5).sum(), large.rolling(5).sum()
    df["net_flow_z_60"] = (net - net.rolling(60).mean()) / net.rolling(60).std()
    df["realized_vol_20"] = ret.rolling(20).std() * np.sqrt(252)
    future = df.close.shift(-HORIZON) / df.close - 1
    df["target"] = np.where(future.notna(), (future > THRESHOLD).astype(int), np.nan)
    return df

def _model(kind: str) -> Pipeline:
    classifier = LogisticRegression(max_iter=3000, class_weight="balanced", random_state=42) if kind == "logistic" else HistGradientBoostingClassifier(max_iter=150, max_leaf_nodes=8, l2_regularization=2.0, random_state=42)
    steps = [("impute", SimpleImputer(strategy="median")), ("select", SelectKBest(partial(mutual_info_classif, random_state=42), k=7))]
    if kind == "logistic": steps.insert(1, ("scale", StandardScaler()))
    return Pipeline(steps + [("model", classifier)])

def evaluate(frame: pd.DataFrame, kinds=("logistic", "hist_gradient"), splits=5) -> tuple[pd.DataFrame, dict[str, Pipeline]]:
    labelled = frame.dropna(subset=["target"]).copy()
    n, size = len(labelled), len(labelled) // (splits + 1)
    rows, final = [], {}
    for kind in kinds:
        for fold in range(1, splits + 1):
            start = n - (splits - fold + 1) * size
            train, test = labelled.iloc[:start-HORIZON], labelled.iloc[start:start+size]
            pipe = _model(kind); pipe.fit(train[FEATURES], train.target.astype(int))
            p = pipe.predict_proba(test[FEATURES])[:, 1]; y = test.target.astype(int)
            rows.append({"model":kind,"fold":fold,"train_end":train.index[-1].date().isoformat(),"test_start":test.index[0].date().isoformat(),"test_end":test.index[-1].date().isoformat(),"roc_auc":roc_auc_score(y,p),"balanced_accuracy":balanced_accuracy_score(y,p>=.5)})
        final[kind] = _model(kind).fit(labelled[FEATURES], labelled.target.astype(int))
    return pd.DataFrame(rows), final
