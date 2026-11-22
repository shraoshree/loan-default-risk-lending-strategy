"""Backtest approval policies on mature, previously originated loans."""
import argparse
import json
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

NUMERIC = ["loan_amnt", "annual_inc", "dti", "fico_range_low", "open_acc"]
CATEGORICAL = ["home_ownership", "purpose"]
LABELS = {"Fully Paid": 0, "Charged Off": 1}
ADDITIONAL_NUMERIC = ["revol_util", "inq_last_6mths", "delinq_2yrs",
                      "emp_length_years", "credit_history_years"]
ADDITIONAL_RAW = ["revol_util", "inq_last_6mths", "delinq_2yrs", "emp_length", "earliest_cr_line"]
FUNDING_YEARS = 1.5
FUNDING_RATE = .04
OPERATING_COST = 150.
CASH_FIELDS = ["funded_amnt", "total_rec_prncp", "total_rec_int", "recoveries",
               "collection_recovery_fee"]
COLUMNS = NUMERIC + CATEGORICAL + ["id", "loan_status", "issue_d", "term", "int_rate"]
SQL = Path(__file__).with_name("policy.sql").read_text()


def demo_data():
    rng = np.random.default_rng(47)
    n = 12000
    fico = rng.integers(630, 810, n)
    dti = rng.uniform(2, 37, n)
    risk = 1 / (1 + np.exp(2.2 + (fico - 700) / 40 - (dti - 18) / 15))
    return pd.DataFrame({
        "id": np.arange(n), "loan_amnt": rng.integers(2000, 30000, n),
        "annual_inc": rng.lognormal(11, .55, n), "dti": dti,
        "fico_range_low": fico, "open_acc": rng.integers(2, 24, n),
        "home_ownership": rng.choice(["RENT", "OWN", "MORTGAGE"], n),
        "purpose": rng.choice(["debt_consolidation", "credit_card", "other"], n),
        "issue_d": rng.choice(pd.date_range("2013-01-01", "2015-12-01", freq="MS")
                              .strftime("%b-%Y").to_numpy(), n),
        "term": "36 months", "int_rate": 8 + 24 * risk,
        "loan_status": np.where(rng.random(n) < risk, "Charged Off", "Fully Paid"),
    })


def prepare(raw):
    data = raw.copy()
    data["month"] = pd.to_datetime(data["issue_d"], format="%b-%Y", errors="coerce")
    data["defaulted"] = data["loan_status"].map(LABELS)
    data["apr"] = pd.to_numeric(data["int_rate"].astype(str).str.rstrip("%"),
                                errors="coerce") / 100
    for column in NUMERIC:
        data[column] = pd.to_numeric(data[column], errors="coerce").replace(
            [np.inf, -np.inf], np.nan)
    if set(ADDITIONAL_RAW).issubset(data.columns):
        data["revol_util"] = pd.to_numeric(
            data["revol_util"].astype(str).str.rstrip("%"), errors="coerce")
        employment = data["emp_length"].astype(str).str.extract(r"(\d+)")[0]
        data["emp_length_years"] = pd.to_numeric(employment, errors="coerce")
        data.loc[data["emp_length"].eq("< 1 year"), "emp_length_years"] = 0
        earliest = pd.to_datetime(data["earliest_cr_line"], format="%b-%Y", errors="coerce")
        history_months = 12 * (data["month"].dt.year - earliest.dt.year)
        history_months += data["month"].dt.month - earliest.dt.month
        data["credit_history_years"] = history_months.where(history_months.ge(0)) / 12
        data[ADDITIONAL_NUMERIC] = data[ADDITIONAL_NUMERIC].apply(
            pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    valid = (data["term"].astype(str).str.strip().eq("36 months")
             & data["loan_amnt"].gt(0) & data["apr"].between(.00001, 1)
             & data["month"].between("2013-01-01", "2015-12-31"))
    return data.loc[valid].dropna(subset=["id", "defaulted"]).drop_duplicates("id")


def split(data):
    return [data.loc[data["month"].dt.year.eq(year)] for year in (2013, 2014, 2015)]


def model(numeric_columns=NUMERIC):
    numeric = make_pipeline(SimpleImputer(strategy="median"), StandardScaler())
    category = make_pipeline(SimpleImputer(strategy="most_frequent"),
                             OneHotEncoder(handle_unknown="ignore"))
    features = ColumnTransformer([("numeric", numeric, numeric_columns),
                                  ("category", category, CATEGORICAL)])
    return make_pipeline(features, LogisticRegression(max_iter=1000))


def score(frame, estimator):
    amount = frame["loan_amnt"].to_numpy()
    rate = frame["apr"].to_numpy() / 12
    # Contractual interest over 36 months assuming scheduled payments.
    payment = amount * rate / -np.expm1(-36 * np.log1p(rate))
    # Historical cash flows are used only for outcome reporting.
    if set(CASH_FIELDS).issubset(frame.columns):
        funded, principal, interest, recovery, fee = (
            pd.to_numeric(frame[column], errors="coerce").to_numpy() for column in CASH_FIELDS)
        observed_cash_margin = principal + interest + recovery - fee - funded
    else:
        observed_cash_margin = np.full(len(frame), np.nan)
    return pd.DataFrame({"pd": estimator.predict_proba(frame)[:, 1],
                         "defaulted": frame["defaulted"].to_numpy(),
                         "amount": amount, "interest": 36 * payment - amount,
                         "funding": amount * FUNDING_RATE * FUNDING_YEARS,
                         "observed_cash_margin": observed_cash_margin})


def evaluate(scored, policies):
    with sqlite3.connect(":memory:") as db:
        scored.to_sql("scored", db, index=False)
        pd.DataFrame(policies, columns=["name", "threshold", "interest_multiplier",
                                        "lgd", "funding_multiplier", "operating_cost"]
                     ).to_sql("policies", db, index=False)
        return pd.read_sql_query(SQL, db)


def metrics(frame, pd_values):
    labels = frame["defaulted"]
    return {"roc_auc": roc_auc_score(labels, pd_values),
            "average_precision": average_precision_score(labels, pd_values),
            "brier": brier_score_loss(labels, pd_values)}


def break_even(scored, threshold):
    retained = scored["pd"].le(threshold)
    rows = []
    for name, loans in (("approve_all", scored), ("selected_threshold", scored.loc[retained]),
                        ("excluded_by_threshold", scored.loc[~retained])):
        count = len(loans)
        gross = loans["observed_cash_margin"].sum()
        exposure = loans["amount"].sum() * FUNDING_YEARS
        rows.append({
            "group": name, "loans": count, "gross_cash_margin": gross,
            "break_even_cost_per_funded_loan": gross / count if count else np.nan,
            "break_even_funding_rate_at_150_opex":
                (gross - OPERATING_COST * count) / exposure if exposure else np.nan,
            "break_even_opex_at_4pct_funding":
                (gross - FUNDING_RATE * exposure) / count if count else np.nan,
        })
    return pd.DataFrame(rows)


def select_threshold(validation_scores, baseline):
    thresholds = np.linspace(.025, .50, 20)
    candidates = [(f"{limit:.3f}", limit, 1., .65, 1., OPERATING_COST)
                  for limit in thresholds]
    grid = evaluate(validation_scores, [baseline, *candidates])
    feasible = grid.loc[grid["approval_rate"].ge(.50)]
    choice = str(feasible.iloc[0]["name"])
    threshold = 1. if choice == "approve_all" else float(choice)
    return grid, feasible, threshold


def run(raw, output, source):
    train, validation, test = split(prepare(raw))
    for cohort in (train, validation, test):
        if cohort["defaulted"].nunique() != 2:
            raise ValueError("Each calendar-year cohort needs paid and charged-off loans.")
    estimator = model().fit(train, train["defaulted"])
    dummy = DummyClassifier(strategy="prior").fit(train, train["defaulted"])
    validation_scores = score(validation, estimator)
    test_scores = score(test, estimator)

    baseline = ("approve_all", 1., 1., .65, 1., OPERATING_COST)
    grid, feasible, threshold = select_threshold(validation_scores, baseline)
    policies = [baseline, ("selected_threshold", threshold, 1., .65, 1., OPERATING_COST),
                ("selected_higher_interest", threshold, 1.10, .65, 1., OPERATING_COST),
                ("selected_stress", threshold, 1., .80, 1.50, OPERATING_COST),
                ("approve_all_stress", 1., 1., .80, 1.50, OPERATING_COST)]
    results = evaluate(test_scores, policies)
    test_scores["risk_band"] = pd.cut(test_scores["pd"], [0, .10, .20, 1.],
                                     labels=["0–10%", ">10–20%", ">20%"],
                                     include_lowest=True)
    bands = test_scores.groupby("risk_band", observed=True).agg(
        loans=("pd", "size"), mean_pd=("pd", "mean"), observed_default_rate=("defaulted", "mean"))
    output.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(":memory:") as db:
        segments_input = test_scores.assign(
            purpose=test["purpose"].to_numpy(), home_ownership=test["home_ownership"].to_numpy())
        segments_input.to_sql("scored", db, index=False)
        segments = pd.read_sql_query(Path(__file__).with_name("segments.sql").read_text(),
                                     db, params={"threshold": threshold})
    segments.to_csv(output / "test_segments.csv", index=False)
    preprocess = estimator.named_steps["columntransformer"]
    coefficients = estimator.named_steps["logisticregression"].coef_[0]
    drivers = pd.DataFrame({"feature": preprocess.get_feature_names_out(),
                            "log_odds_coefficient": coefficients,
                            "odds_multiplier": np.exp(coefficients)})
    drivers.sort_values("log_odds_coefficient").to_csv(output / "risk_drivers.csv", index=False)
    if test_scores["observed_cash_margin"].notna().all():
        break_even(test_scores, threshold).to_csv(output / "cost_break_even.csv", index=False)
    grid.to_csv(output / "validation_frontier.csv", index=False)
    results.to_csv(output / "test_policies.csv", index=False)
    bands.to_csv(output / "test_risk_bands.csv")
    summary = {"source": source, "cohort_counts": dict(zip(("train", "validation", "test"),
                map(len, (train, validation, test)))), "selected_threshold": threshold,
               "logistic": metrics(test, test_scores["pd"]),
               "base_rate_model": metrics(test, dummy.predict_proba(test)[:, 1])}
    summary["cohort_chargeoff_rates"] = {
        str(year): cohort["defaulted"].mean() for year, cohort in
        zip((2013, 2014, 2015), (train, validation, test))}
    summary["logistic_validation"] = metrics(validation, validation_scores["pd"])
    if set(ADDITIONAL_NUMERIC).issubset(train.columns):
        if not train[ADDITIONAL_NUMERIC].notna().any().all():
            raise ValueError("Each challenger feature requires observed training values.")
        challenger = model(NUMERIC + ADDITIONAL_NUMERIC).fit(train, train["defaulted"])
        challenger_validation = score(validation, challenger)
        _, _, challenger_threshold = select_threshold(challenger_validation, baseline)
        challenger_test = score(test, challenger)
        summary["challenger"] = {
            "validation": metrics(validation, challenger_validation["pd"]),
            "holdout": metrics(test, challenger_test["pd"]),
            "selected_threshold": challenger_threshold}
        evaluate(challenger_test, [baseline, ("challenger_threshold", challenger_threshold,
                 1., .65, 1., OPERATING_COST)]).to_csv(
                     output / "challenger_test_policies.csv", index=False)
    (output / "model_metrics.json").write_text(json.dumps(summary, indent=2) + "\n")

    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    ax.plot(grid.sort_values("approval_rate")["approval_rate"] * 100,
            grid.sort_values("approval_rate")["profit_per_evaluated_loan"], "o-",
            color="#176b70", markersize=4)
    selected = feasible.iloc[0]
    ax.scatter(selected["approval_rate"] * 100, selected["profit_per_evaluated_loan"],
               marker="D", color="#aa4f25", label="Selected policy", zorder=3)
    ax.axvline(50, color="#666666", linestyle="--", label="Minimum approval rate")
    ax.set(title=f"Validation policy trade-off | {source}",
           xlabel="Previously originated loans retained (%)",
           ylabel="Modeled profit per evaluated loan ($)")
    ax.legend(frameon=False)
    fig.savefig(output / "validation_frontier.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    source = cli.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", type=Path, help="LendingClub accepted-loans CSV or CSV.gz")
    source.add_argument("--demo", action="store_true", help="Run on deterministic synthetic data")
    cli.add_argument("--output", type=Path, default=Path("outputs"))
    args = cli.parse_args()
    if args.demo:
        raw = demo_data()
    else:
        chunks = pd.read_csv(
            args.csv, usecols=lambda column: column in COLUMNS + CASH_FIELDS + ADDITIONAL_RAW,
            dtype={"id": str}, chunksize=100_000, low_memory=False)
        raw = pd.concat([
            chunk.loc[chunk["issue_d"].str.endswith(("-2013", "-2014", "-2015"), na=False)
                      & chunk["term"].str.strip().eq("36 months")
                      & chunk["loan_status"].isin(LABELS)]
            for chunk in chunks
        ], ignore_index=True)
    run(raw, args.output, "Synthetic demo" if args.demo else "LendingClub")
