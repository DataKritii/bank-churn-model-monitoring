"""
churn_model.py
==============
Reusable code for notebooks/bank_churn_model_monitoring.ipynb: the churn model,
the simulated 12-month monitoring period, and the export of Power BI tables.

    1. Load the data; drop identifiers and surname; leave out gender and age (protected grounds)
    2. Compare four models in the same pipeline; select by 5-fold cross-validated AUC
    3. Score a simulated year of production data, with gradual population drift from
       month 7 and a simulated market event from month 10
    4. Compute monthly monitoring metrics, feature drift, fairness and alert statuses
    5. Export star-schema tables for the Power BI monitoring dashboard

Regenerate the Power BI tables from the project folder with:
    python -m src.churn_model
"""

from __future__ import annotations

import os
import urllib.request
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier

RANDOM_STATE = 42
TARGET = "Exited"
DATA_FILE = "Churn_Modelling.csv"
DATA_URL = ("https://raw.githubusercontent.com/sagnikghoshcr7/Bank-Customer-Churn-Prediction/"
            "master/Churn_Modelling.csv")

# NumOfProducts is treated as a category: churn is 28% with 1 product, 8% with 2, and 83%+ with 3-4
CATEGORICAL = ["Geography", "NumOfProducts"]
NUMERIC = ["CreditScore", "Tenure", "Balance", "HasCrCard", "IsActiveMember", "EstimatedSalary"]
FEATURES = CATEGORICAL + NUMERIC
PROTECTED = ["Gender", "Age"]          # not used by the model; monitored for fairness
MONITORED = ["CreditScore", "Tenure", "Balance", "NumOfProducts", "IsActiveMember", "EstimatedSalary",
             "Geography", "HasCrCard", "Age"]   # Age is monitored as a population check, not a model input

N_MONTHS, CUSTOMERS_PER_MONTH = 12, 1000
MONTH_START = pd.Timestamp("2025-01-01")

# Alert thresholds: (amber, red). AUC and top-decile precision are compared with development values.
THRESHOLDS = {
    "auc_drop": (0.03, 0.05),               # AUC below development by more than this
    "psi": (0.10, 0.25),                    # score population stability index
    "calibration_gap": (0.03, 0.05),        # |actual churn - average predicted|
    "top_decile_precision_drop": (0.05, 0.10),
    "max_feature_psi": (0.10, 0.25),        # largest PSI among the model's input features
}


# --------------------------------------------------------------------------
# 1. Data and models
# --------------------------------------------------------------------------
def load_raw(data_dir: str) -> pd.DataFrame:
    path = os.path.join(data_dir, DATA_FILE)
    if not os.path.exists(path):
        os.makedirs(data_dir, exist_ok=True)
        urllib.request.urlretrieve(DATA_URL, path)
    return pd.read_csv(path)


def age_band(age) -> pd.Series:
    return pd.cut(age, [0, 29, 39, 49, 59, 120], labels=["18–29", "30–39", "40–49", "50–59", "60+"]).astype(str)


def _prep(scale: bool) -> ColumnTransformer:
    return ColumnTransformer([("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
                              ("num", StandardScaler() if scale else "passthrough", NUMERIC)])


def candidate_models() -> dict[str, Pipeline]:
    """The four models compared, each in the same preprocessing pipeline."""
    return {
        "Logistic regression": Pipeline([("prep", _prep(True)), ("model", LogisticRegression(max_iter=2000))]),
        "Decision tree": Pipeline([("prep", _prep(False)), ("model", DecisionTreeClassifier(
            max_depth=5, min_samples_leaf=50, random_state=RANDOM_STATE))]),
        "Random forest": Pipeline([("prep", _prep(False)), ("model", RandomForestClassifier(
            n_estimators=300, min_samples_leaf=20, max_features=0.5, n_jobs=-1, random_state=RANDOM_STATE))]),
        "Gradient boosting": Pipeline([("prep", _prep(False)), ("model", HistGradientBoostingClassifier(
            learning_rate=0.1, max_depth=3, min_samples_leaf=20, random_state=RANDOM_STATE))]),
    }


@dataclass
class ChurnBundle:
    model: Pipeline
    model_name: str
    comparison: pd.DataFrame
    train: pd.DataFrame
    test: pd.DataFrame          # with "p" column
    dev_auc: float
    dev_top_decile_precision: float
    train_scores: np.ndarray


def top_decile_precision(y, p) -> float:
    """Churn rate among the 10% of customers with the highest predicted probability."""
    y, p = np.asarray(y), np.asarray(p)
    k = max(1, int(round(0.1 * len(p))))
    return float(y[np.argsort(-p)[:k]].mean())


def train(data_dir: str) -> ChurnBundle:
    d = load_raw(data_dir)
    train_df, test_df = train_test_split(d, test_size=0.2, stratify=d[TARGET], random_state=RANDOM_STATE)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    rows, fitted = [], {}
    for name, pipe in candidate_models().items():
        cv_auc = cross_val_score(pipe, train_df[FEATURES], train_df[TARGET], cv=cv, scoring="roc_auc").mean()
        pipe.fit(train_df[FEATURES], train_df[TARGET])
        p = pipe.predict_proba(test_df[FEATURES])[:, 1]
        rows.append({"model": name, "cv_auc": cv_auc, "test_auc": roc_auc_score(test_df[TARGET], p),
                     "test_top_decile_precision": top_decile_precision(test_df[TARGET], p)})
        fitted[name] = pipe
    comparison = pd.DataFrame(rows)
    best = comparison.loc[comparison["cv_auc"].idxmax(), "model"]
    comparison["selected"] = comparison["model"] == best
    model = fitted[best]
    test_df = test_df.copy()
    test_df["p"] = model.predict_proba(test_df[FEATURES])[:, 1]
    return ChurnBundle(model=model, model_name=best, comparison=comparison, train=train_df, test=test_df,
                       dev_auc=roc_auc_score(test_df[TARGET], test_df["p"]),
                       dev_top_decile_precision=top_decile_precision(test_df[TARGET], test_df["p"]),
                       train_scores=model.predict_proba(train_df[FEATURES])[:, 1])


# --------------------------------------------------------------------------
# 2. Simulated production year
# --------------------------------------------------------------------------
def simulate_production(b: ChurnBundle, seed: int = 7) -> pd.DataFrame:
    """A SIMULATED year of production scoring, drawn from the held-out test customers.

    Months 1-6: stable (customers drawn at random).
    Months 7-12: population drift. Customers from Germany and inactive customers become
        progressively more common (sampling weights rise each month), as if a marketing
        push or branch change shifted the customer mix.
    Months 10-12: a simulated market event. A competitor launches a high-rate savings
        account; a growing share of non-churning customers with balances above 100K leave
        (15%, 25%, 35%). The model has never seen this behaviour.
    """
    rng = np.random.default_rng(seed)
    pool = b.test.reset_index(drop=True)
    out = []
    for m in range(1, N_MONTHS + 1):
        w = np.ones(len(pool))
        if m >= 7:
            step = m - 6
            w *= np.where(pool["Geography"] == "Germany", 1 + 0.35 * step, 1.0)
            w *= np.where(pool["IsActiveMember"] == 0, 1 + 0.25 * step, 1.0)
        idx = rng.choice(len(pool), CUSTOMERS_PER_MONTH, replace=True, p=w / w.sum())
        month = pool.iloc[idx].copy()
        month["month_id"] = m
        month["churned"] = month[TARGET].values
        if m >= 10:
            share = {10: 0.15, 11: 0.25, 12: 0.35}[m]
            at_risk = (month["Balance"] > 100_000) & (month["churned"] == 0)
            flip = at_risk & (rng.random(len(month)) < share)
            month.loc[flip, "churned"] = 1
        out.append(month)
    prod = pd.concat(out, ignore_index=True)
    prod["p"] = b.model.predict_proba(prod[FEATURES])[:, 1]
    prod["age_band"] = age_band(prod["Age"])
    return prod


# --------------------------------------------------------------------------
# 3. Monitoring metrics
# --------------------------------------------------------------------------
def psi(expected, actual, categorical: bool = False, n_bins: int = 10) -> float:
    """Population stability index: sum over bins of (actual% - expected%) x ln(actual% / expected%)."""
    expected, actual = pd.Series(expected), pd.Series(actual)
    if categorical:
        e = expected.value_counts(normalize=True)
        a = actual.value_counts(normalize=True).reindex(e.index, fill_value=0)
    else:
        edges = np.unique(np.quantile(expected, np.linspace(0, 1, n_bins + 1)))
        edges[0], edges[-1] = -np.inf, np.inf
        e = pd.cut(expected, edges).value_counts(normalize=True, sort=False)
        a = pd.cut(actual, edges).value_counts(normalize=True, sort=False).reindex(e.index, fill_value=0)
    e, a = e.clip(lower=1e-4), a.clip(lower=1e-4)
    return float(((a - e) * np.log(a / e)).sum())


def status(value: float, amber: float, red: float) -> str:
    return "Red" if value > red else ("Amber" if value > amber else "Green")


def monthly_metrics(b: ChurnBundle, prod: pd.DataFrame) -> pd.DataFrame:
    drift = feature_drift(b, prod)
    max_input_psi = drift[drift["model_input"]].groupby("month_id")["psi"].max()
    rows = []
    for m, g in prod.groupby("month_id"):
        auc = roc_auc_score(g["churned"], g["p"])
        tdp = top_decile_precision(g["churned"], g["p"])
        gap = g["churned"].mean() - g["p"].mean()
        score_psi = psi(b.train_scores, g["p"])
        r = {"month_id": m, "customers": len(g), "avg_predicted": g["p"].mean(), "actual_churn": g["churned"].mean(),
             "calibration_gap": gap, "auc": auc, "auc_drop": b.dev_auc - auc, "top_decile_precision": tdp,
             "top_decile_precision_drop": b.dev_top_decile_precision - tdp, "score_psi": score_psi,
             "max_feature_psi": max_input_psi[m]}
        r["auc_status"] = status(r["auc_drop"], *THRESHOLDS["auc_drop"])
        r["psi_status"] = status(score_psi, *THRESHOLDS["psi"])
        r["calibration_status"] = status(abs(gap), *THRESHOLDS["calibration_gap"])
        r["top_decile_status"] = status(r["top_decile_precision_drop"], *THRESHOLDS["top_decile_precision_drop"])
        r["feature_drift_status"] = status(r["max_feature_psi"], *THRESHOLDS["max_feature_psi"])
        levels = [r[k] for k in ("auc_status", "psi_status", "calibration_status", "top_decile_status",
                                 "feature_drift_status")]
        r["overall_status"] = "Red" if "Red" in levels else ("Amber" if "Amber" in levels else "Green")
        rows.append(r)
    return pd.DataFrame(rows)


def feature_drift(b: ChurnBundle, prod: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for m, g in prod.groupby("month_id"):
        for f in MONITORED:
            cat = f in ("Geography", "NumOfProducts", "IsActiveMember", "HasCrCard")
            v = psi(b.train[f], g[f], categorical=cat)
            rows.append({"month_id": m, "feature": f, "psi": v, "status": status(v, *THRESHOLDS["psi"]),
                         "model_input": f in FEATURES})
    return pd.DataFrame(rows)


def fairness(prod: pd.DataFrame) -> pd.DataFrame:
    """Per month and group: average predicted vs actual churn, and share flagged (top 10% of scores)."""
    prod = prod.copy()
    prod["flagged"] = prod.groupby("month_id")["p"].transform(lambda s: s >= s.quantile(0.9)).astype(int)
    rows = []
    for dim, col in [("Gender", "Gender"), ("Age band", "age_band"), ("Geography", "Geography")]:
        for (m, grp), g in prod.groupby(["month_id", col]):
            rows.append({"month_id": m, "dimension": dim, "group": grp, "customers": len(g),
                         "avg_predicted": g["p"].mean(), "actual_churn": g["churned"].mean(),
                         "flagged_share": g["flagged"].mean()})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 4. Power BI export
# --------------------------------------------------------------------------
PHASES = {**{m: "Stable" for m in range(1, 7)}, **{m: "Population drift" for m in range(7, 10)},
          **{m: "Drift + market event" for m in range(10, 13)}}


def powerbi_tables(b: ChurnBundle, prod: pd.DataFrame) -> dict[str, pd.DataFrame]:
    months = pd.DataFrame({"month_id": range(1, N_MONTHS + 1)})
    months["month_start"] = [(MONTH_START + pd.DateOffset(months=m - 1)).date() for m in months["month_id"]]
    months["month_label"] = [pd.Timestamp(d).strftime("%b %Y") for d in months["month_start"]]
    months["phase"] = months["month_id"].map(PHASES)

    p = prod.copy()
    p["flagged_top_decile"] = p.groupby("month_id")["p"].transform(lambda s: s >= s.quantile(0.9)).astype(int)
    p["risk_band"] = pd.cut(p["p"], [-0.01, 0.10, 0.25, 0.50, 1.01], labels=["Low", "Medium", "High", "Very high"]).astype(str)
    scored = pd.DataFrame({
        "month_id": p["month_id"], "customer_id": p["CustomerId"], "geography": p["Geography"], "gender": p["Gender"],
        "age": p["Age"], "age_band": p["age_band"], "credit_score": p["CreditScore"], "tenure_years": p["Tenure"],
        "balance": p["Balance"].round(2), "products": p["NumOfProducts"], "has_credit_card": p["HasCrCard"],
        "is_active_member": p["IsActiveMember"], "estimated_salary": p["EstimatedSalary"].round(2),
        "churn_probability": p["p"].round(4), "risk_band": p["risk_band"],
        "risk_band_order": p["risk_band"].map({"Low": 1, "Medium": 2, "High": 3, "Very high": 4}),
        "flagged_top_decile": p["flagged_top_decile"], "churned": p["churned"]})

    thresholds = pd.DataFrame([
        {"metric": "AUC drop vs development", "amber_above": 0.03, "red_above": 0.05,
         "why": "Ranking quality: can the model still tell churners from stayers?"},
        {"metric": "Score PSI", "amber_above": 0.10, "red_above": 0.25,
         "why": "Population drift: are we scoring a different customer mix than the model was built on?"},
        {"metric": "Calibration gap (absolute)", "amber_above": 0.03, "red_above": 0.05,
         "why": "Are predicted churn rates still close to actual churn?"},
        {"metric": "Top-decile precision drop", "amber_above": 0.05, "red_above": 0.10,
         "why": "Campaign efficiency: are the customers we target still the ones who leave?"},
        {"metric": "Largest input-feature PSI", "amber_above": 0.10, "red_above": 0.25,
         "why": "Early warning: has any model input shifted, even before the score does?"},
    ])
    comparison = b.comparison.copy()
    monitoring = monthly_metrics(b, prod)
    return {"months": months, "monitoring_monthly": monitoring.round(4),
            "monitoring_status": status_long(monitoring).round(4),
            "feature_drift": feature_drift(b, prod).round(4), "fairness_monthly": fairness(prod).round(4),
            "scored_customers": scored, "thresholds": thresholds, "model_comparison": comparison.round(4)}


# The five checks in display order: (name shown in Power BI = thresholds[metric], value column, status column)
CHECKS = [("AUC drop vs development", "auc_drop", "auc_status"),
          ("Score PSI", "score_psi", "psi_status"),
          ("Calibration gap (absolute)", "calibration_gap", "calibration_status"),
          ("Top-decile precision drop", "top_decile_precision_drop", "top_decile_status"),
          ("Largest input-feature PSI", "max_feature_psi", "feature_drift_status")]
STATUS_RANK = {"Green": 1, "Amber": 2, "Red": 3}


def status_long(monitoring: pd.DataFrame) -> pd.DataFrame:
    """One row per month x check: the shape a Power BI status grid (matrix) needs."""
    rows = []
    for _, r in monitoring.iterrows():
        for order, (check, value_col, status_col) in enumerate(CHECKS, start=1):
            rows.append({"month_id": int(r["month_id"]), "check": check, "check_order": order,
                         "value": r[value_col], "status": r[status_col], "status_rank": STATUS_RANK[r[status_col]]})
    return pd.DataFrame(rows)


def export_powerbi(out_dir: str, tables: dict[str, pd.DataFrame]) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for name, t in tables.items():
        t.to_csv(os.path.join(out_dir, f"{name}.csv"), index=False)


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bundle = train(os.path.join(root, "data"))
    production = simulate_production(bundle)
    export_powerbi(os.path.join(root, "powerbi", "data"), powerbi_tables(bundle, production))
    print(monthly_metrics(bundle, production)[["month_id", "auc", "score_psi", "calibration_gap", "overall_status"]])
