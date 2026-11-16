"""
Automated checks for the churn model, the monitoring logic and the Power BI export.

Run from the project folder with:
    pytest tests/
"""

import io
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.churn_model import (FEATURES, PROTECTED, THRESHOLDS, psi, powerbi_tables,  # noqa: E402
                             simulate_production, status, train)

PBI = ROOT / "powerbi"
TABLES = ["months", "monitoring_monthly", "monitoring_status", "feature_drift", "fairness_monthly",
          "scored_customers", "thresholds", "model_comparison"]


@pytest.fixture(scope="module")
def bundle():
    return train(str(ROOT / "data"))


@pytest.fixture(scope="module")
def tables(bundle):
    return powerbi_tables(bundle, simulate_production(bundle))


@pytest.fixture(scope="module")
def exported():
    return {name: pd.read_csv(PBI / "data" / f"{name}.csv") for name in TABLES}


# ---------- Model ----------

def test_protected_attributes_not_used():
    assert not set(PROTECTED) & set(FEATURES)


def test_selected_model_and_benchmarks(bundle):
    assert bundle.model_name == "Gradient boosting"
    assert bundle.comparison.loc[bundle.comparison["selected"], "cv_auc"].item() == bundle.comparison["cv_auc"].max()
    assert bundle.dev_auc == pytest.approx(0.797, abs=0.001)
    assert bundle.dev_top_decile_precision == pytest.approx(0.665, abs=0.001)


# ---------- Monitoring logic ----------

def test_psi_is_zero_for_identical_and_large_for_shifted():
    s = pd.Series(range(1000), dtype=float)
    assert psi(s, s) == pytest.approx(0, abs=1e-9)
    assert psi(s, s + 500) > 0.25


def test_status_boundaries():
    amber, red = THRESHOLDS["psi"]
    assert status(0.10, amber, red) == "Green"      # "above" the threshold, not equal to it
    assert status(0.11, amber, red) == "Amber"
    assert status(0.26, amber, red) == "Red"


def test_simulated_year_story(exported):
    """Green Jan-Aug, Amber in Sep (feature drift only), Red Oct-Dec."""
    m = exported["monitoring_monthly"].set_index("month_id")
    assert list(m["overall_status"]) == ["Green"] * 8 + ["Amber"] + ["Red"] * 3
    assert m.loc[9, "feature_drift_status"] == "Amber" and m.loc[9, "psi_status"] == "Green"
    assert (m["top_decile_status"] == "Green").all()


def test_status_grid_matches_monthly_table(exported):
    st, m = exported["monitoring_status"], exported["monitoring_monthly"]
    assert len(st) == 12 * 5 and st["status"].value_counts().to_dict() == {"Green": 48, "Amber": 6, "Red": 6}
    worst = st.groupby("month_id")["status_rank"].max().map({1: "Green", 2: "Amber", 3: "Red"})
    assert list(worst) == list(m.sort_values("month_id")["overall_status"])
    assert set(st["check"]) == set(exported["thresholds"]["metric"])   # the relationship in Power BI


# ---------- Power BI export ----------

def test_module_reproduces_exported_tables(tables, exported):
    """The notebook wrote powerbi/data; the module must produce the same tables."""
    for name in TABLES:
        as_csv = pd.read_csv(io.StringIO(tables[name].to_csv(index=False)))   # same round trip as the export
        pd.testing.assert_frame_equal(as_csv, exported[name],
                                      check_dtype=False, atol=1e-3, obj=name)


def test_keys_and_row_counts(exported):
    e = exported
    assert e["months"]["month_id"].is_unique and len(e["months"]) == 12
    for name in ["monitoring_monthly", "monitoring_status", "feature_drift", "fairness_monthly", "scored_customers"]:
        assert set(e[name]["month_id"]) <= set(e["months"]["month_id"]), name
    assert len(e["scored_customers"]) == 12_000
    assert e["fairness_monthly"].groupby(["month_id", "dimension"])["customers"].sum().eq(1000).all()


def test_guide_checkpoints(exported):
    """Spot-check numbers quoted in the build guide."""
    s = exported["scored_customers"]
    be = 25 / (0.30 * 500)
    target = s[s["churn_probability"] > be]
    assert len(target) == 5928
    assert round((target["churned"] * 0.30 * 500 - 25).sum()) == 202_950
    dec = exported["monitoring_monthly"].set_index("month_id").loc[12]
    assert round(dec["auc"], 3) == 0.734 and round(dec["score_psi"], 3) == 0.174


def test_theme_is_valid_json():
    theme = json.loads((PBI / "DataKritii_theme.json").read_text(encoding="utf-8"))
    assert theme["name"] == "DataKritii" and len(theme["dataColors"]) >= 6


def test_guide_only_uses_defined_measures():
    """Every measure the build guide asks for must exist in measures.dax (or be a What-if parameter)."""
    dax = (PBI / "measures.dax").read_text(encoding="utf-8")
    defined = {d.strip() for d in re.findall(r"^([A-Z][^\n=/]*?) =", dax, flags=re.M)}
    defined |= {"Offer Cost Value", "Success Rate Value", "Customer Value Value"}
    guide = (PBI / "POWERBI_BUILD_GUIDE.md").read_text(encoding="utf-8")
    pages = {"Model health", "Performance", "Drift", "Fairness", "Retention planner", "Model card"}
    not_measures = pages | {"Offer Cost", "Success Rate", "Customer Value"}
    referenced = {r for r in re.findall(r"`([A-Z][A-Za-z%\- ]+)`", guide)
                  if r not in not_measures and not r.isupper()}          # all-caps = DAX functions
    missing = referenced - defined
    assert not missing, missing
