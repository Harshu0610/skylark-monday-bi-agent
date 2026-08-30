"""
Prepare the raw Skylark spreadsheets for import into Monday.com.

This script is deliberately CONSERVATIVE. It fixes only the structural problems
that would make a Monday.com import wrong or impossible:

  1. Work Orders has its real header on row 2 (row 1 is blank).
  2. Both sheets contain repeated header rows embedded as DATA
     (e.g. a row whose "Deal Stage" cell literally contains the text "Deal Stage").
  3. Four Work Order columns are 100% empty and carry no information.
  4. Leading/trailing whitespace on text cells.

Everything else -- inconsistent statuses, missing amounts, unparseable dates,
the "Project Completed" stage that breaks the A./B./C. convention, the "BIlled"
typo -- is LEFT IN PLACE ON PURPOSE. The agent must handle real messy data at
query time; pre-solving it here would defeat the point of the assignment.

Usage:
    python scripts/prepare_for_monday.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data_clean"

DEALS_SRC = ROOT / "Deal funnel Data.xlsx"
WORK_ORDERS_SRC = ROOT / "Work_Order_Tracker Data.xlsx"

# Work Order columns that are 100% null in the source. Importing them would
# create Monday columns that can never be populated, and would tempt the agent
# into building AR/collections metrics the data cannot support.
WO_EMPTY_COLUMNS = [
    "Expected Billing Month",
    "Actual Collection Month",
    "Collection status",
    "Collection Date",
]

# Columns retained for the Work Orders board. The source has 38; these 18 are
# the ones with analytical value at this scope.
WO_KEEP_COLUMNS = [
    "Deal name masked",
    "Serial #",
    "Customer Name Code",
    "Sector",
    "Execution Status",
    "Nature of Work",
    "Type of Work",
    "BD/KAM Personnel code",
    "Probable Start Date",
    "Probable End Date",
    "Data Delivery Date",
    "Date of PO/LOI",
    "Document Type",
    "Amount in Rupees (Excl of GST) (Masked)",
    "Amount in Rupees (Incl of GST) (Masked)",
    "Billed Value in Rupees (Excl of GST.) (Masked)",
    "Amount Receivable (Masked)",
    "Invoice Status",
    "WO Status (billed)",
]


def drop_header_echo_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop rows where any cell repeats its own column name.

    These sheets were assembled by concatenating exports without stripping
    headers, so a handful of rows are the header repeated as data. Left in,
    they create phantom categories ("Sector/service" appears as a sector).
    """
    mask = pd.Series(False, index=df.index)
    for col in df.columns:
        if df[col].dtype == object:
            mask |= df[col].astype(str).str.strip() == str(col).strip()
    dropped = int(mask.sum())
    return df.loc[~mask].copy(), dropped


def strip_whitespace(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)
    return df


def format_dates(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Render date-ish columns as ISO strings so Monday's importer reads them
    unambiguously. Unparseable values are left as-is for the agent to flag."""
    for col in columns:
        if col not in df.columns:
            continue
        parsed = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
        df[col] = parsed.dt.strftime("%Y-%m-%d").where(parsed.notna(), df[col])
    return df


def prepare_deals() -> pd.DataFrame:
    df = pd.read_excel(DEALS_SRC)
    before = len(df)
    df, dropped = drop_header_echo_rows(df)
    df = strip_whitespace(df)
    df = format_dates(df, ["Close Date (A)", "Tentative Close Date", "Created Date"])

    print(f"[deals] {before} rows -> {len(df)} rows ({dropped} header-echo rows dropped)")
    print(f"[deals] columns: {len(df.columns)}")
    _report_nulls(df, "deals")
    return df


def prepare_work_orders() -> pd.DataFrame:
    # Real header is on the second row; the first row is blank.
    df = pd.read_excel(WORK_ORDERS_SRC, header=1)
    before = len(df)

    empty_found = [c for c in WO_EMPTY_COLUMNS if c in df.columns and df[c].isna().all()]
    df = df.drop(columns=empty_found)
    print(f"[work_orders] dropped {len(empty_found)} fully-empty columns: {empty_found}")

    df, dropped = drop_header_echo_rows(df)
    df = strip_whitespace(df)

    missing = [c for c in WO_KEEP_COLUMNS if c not in df.columns]
    if missing:
        print(f"[work_orders] WARNING expected columns not found: {missing}")
    keep = [c for c in WO_KEEP_COLUMNS if c in df.columns]
    df = df[keep]

    df = format_dates(
        df,
        [
            "Probable Start Date",
            "Probable End Date",
            "Data Delivery Date",
            "Date of PO/LOI",
        ],
    )

    print(f"[work_orders] {before} rows -> {len(df)} rows ({dropped} header-echo rows dropped)")
    print(f"[work_orders] columns: {len(df.columns)}")
    _report_nulls(df, "work_orders")
    return df


def _report_nulls(df: pd.DataFrame, label: str) -> None:
    """Print a null profile. This is the data-quality baseline the agent will
    later report at query time -- useful to eyeball before importing."""
    nulls = df.isna().sum()
    nulls = nulls[nulls > 0].sort_values(ascending=False)
    if nulls.empty:
        print(f"[{label}] no nulls")
        return
    print(f"[{label}] null profile (top 8):")
    for col, n in list(nulls.items())[:8]:
        print(f"          {n:>4} / {len(df):<4} ({n / len(df):>5.1%})  {col}")


def main() -> int:
    for src in (DEALS_SRC, WORK_ORDERS_SRC):
        if not src.exists():
            print(f"ERROR: source file not found: {src}", file=sys.stderr)
            return 1

    OUT_DIR.mkdir(exist_ok=True)

    deals = prepare_deals()
    print()
    work_orders = prepare_work_orders()

    deals_out = OUT_DIR / "deals_clean.csv"
    wo_out = OUT_DIR / "work_orders_clean.csv"
    deals.to_csv(deals_out, index=False, encoding="utf-8-sig")
    work_orders.to_csv(wo_out, index=False, encoding="utf-8-sig")

    print()
    print(f"Wrote {deals_out}")
    print(f"Wrote {wo_out}")
    print()
    print("Next: import these two CSVs into Monday.com as separate boards.")
    print("See README.md section 'Monday.com Setup' for the column type mapping.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
