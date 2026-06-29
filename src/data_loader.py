import random
from dataclasses import asdict
from pathlib import Path
from typing import Tuple

import pandas as pd

from .config import Config


REQUIRED_COLS = [
    "transaction_amt",
    "reported_amt",
    "customer_id",
    "invoice_id",
    "transaction_date",
    "currency",
]


def _ensure_dirs(cfg: Config) -> None:
    cfg.data_raw_csv.parent.mkdir(parents=True, exist_ok=True)
    cfg.data_processed_excel.parent.mkdir(parents=True, exist_ok=True)
    cfg.docx_output_path.parent.mkdir(parents=True, exist_ok=True)
    (Path("reports") / "templates").mkdir(parents=True, exist_ok=True)


def _generate_mock_transactions_csv(cfg: Config, path: Path, seed: int = 42) -> Path:
    """Create mock Q1–Q2 2026 CSV with controllable mismatch rates."""
    random.seed(seed)

    currencies = ["USD", "EUR", "GBP", "INR"]
    customer_ids = [f"C{str(i).zfill(5)}" for i in range(1, 401)]

    rows = []

    # Q1-Q2 2026: Jan 1 .. Jun 30
    date_start = pd.Timestamp("2026-01-01")
    date_end = pd.Timestamp("2026-06-30")
    total_days = (date_end - date_start).days + 1

    n_rows = 2500
    mismatch_rate = 0.18  # 18% have introduced leakage/mismatch

    for i in range(n_rows):
        day_offset = random.randint(0, total_days - 1)
        tx_date = (date_start + pd.Timedelta(days=day_offset)).date().isoformat()

        currency = random.choice(currencies)
        customer_id = random.choice(customer_ids)
        invoice_id = f"INV{random.randint(100000, 999999)}"

        # base amount distribution by currency
        base = {
            "USD": random.uniform(80, 2500),
            "EUR": random.uniform(70, 2200),
            "GBP": random.uniform(60, 2100),
            "INR": random.uniform(5000, 180000),
        }[currency]

        # Reported amount usually equals transaction amount
        transaction_amt = round(base, 2)

        if random.random() < mismatch_rate:
            # Create an out-of-tolerance delta with some randomness and direction
            # 60% under-reported, 40% over-reported (typical leakage patterns)
            direction = -1 if random.random() < 0.6 else 1
            # delta magnitude: between 1% and 6% of transaction, plus sometimes big fixed deltas
            pct_delta = random.uniform(0.012, 0.06)
            fixed_delta = random.choice([0.0, 5.0, 25.0, 100.0])
            delta = direction * (transaction_amt * pct_delta + fixed_delta)
        else:
            # small noise within tolerance
            delta = random.uniform(-0.3, 0.3)  # small cents/dollars

        reported_amt = round(transaction_amt + delta, 2)

        rows.append(
            {
                "transaction_amt": transaction_amt,
                "reported_amt": reported_amt,
                "customer_id": customer_id,
                "invoice_id": invoice_id,
                "transaction_date": tx_date,
                "currency": currency,
            }
        )

    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def load_and_validate_transactions(cfg: Config) -> Tuple[pd.DataFrame, Path]:
    """Load transactions.csv; if missing, generate mock Q1–Q2 2026 data.

    Returns: (df_validated, csv_path)
    """
    _ensure_dirs(cfg)

    csv_path: Path = cfg.data_raw_csv
    if not csv_path.exists():
        _generate_mock_transactions_csv(cfg, csv_path)

    df = pd.read_csv(csv_path)

    missing_cols = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"transactions.csv missing required columns: {missing_cols}")

    # Type conversions
    for c in [cfg.col_transaction_amt, cfg.col_reported_amt]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Datetime parsing is unstable in this environment (pandas/numpy ABI issues).
    # Use a pure-Python fallback for the expected ISO input format: YYYY-MM-DD.
    # This avoids pd.to_datetime (which is crashing with SystemError/segfaults).
    date_strs = df[cfg.col_transaction_date].astype(str)

    def _parse_iso_date(x: str):
        try:
            # Fast path for YYYY-MM-DD
            parts = x.split("-")
            if len(parts) != 3:
                return None
            y, m, d = map(int, parts)
            from datetime import date

            return date(y, m, d)
        except Exception:
            return None

    df[cfg.col_transaction_date] = date_strs.map(_parse_iso_date)

    # Basic validation summary
    invalid_numeric = int(df[[cfg.col_transaction_amt, cfg.col_reported_amt]].isna().any(axis=1).sum())
    invalid_dates = int(df[[cfg.col_transaction_date]].isna().any(axis=1).sum())


    # Drop invalid rows (portfolio-safe approach)
    df = df.dropna(subset=[cfg.col_transaction_amt, cfg.col_reported_amt, cfg.col_transaction_date]).copy()

    if df.empty:
        raise ValueError("After validation, no rows remain. Check input data constraints.")

    # Normalize date to month/quarter later in analysis
    # At this point df[cfg.col_transaction_date] is already python `date` objects (or None).


    # Ensure consistent column order
    df = df[REQUIRED_COLS]

    # Attach validation metadata for downstream reporting (optional)
    df.attrs["validation"] = {
        "invalid_numeric_dropped": invalid_numeric,
        "invalid_dates_dropped": invalid_dates,
        "rows_after_validation": len(df),
        "config": asdict(cfg) if hasattr(cfg, "__dict__") else None,
    }

    return df, csv_path

