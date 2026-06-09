"""
preprocess.py
=============
Chuyển đổi từ notebook 02_Preprocessing_Improved.ipynb → module Python thuần.

Dùng trong 2 chế độ:
  1. Offline (CLI): python preprocess.py --input data/raw/merged.csv --output data/cleaned.csv
  2. Online (import): from preprocess import preprocess_dataframe
                      df_clean = preprocess_dataframe(df_raw)
"""

from __future__ import annotations

import re
import datetime
import argparse
import logging
from pathlib import Path

import pandas as pd
import numpy as np

log = logging.getLogger(__name__)

# ─── Hằng số lịch ────────────────────────────────────────────────────────────

PUBLIC_HOLIDAYS = [
    pd.Timestamp("2025-04-07").date(),
    pd.Timestamp("2025-04-30").date(),
    pd.Timestamp("2025-05-01").date(),
    pd.Timestamp("2025-09-02").date(),
]
PUBLIC_HOLIDAYS_SET = set(PUBLIC_HOLIDAYS)

TET_EVE_START = pd.Timestamp("2025-01-12").date()
TET_START     = pd.Timestamp("2025-01-26").date()
TET_END       = pd.Timestamp("2025-02-02").date()

NEARBY_HOLIDAYS: set = set()
for _h in PUBLIC_HOLIDAYS:
    for _delta in [-3, -2, -1, 1, 2, 3]:
        _nb = (pd.Timestamp(_h) + pd.Timedelta(days=_delta)).date()
        if _nb not in PUBLIC_HOLIDAYS_SET:
            NEARBY_HOLIDAYS.add(_nb)

LUGGAGE_DEFAULTS = {
    "VietJet Air":      {"hand_luggage": 7,  "checked_baggage": 0},
    "Vietnam Airlines": {"hand_luggage": 12, "checked_baggage": 23},
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _is_holiday_encode(date) -> int:
    """0=thường | 1=cuối tuần | 2=cận lễ | 3=ngày lễ/Tết"""
    d = date.date() if hasattr(date, "date") else date
    if d in PUBLIC_HOLIDAYS_SET:
        return 3
    if d in NEARBY_HOLIDAYS:
        return 2
    if d.weekday() >= 4:   # Fri=4, Sat=5, Sun=6
        return 1
    return 0


def _convert_vn_date(date_str: str, year: int = None) -> pd.Timestamp:
    if year is None:
        year = datetime.date.today().year
    day, month = date_str.strip().split(" thg ")
    return pd.to_datetime(f"{int(day):02d}-{int(month):02d}-{year}", dayfirst=True)


def _format_luggage(string) -> int | None:
    if pd.isna(string):
        return None
    numbers = re.findall(r"\d+", str(string))
    if len(numbers) >= 2:
        return int(numbers[0]) * int(numbers[1])
    if len(numbers) == 1:
        return int(numbers[0])
    return None


# ─── Pipeline chính ───────────────────────────────────────────────────────────

def preprocess_dataframe(df: pd.DataFrame, reference_date: pd.Timestamp | None = None) -> pd.DataFrame:
    """
    Nhận DataFrame thô (cùng schema với crawler) → trả DataFrame đã clean,
    sẵn sàng đưa vào model.

    Convention lag features (FIX #7):
      sort DESCENDING days_left (3→2→1), shift(+1) = "giá ngày hôm qua khi crawl"
      price_lag1[days_left=1] = price tại days_left=2
      price_lag3[days_left=1] = price tại days_left=4 (nếu có)
      Nhất quán với _add_lag_features trong predictor.py.

    Parameters
    ----------
    df : pd.DataFrame
    reference_date : Timestamp, optional

    Returns
    -------
    pd.DataFrame
    """
    df = df.copy()
    log.info("Preprocess bắt đầu | shape=%s", df.shape)

    # ── 1. Dedup & basic cleaning ────────────────────────────────────────────
    df = df.drop_duplicates(keep="first").reset_index(drop=True)

    df["destination"] = df["destination"].replace(
        "Hà Nội (HAN)\r\nSân bay Nội Bài\r\nNhà ga 1",
        "Hà Nội (HAN)\r\nSân bay Nội Bài",
    )

    # Price
    df["price_raw"] = df["price"]

    df["price"] = df["price"].astype(str).str.extract(
        r"([\d\.]+)", expand=False
    )

    bad_rows = df[df["price"].isna()]
    if not bad_rows.empty:
        log.warning("Phát hiện %d dòng lỗi price", len(bad_rows))
        bad_rows.to_csv("bad_price_rows.csv", index=True, encoding="utf-8-sig")
        log.warning("Đã lưu: bad_price_rows.csv | Index lỗi: %s", bad_rows.index.tolist())
        df = df[df["price"].notna()].copy()

    df["price"] = (
        df["price"]
        .str.replace(".", "", regex=False)
        .astype(int)
    )

    # Time → start_hour / end_hour bins
    for col in ("start_time", "end_time"):
        df[col] = df[col].str.replace("h", ":")

    df["start_hour_raw"] = df["start_time"].str.split(":").str[0].astype(int)
    df["end_hour_raw"]   = df["end_time"].str.split(":").str[0].astype(int)

    for col, raw in [("start_hour", "start_hour_raw"), ("end_hour", "end_hour_raw")]:
        df[col] = pd.cut(
            df[raw],
            bins=[0, 3, 9, 15, 21, 24],
            labels=["EarlyMorning", "Morning", "Afternoon", "Evening", "LateNight"],
            include_lowest=True,
        )

    # trip_mins
    tp = df["trip_time"].str.extract(r"(?:(?P<hour>\d+)h)?\s*(?:(?P<minute>\d+)m)?")
    tp = tp.astype(float).fillna(0)
    df["trip_mins"] = (tp["hour"] * 60 + tp["minute"]).astype(int)

    df.drop(
        columns=["start_time", "end_time", "trip_time", "start_hour_raw", "end_hour_raw"],
        inplace=True, errors="ignore",
    )

    # ── 2. Date conversion & days_left ───────────────────────────────────────
    def _safe_date(s):
        try:
            return _convert_vn_date(s)
        except Exception:
            return pd.to_datetime(s, errors="coerce")

    df["start_day"] = df["start_day"].apply(_safe_date)
    df["end_day"]   = df["end_day"].apply(_safe_date)

    # FIX #1: crawl_date — thử nhiều format, fallback về today nếu parse lỗi
    if reference_date is not None:
        df["crawl_date"] = pd.Timestamp(reference_date).normalize()
    elif "crawl_date" in df.columns:
        def _parse_crawl_date(s):
            for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    return pd.to_datetime(s, format=fmt)
                except Exception:
                    pass
            return pd.to_datetime(s, errors="coerce")

        df["crawl_date"] = df["crawl_date"].astype(str).apply(_parse_crawl_date)

        today = pd.Timestamp(datetime.date.today())
        bad_dates = df["crawl_date"].isna() | (df["crawl_date"] > today + pd.Timedelta(days=1))
        if bad_dates.any():
            log.warning(
                "%d dòng có crawl_date không hợp lệ → thay bằng today (%s)",
                bad_dates.sum(), today.date()
            )
            df.loc[bad_dates, "crawl_date"] = today
    else:
        df["crawl_date"] = pd.Timestamp(datetime.date.today())

    df["days_left"] = (df["start_day"] - df["crawl_date"]).dt.days
    log.info("days_left stats:\n%s", df["days_left"].describe().to_string())

    n_before = len(df)
    df = df[df["days_left"] >= 0].copy()
    n_dropped = n_before - len(df)
    if n_dropped > 0:
        log.warning("Đã drop %d dòng có days_left < 0", n_dropped)

    if df.empty:
        log.error(
            "DataFrame rỗng sau khi filter days_left! "
            "Kiểm tra lại crawl_date trong data hoặc truyền reference_date đúng."
        )
        return df

    log.info(
        "days_left sau filter | shape=%s | min=%s max=%s",
        df.shape, df["days_left"].min(), df["days_left"].max()
    )

    # ── 3. is_holiday ────────────────────────────────────────────────────────
    df["is_holiday"] = df["start_day"].apply(_is_holiday_encode)

    # ── 4. Supply proxy ──────────────────────────────────────────────────────
    supply = (
        df.groupby(["brand", "destination", "crawl_date"])["id"]
        .nunique()
        .reset_index()
        .rename(columns={"id": "num_flights_same_route_day"})
    )
    df = df.merge(supply, on=["brand", "destination", "crawl_date"], how="left")

    # ── 5. Lag & rolling features ────────────────────────────────────────────
    # FIX #7: sort DESCENDING (3→2→1) + shift(+1) để nhất quán với predictor.py
    # price_lag1[days_left=1] = price tại days_left=2 (ngày crawl trước đó)
    df = df.sort_values(["id", "days_left"], ascending=[True, False]).reset_index(drop=True)

    for lag in [1, 3]:
        df[f"price_lag{lag}"] = df.groupby("id")["price"].shift(lag)

    # Fill null lag bằng giá hiện tại (flight mới xuất hiện / đầu chuỗi)
    df["price_lag1"] = df["price_lag1"].fillna(df["price"])
    df["price_lag3"] = df["price_lag3"].fillna(df["price"])

    route_price = (
        df.groupby(["brand", "destination", "days_left"])["price"]
        .mean()
        .reset_index()
        .sort_values(["brand", "destination", "days_left"], ascending=[True, True, False])
    )
    route_price["price_roll3_mean"] = route_price.groupby(["brand", "destination"])["price"].transform(
        lambda x: x.rolling(3, min_periods=1).mean()
    )
    route_price["price_roll3_std"] = route_price.groupby(["brand", "destination"])["price"].transform(
        lambda x: x.rolling(3, min_periods=1).std().fillna(0)
    )
    df = df.merge(
        route_price[["brand", "destination", "days_left", "price_roll3_mean", "price_roll3_std"]],
        on=["brand", "destination", "days_left"],
        how="left",
    )

    # Fill null rolling nếu vẫn còn
    df["price_roll3_mean"] = df["price_roll3_mean"].fillna(df["price"])
    df["price_roll3_std"]  = df["price_roll3_std"].fillna(0)

    # ── 6. Luggage ───────────────────────────────────────────────────────────
    for col in ("checked_baggage", "hand_luggage"):
        df[col] = df[col].apply(_format_luggage)

    for col in ("hand_luggage", "checked_baggage"):
        df[col] = df.groupby("id")[col].transform(
            lambda x: x.fillna(x.mode().iloc[0]) if not x.mode().empty else x
        )

    for brand, vals in LUGGAGE_DEFAULTS.items():
        for col, val in vals.items():
            mask = (df["brand"] == brand) & df[col].isna()
            df.loc[mask, col] = val

    df["hand_luggage"]    = df["hand_luggage"].fillna(0).astype(int)
    df["checked_baggage"] = df["checked_baggage"].fillna(0).astype(int)

    # ── 7. Drop date columns ─────────────────────────────────────────────────
    df.drop(columns=["start_day", "end_day", "crawl_date"], inplace=True, errors="ignore")

    null_count = df.isna().sum().sum()
    log.info("Preprocess xong | shape=%s | null=%s", df.shape, null_count)
    if null_count > 0:
        log.warning("Còn null:\n%s", df.isnull().sum()[df.isnull().sum() > 0].to_string())

    return df


def load_and_preprocess_csv(csv_path: str | Path, **kwargs) -> pd.DataFrame:
    """Đọc CSV thô → preprocess → trả DataFrame sạch."""
    df = pd.read_csv(csv_path)
    return preprocess_dataframe(df, **kwargs)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Preprocess raw flight CSV")
    parser.add_argument("--input",  default="data/raw/merged_file.csv")
    parser.add_argument("--output", default="data/cleaned_file_improved.csv")
    parser.add_argument(
        "--reference-date",
        default=None,
        help="Ngày crawl chuẩn (YYYY-MM-DD). Dùng khi crawl_date trong CSV bị sai.",
    )
    args = parser.parse_args()

    ref = pd.Timestamp(args.reference_date) if args.reference_date else None
    df_out = load_and_preprocess_csv(args.input, reference_date=ref)
    df_out.to_csv(args.output, index=False)
    print(f"Saved → {args.output}  shape={df_out.shape}")