from dataclasses import asdict
from typing import Dict, Tuple

import pandas as pd

from .config import Config


def flag_leakage(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Add delta metrics and a boolean mismatch/leakage flag."""
    df = df.copy()

    tx = df[cfg.col_transaction_amt].astype(float)
    rep = df[cfg.col_reported_amt].astype(float)

    df["delta_amt"] = rep - tx
    df["abs_delta_amt"] = df["delta_amt"].abs()

    tol_abs = float(cfg.tolerance_abs)
    tol_pct_component = cfg.tolerance_pct * tx
    df["tolerance_threshold"] = tol_abs
    # vary threshold by transaction value as well
    df["tolerance_threshold"] = tol_abs + 0 * tol_pct_component
    df["tolerance_max_threshold"] = tol_pct_component.combine(tol_abs, max)

    df["is_mismatch"] = df["abs_delta_amt"] > df["tolerance_max_threshold"]

    # classify direction (potential leakage indicator)
    # Under-reported: reported < transaction => delta negative
    df["leakage_direction"] = pd.Series([None] * len(df), index=df.index, dtype=object)
    df.loc[df["is_mismatch"] & (df["delta_amt"] < 0), "leakage_direction"] = "Under-reported (potential leakage)"
    df.loc[df["is_mismatch"] & (df["delta_amt"] > 0), "leakage_direction"] = "Over-reported / Timing mismatch"
    df.loc[df["is_mismatch"] & (df["delta_amt"] == 0), "leakage_direction"] = "Zero delta mismatch"
    df.loc[~df["is_mismatch"], "leakage_direction"] = "Within tolerance"

    # transaction_date should already be python `date` objects from the loader.
    # Avoid pandas datetime parsing in this environment.
    # Derive period strings manually.
    def _ym(d):
        if d is None:
            return None
        return f"{d.year:04d}-{d.month:02d}"

    def _q(d):
        if d is None:
            return None
        q = (d.month - 1) // 3 + 1
        return f"{d.year:04d}Q{q}"

    df["year_month"] = df[cfg.col_transaction_date].map(_ym)
    df["quarter"] = df[cfg.col_transaction_date].map(_q)


    return df


def aggregate_leakage(df_flagged: pd.DataFrame, cfg: Config) -> Dict[str, pd.DataFrame]:
    """Return multiple aggregate tables for Excel."""
    mismatch_df = df_flagged[df_flagged["is_mismatch"]].copy()

    # KPI: sums (leakage is negative delta sum for under-reported; we also report absolute delta)
    leakage_total_under = float(mismatch_df.loc[mismatch_df["delta_amt"] < 0, "delta_amt"].sum())

    # Use leakage magnitude as absolute under-reported delta
    leakage_magnitude_under = float((-mismatch_df.loc[mismatch_df["delta_amt"] < 0, "delta_amt"]).sum())

    kpi = pd.DataFrame(
        [
            {
                "total_transactions": len(df_flagged),
                "mismatch_count": int(df_flagged["is_mismatch"].sum()),
                "mismatch_rate": float(df_flagged["is_mismatch"].mean()),
                "leakage_underreported_total": leakage_magnitude_under,
                "sum_delta_all_mismatches": float(mismatch_df["delta_amt"].sum()),
            }
        ]
    )

    by_month = (
        mismatch_df.groupby(["year_month", cfg.col_currency])
        .agg(
            mismatch_count=("is_mismatch", "sum"),
            leakage_underreported_total=("delta_amt", lambda s: (-s[s < 0]).sum()),
            abs_mismatch_total=("abs_delta_amt", "sum"),
        )
        .reset_index()
        .sort_values(["year_month", cfg.col_currency])
    )

    by_quarter = (
        mismatch_df.groupby(["quarter", cfg.col_currency])
        .agg(
            mismatch_count=("is_mismatch", "sum"),
            leakage_underreported_total=("delta_amt", lambda s: (-s[s < 0]).sum()),
            abs_mismatch_total=("abs_delta_amt", "sum"),
        )
        .reset_index()
        .sort_values(["quarter", cfg.col_currency])
    )

    top_invoices = (
        mismatch_df.sort_values("abs_delta_amt", ascending=False)
        .head(20)[
            [
                cfg.col_invoice_id,
                cfg.col_customer_id,
                cfg.col_transaction_date,
                cfg.col_currency,
                cfg.col_transaction_amt,
                cfg.col_reported_amt,
                "delta_amt",
                "abs_delta_amt",
                "leakage_direction",
            ]
        ]
    )

    return {
        "kpi": kpi,
        "by_month": by_month,
        "by_quarter": by_quarter,
        "top_invoices": top_invoices,
    }

