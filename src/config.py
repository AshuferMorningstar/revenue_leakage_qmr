from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    # Tolerance: mismatch if abs_delta > max(tolerance_abs, tolerance_pct * transaction_amt)
    tolerance_abs: float = 1.0
    tolerance_pct: float = 0.01  # 1%

    # Column names expected in transactions.csv
    col_transaction_amt: str = "transaction_amt"
    col_reported_amt: str = "reported_amt"
    col_customer_id: str = "customer_id"
    col_invoice_id: str = "invoice_id"
    col_transaction_date: str = "transaction_date"
    col_currency: str = "currency"

    @property
    def data_raw_csv(self) -> Path:
        return Path("data") / "raw" / "transactions.csv"

    @property
    def data_processed_excel(self) -> Path:
        return Path("data") / "processed" / "leakage_report.xlsx"

    @property
    def excel_template_path(self) -> Path:
        return Path("reports") / "templates" / "qmr_template.xlsx"

    @property
    def docx_output_path(self) -> Path:
        return Path("reports") / "QMR_Process_Improvement.docx"

