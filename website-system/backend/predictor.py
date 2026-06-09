"""
predictor.py
============
Chuyển đổi từ notebook 03_Modelling_Improved.ipynb → module Python thuần.

Chế độ sử dụng:
  1. Import trong api_server.py:
       from predictor import FlightPredictor
       predictor = FlightPredictor()                   # load model từ disk
       label = predictor.predict_label(df_cleaned, flight_id)

  2. CLI train (offline):
       python predictor.py --train --data data/cleaned_file_improved.csv

  3. CLI predict đơn (debug):
       python predictor.py --predict --data data/cleaned_file_improved.csv --flight VJ123
"""

from __future__ import annotations

import argparse
import logging
import pickle
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn import metrics
from sklearn.model_selection import TimeSeriesSplit
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import LabelEncoder

warnings.filterwarnings("ignore")
log = logging.getLogger(__name__)

# ── Optional heavy deps ───────────────────────────────────────────────────────
try:
    import lightgbm as lgb
    _HAS_LGB = True
except ImportError:
    _HAS_LGB = False
    log.warning("lightgbm chưa cài — bỏ qua LightGBM, chỉ dùng GBR + CatBoost")

try:
    from catboost import CatBoostRegressor
    _HAS_CAT = True
except ImportError:
    _HAS_CAT = False
    log.warning("catboost chưa cài — bỏ qua CatBoost")

# ─── Đường dẫn mặc định ──────────────────────────────────────────────────────
DEFAULT_MODELS_PATH   = Path("route_models.pkl")
DEFAULT_WEIGHTS_PATH  = Path("route_weights.pkl")
DEFAULT_ENCODERS_PATH = Path("route_encoders.pkl")   # FIX #6: lưu encoder

# ─── Model factories ─────────────────────────────────────────────────────────

def _make_gbr():
    return GradientBoostingRegressor(
        n_estimators=100, learning_rate=0.1, max_depth=3, random_state=42
    )

def _make_lgbm():
    return lgb.LGBMRegressor(
        n_estimators=300, learning_rate=0.1,
        num_leaves=63, subsample=0.8,
        colsample_bytree=0.8, random_state=42, verbose=-1,
    )

def _make_catboost():
    return CatBoostRegressor(
        iterations=300, learning_rate=0.03,
        depth=3, random_seed=42, verbose=False,
    )

def _get_model_factories() -> dict:
    facs: dict[str, Any] = {"GBR": _make_gbr}
    if _HAS_LGB:
        facs["LightGBM"] = _make_lgbm
    if _HAS_CAT:
        facs["CatBoost"] = _make_catboost
    return facs

# ─── Preprocessing bổ sung ───────────────────────────────────────────────────

def _prepare_features(
    data: pd.DataFrame,
    encoders: dict | None = None,
    fit_encoders: bool = False,
) -> tuple[pd.DataFrame, list[str], dict]:
    """
    One-hot encode + label encode → trả (df, feature_cols, encoders).

    FIX #6: khi fit_encoders=True (lúc train) thì fit + trả encoder mới.
            khi fit_encoders=False (lúc predict) thì dùng encoder đã lưu,
            tránh encoding khác nhau giữa train và predict.

    Parameters
    ----------
    data         : DataFrame đầu vào
    encoders     : dict {"dest": LabelEncoder, "brand": LabelEncoder} đã fit
    fit_encoders : True khi train, False khi predict
    """
    data = data.copy()

    # One-hot giờ
    data = pd.get_dummies(data, columns=["start_hour", "end_hour"])

    if fit_encoders:
        le_dest  = LabelEncoder()
        le_brand = LabelEncoder()
        data["destination_enc"] = le_dest.fit_transform(data["destination"].astype(str))
        data["brand_enc"]       = le_brand.fit_transform(data["brand"].astype(str))
        encoders = {"dest": le_dest, "brand": le_brand}
    else:
        if encoders is None:
            raise ValueError(
                "encoders=None khi fit_encoders=False. "
                "Cần load encoder đã train trước (route_encoders.pkl)."
            )
        le_dest  = encoders["dest"]
        le_brand = encoders["brand"]

        # Các giá trị chưa thấy khi train → map về class đầu tiên để tránh crash
        known_dest  = set(le_dest.classes_)
        known_brand = set(le_brand.classes_)
        data["destination"] = data["destination"].apply(
            lambda x: x if x in known_dest  else le_dest.classes_[0]
        )
        data["brand"] = data["brand"].apply(
            lambda x: x if x in known_brand else le_brand.classes_[0]
        )
        data["destination_enc"] = le_dest.transform(data["destination"].astype(str))
        data["brand_enc"]       = le_brand.transform(data["brand"].astype(str))

    data["route"] = data["brand"].astype(str) + "|" + data["destination"].astype(str)

    DROP = {"id", "brand", "destination", "route", "price", "price_raw"}
    feature_cols = [c for c in data.columns if c not in DROP]

    return data, feature_cols, encoders

# ─── Outlier handling ─────────────────────────────────────────────────────────

def _process_outliers(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for des in df["destination"].unique():
        mask = df["destination"] == des
        q1, q3 = df.loc[mask, "price"].quantile([0.25, 0.75])
        upper = q3 + 1.5 * (q3 - q1)
        df.loc[mask & (df["price"] > upper), "price"] = upper
    return df

# ─── TimeSeriesCV + train ─────────────────────────────────────────────────────

def _ts_cv_and_train(df: pd.DataFrame, feature_cols: list[str], model_fn, model_name: str):
    df_sorted = df.sort_values("days_left", ascending=False).reset_index(drop=True)
    tscv = TimeSeriesSplit(n_splits=5)
    r2_list, mae_list, mape_list = [], [], []

    for train_idx, test_idx in tscv.split(df_sorted):
        tr, te = df_sorted.iloc[train_idx], df_sorted.iloc[test_idx]
        X_tr, y_tr = tr[feature_cols].values, tr["price"].values
        X_te, y_te = te[feature_cols].values, te["price"].values

        m = model_fn()
        m.fit(X_tr, y_tr)
        y_pred = m.predict(X_te)

        r2_list.append(metrics.r2_score(y_te, y_pred))
        mae_list.append(metrics.mean_absolute_error(y_te, y_pred))
        mape_list.append(np.mean(np.abs((y_te - y_pred) / (y_te + 1e-9))) * 100)

    final = model_fn()
    final.fit(df_sorted[feature_cols].values, df_sorted["price"].values)

    return {
        "Model":     model_name,
        "R2_mean":   round(np.mean(r2_list), 4),
        "MAE_mean":  round(np.mean(mae_list), 2),
        "MAPE_mean": round(np.mean(mape_list), 2),
    }, final

# ─── Lag features helper ─────────────────────────────────────────────────────

def _add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    FIX #1: nhất quán với preprocess.py — sort DESCENDING, shift(+1).
    price_lag1[days_left=1] = price tại days_left=2 (ngày crawl trước).
    """
    df = df.sort_values(["id", "days_left"], ascending=[True, False]).copy()
    df["price_lag1"] = df.groupby("id")["price"].shift(1)
    df["price_lag3"] = df.groupby("id")["price"].shift(3)
    df["price_roll3_mean"] = df.groupby("id")["price"].transform(
        lambda x: x.rolling(3, min_periods=1).mean().shift(1)
    )
    df["price_roll3_std"] = df.groupby("id")["price"].transform(
        lambda x: x.rolling(3, min_periods=1).std().shift(1)
    ).fillna(0)
    # Fill null đầu chuỗi bằng giá hiện tại
    df["price_lag1"]      = df["price_lag1"].fillna(df["price"])
    df["price_lag3"]      = df["price_lag3"].fillna(df["price"])
    df["price_roll3_mean"] = df["price_roll3_mean"].fillna(df["price"])
    return df

# ─── Prediction helpers ───────────────────────────────────────────────────────

def _predict_ensemble(route: str, X_new, route_models: dict, route_weights: dict) -> float:
    models  = route_models[route]
    weights = route_weights[route]
    if hasattr(X_new, "values"):
        X_new = X_new.values

    preds, wts = [], []
    for name, model in models.items():
        if name in weights:
            preds.append(model.predict(X_new))
            wts.append(weights[name])

    preds = np.array(preds)
    wts   = np.array(wts) / sum(wts)
    val   = float(np.average(preds, axis=0, weights=wts)[0])
    return val


def _predict_until_takeoff(
    feature_data: pd.DataFrame,
    route_models: dict,
    route_weights: dict,
    feature_cols: list[str],
    max_iter: int = 30,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Bắt đầu từ feature_data (≥3 dòng thực), dự đoán lần lượt đến ngày 0.

    FIX #3: giữ cột route trong history để không bị mất qua các vòng lặp.
    FIX #2: feature_cols được truyền đúng từ caller.
    """
    flight_id = feature_data["id"].iloc[0]
    route     = feature_data["route"].iloc[0]

    history = feature_data.sort_values("days_left", ascending=False).copy()
    # FIX #4: khởi tạo cột is_predicted đúng cách — không dùng .get()
    history["is_predicted"] = False

    all_preds = []

    for _ in range(max_iter):
        window = history.sort_values("days_left").head(3).sort_values("days_left", ascending=False).copy()
        target_day = window["days_left"].min() - 1
        if target_day < 0:
            break

        target_row = window.iloc[[0]].copy()
        target_row["days_left"] = target_day
        target_row = target_row.drop(columns=["price"], errors="ignore")

        # FIX #3: đảm bảo route được giữ lại trong target_row
        target_row["route"] = route
        target_row["id"]    = flight_id

        combined = pd.concat([window, target_row], ignore_index=True)
        combined = _add_lag_features(combined)
        target_feat = combined[combined["days_left"] == target_day].copy()

        if len(target_feat) == 0:
            break

        missing = [c for c in feature_cols if c not in target_feat.columns]
        for c in missing:
            target_feat[c] = 0

        try:
            pred_price = _predict_ensemble(route, target_feat[feature_cols], route_models, route_weights)
        except Exception as e:
            log.debug("predict_ensemble lỗi: %s", e)
            break

        new_row = target_row.iloc[0].to_dict()
        new_row["price"]        = pred_price
        new_row["is_predicted"] = True
        # FIX #3: giữ route trong history
        new_row["route"]        = route
        history = pd.concat([history, pd.DataFrame([new_row])], ignore_index=True)

        all_preds.append({"days_left": target_day, "predicted_price": pred_price})

    return history, pd.DataFrame(all_preds)


def _assign_label(
    full_history: pd.DataFrame,
    initial_feature_days: list[int],
    threshold: int = 50_000,
) -> dict:
    current_day = min(initial_feature_days)

    # FIX #4: is_predicted đã được khởi tạo đúng — dùng trực tiếp
    actual = full_history[
        (full_history["days_left"] == current_day) & (~full_history["is_predicted"])
    ]
    if actual.empty:
        actual = full_history[full_history["days_left"] == current_day]
    if actual.empty:
        return {"label": "BUY_NOW", "note": "no_data"}

    current_price = float(actual.iloc[0]["price"])

    future = full_history[
        (full_history["days_left"] < current_day) &
        (full_history["days_left"] >= 0) &
        (full_history["is_predicted"])
    ]

    if future.empty:
        return {
            "label": "BUY_NOW",
            "current_price": current_price,
            "min_price": current_price,
            "min_day": current_day,
            "price_diff": 0,
        }

    min_row   = future.loc[future["price"].idxmin()]
    min_price = float(min_row["price"])
    min_day   = int(min_row["days_left"])
    diff      = current_price - min_price
    distance  = current_day - min_day

    if diff <= threshold:
        label = "BUY_NOW"
    elif 1 <= distance <= 3:
        label = "WAIT_SHORT"
    else:
        label = "WAIT_LONG"

    return {
        "label":         label,
        "current_day":   current_day,
        "current_price": current_price,
        "min_price":     min_price,
        "min_day":       min_day,
        "price_diff":    diff,
    }

# ─── FlightPredictor ─────────────────────────────────────────────────────────

class FlightPredictor:
    """
    Load model đã train và cung cấp predict_label(df_cleaned).

    FIX #6: encoder được lưu/load cùng model để đảm bảo encoding nhất quán
            giữa train và predict.
    """

    def __init__(
        self,
        models_path:   str | Path = DEFAULT_MODELS_PATH,
        weights_path:  str | Path = DEFAULT_WEIGHTS_PATH,
        encoders_path: str | Path = DEFAULT_ENCODERS_PATH,
        buy_threshold: int = 50_000,
    ):
        self.models_path   = Path(models_path)
        self.weights_path  = Path(weights_path)
        self.encoders_path = Path(encoders_path)
        self.threshold     = buy_threshold
        self.route_models:  dict = {}
        self.route_weights: dict = {}
        self.encoders:      dict | None = None
        self._loaded = False

        self._try_load()

    # ── Load ─────────────────────────────────────────────────────────────────

    def _try_load(self):
        if (
            self.models_path.exists()
            and self.weights_path.exists()
            and self.encoders_path.exists()
        ):
            try:
                with open(self.models_path, "rb") as f:
                    self.route_models = pickle.load(f)
                with open(self.weights_path, "rb") as f:
                    self.route_weights = pickle.load(f)
                with open(self.encoders_path, "rb") as f:
                    self.encoders = pickle.load(f)
                self._loaded = True
                log.info("Model loaded: %d routes", len(self.route_models))
            except Exception as e:
                log.error("Load model thất bại: %s", e)
        else:
            missing = [
                str(p) for p in [self.models_path, self.weights_path, self.encoders_path]
                if not p.exists()
            ]
            log.warning("Chưa tìm thấy model files: %s. Cần train trước.", missing)

    def is_ready(self) -> bool:
        return self._loaded and bool(self.route_models) and self.encoders is not None

    # ── Train ─────────────────────────────────────────────────────────────────

    def train(self, df_cleaned: pd.DataFrame):
        """
        Train model mới từ df_cleaned.
        FIX #6: fit encoder tại đây và lưu vào disk.
        """
        # fit_encoders=True: tạo encoder mới từ toàn bộ training data
        data, feature_cols, encoders = _prepare_features(
            df_cleaned, encoders=None, fit_encoders=True
        )

        lag_cols = [c for c in feature_cols if any(k in c for k in ("lag", "roll", "diff"))]
        existing = [c for c in lag_cols if c in data.columns]
        data = data.dropna(subset=existing)
        log.info("Train data sau dropna: %s", data.shape)

        model_facs = _get_model_factories()
        routes = data["route"].unique()
        log.info("Bắt đầu train %d routes × %d models", len(routes), len(model_facs))

        new_models:  dict = {}
        new_weights: dict = {}

        for route in routes:
            rdf = data[data["route"] == route].copy()
            rdf = _process_outliers(rdf)
            feat_cols = [c for c in feature_cols if c in rdf.columns]

            new_models[route] = {}
            mape_dict: dict   = {}

            for mname, mfn in model_facs.items():
                try:
                    result, trained = _ts_cv_and_train(rdf, feat_cols, mfn, mname)
                    new_models[route][mname] = trained
                    mape_dict[mname] = result["MAPE_mean"]
                    log.debug("  %s / %s → MAPE=%.4f", route, mname, result["MAPE_mean"])
                except Exception as e:
                    log.warning("  %s / %s lỗi: %s", route, mname, e)

            if mape_dict:
                inv = {n: 1.0 / max(v, 1e-6) for n, v in mape_dict.items()}
                total = sum(inv.values())
                new_weights[route] = {n: v / total for n, v in inv.items()}

        # Lưu model, weights, encoders
        with open(self.models_path, "wb") as f:
            pickle.dump(new_models, f)
        with open(self.weights_path, "wb") as f:
            pickle.dump(new_weights, f)
        with open(self.encoders_path, "wb") as f:
            pickle.dump(encoders, f)

        self.route_models  = new_models
        self.route_weights = new_weights
        self.encoders      = encoders
        self._loaded       = True
        log.info(
            "Train xong. Saved → %s / %s / %s",
            self.models_path, self.weights_path, self.encoders_path,
        )

    # ── Predict ───────────────────────────────────────────────────────────────

    def predict_label(self, df_cleaned: pd.DataFrame) -> list[dict]:
        """
        Nhận df_cleaned (đầu ra preprocess, có thể nhiều chuyến bay),
        trả list[dict] mỗi dict = {id, route, label, current_price, ...}.

        FIX #4: is_predicted được khởi tạo đúng trong _predict_until_takeoff,
                không còn dùng DataFrame.get() nữa.
        FIX #6: dùng encoder đã lưu khi train.
        """
        if not self.is_ready():
            log.warning("Model chưa sẵn sàng, trả fallback BUY_NOW cho tất cả")
            return [
                {"id": fid, "label": "BUY_NOW", "note": "model_not_ready"}
                for fid in df_cleaned["id"].unique()
            ]

        # fit_encoders=False: dùng encoder đã train
        data, feature_cols, _ = _prepare_features(
            df_cleaned, encoders=self.encoders, fit_encoders=False
        )

        lag_cols = [c for c in feature_cols if any(k in c for k in ("lag", "roll", "diff"))]
        existing = [c for c in lag_cols if c in data.columns]
        data = data.dropna(subset=existing)

        results = []
        for flight_id in data["id"].unique():
            fdf = data[data["id"] == flight_id].copy()
            if len(fdf) < 3:
                results.append({
                    "id": flight_id, "label": "BUY_NOW", "note": "insufficient_history"
                })
                continue

            route = fdf["route"].iloc[0]
            if route not in self.route_models:
                log.debug("Route %s chưa có model → fallback BUY_NOW", route)
                results.append({
                    "id": flight_id, "route": route,
                    "label": "BUY_NOW", "note": "unknown_route",
                })
                continue

            initial_feature_days = sorted(fdf["days_left"].unique(), reverse=True)[:3]

            # FIX #2: truyền đủ tham số
            full_history, _ = _predict_until_takeoff(
                fdf, self.route_models, self.route_weights, feature_cols
            )
            # FIX #4: KHÔNG gán lại full_history["is_predicted"] ở đây
            #         vì _predict_until_takeoff đã khởi tạo đúng rồi

            label_info = _assign_label(full_history, initial_feature_days, self.threshold)
            label_info["id"]    = flight_id
            label_info["route"] = route
            results.append(label_info)

        return results

    def predict_label_single(self, df_cleaned: pd.DataFrame, flight_id: str) -> dict:
        """Predict cho một flight_id cụ thể."""
        fdf = df_cleaned[df_cleaned["id"] == flight_id]
        res = self.predict_label(fdf)
        return res[0] if res else {"id": flight_id, "label": "BUY_NOW", "note": "not_found"}


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--train",   action="store_true", help="Train & lưu model")
    parser.add_argument("--predict", action="store_true", help="Predict (debug)")
    parser.add_argument("--data",    default="data/cleaned_file_improved.csv")
    parser.add_argument("--flight",  default=None, help="Flight ID cụ thể (predict mode)")
    args = parser.parse_args()

    predictor = FlightPredictor()

    if args.train:
        df = pd.read_csv(args.data)
        predictor.train(df)

    if args.predict:
        df = pd.read_csv(args.data)
        if args.flight:
            r = predictor.predict_label_single(df, args.flight)
            print(r)
        else:
            results = predictor.predict_label(df)
            for r in results[:5]:
                print(r)