"""
api_server.py
=============
Flask backend cho Bay Giá Tốt.

Endpoints:
  GET  /api/health          → kiểm tra server + model status
  POST /api/search          → crawl Traveloka, preprocess, predict, trả kết quả
  POST /api/predict         → nhận CSV path hoặc JSON rows, trả nhãn predict
  POST /api/train           → (admin) retrain model từ dữ liệu lịch sử trong data/raw/
"""

from __future__ import annotations
import numpy as np
import datetime
import hashlib
import logging
import os
import re
import threading
import time
from pathlib import Path
from time import sleep

import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask.json.provider import DefaultJSONProvider

# ── Local modules ─────────────────────────────────────────────────────────────
from preprocess import preprocess_dataframe
from predictor  import FlightPredictor

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("crawl.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
DATA_DIR         = Path("data/raw")
DATA_DIR.mkdir(parents=True, exist_ok=True)

MODELS_PATH      = Path("route_models.pkl")
WEIGHTS_PATH     = Path("route_weights.pkl")

MAX_RETRIES      = 2
RETRY_WAIT       = 8
CRAWL_DELAY      = 1.5
EDGE_DRIVER_PATH = r"C:\WebDriver\msedgedriver.exe"

COLUMNS = [
    "id", "brand", "price", "start_time", "start_day", "end_time", "end_day",
    "trip_time", "take_place", "destination",
    "hand_luggage", "checked_baggage", "crawl_date",
]

DEST_CODES = {
    "Hà Nội (HAN)":    "HAN",
    "Đà Nẵng (DAD)":   "DAD",
    "Cam Ranh (CXR)":  "CXR",
    "Hải Phòng (HPH)": "HPH",
    "Phú Quốc (PQC)":  "PQC",
}

TIME_SLOTS = {
    "early_morning": (0,  5),
    "morning":       (6,  11),
    "afternoon":     (12, 17),
    "evening":       (18, 23),
}

# ─── Khởi tạo predictor (load model 1 lần khi server start) ──────────────────
_predictor = FlightPredictor(
    models_path=MODELS_PATH,
    weights_path=WEIGHTS_PATH,
)

def find_existing_csv(dest_code: str, depart_date: str):
    """
    depart_date = '2026-06-10'
    tìm file SGN_PQC_10_thg_6.csv
    """
    dt = datetime.datetime.strptime(depart_date, "%Y-%m-%d")

    file_name = f"SGN_{dest_code}_{dt.day}_thg_{dt.month}.csv"
    fp = DATA_DIR / file_name

    log.info("Checking cache: %s", fp.resolve())
    log.info("Exists? %s", fp.exists())

    return fp if fp.exists() else None

# ─── Helpers ──────────────────────────────────────────────────────────────────

def url_to_key(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def build_url(dest_code: str, date_str: str) -> str:
    """date_str: yyyy-MM-dd → dd-MM-yyyy cho Traveloka."""
    y, m, d = date_str.split("-")
    return (
        f"https://www.traveloka.com/vi-vn/flight/fullsearch"
        f"?ap=SGN.{dest_code}&dt={d}-{m}-{y}.NA&ps=1.0.0&sc=ECONOMY"
    )


def parse_hour(time_str: str) -> int:
    try:
        return int(time_str.split(":")[0])
    except Exception:
        return -1


def filter_by_time_slot(rows: list, slot: str) -> list:
    if not slot:
        return rows
    lo, hi = TIME_SLOTS.get(slot, (0, 23))
    return [r for r in rows if lo <= parse_hour(r.get("start_time", "")) <= hi]


def filter_by_airline(rows: list, airline: str) -> list:
    mapping = {
        "vietnam-airlines": "vietnam airlines",
        "vietjet":          "vietjet",
        "bamboo":           "bamboo",
        "vietravel":        "vietravel",
    }
    keyword = mapping.get(airline, "")
    if not keyword:
        return rows
    return [r for r in rows if keyword in r.get("brand", "").lower()]


def filter_by_luggage(rows: list, luggage_kg: str) -> list:
    if not luggage_kg or luggage_kg == "0":
        return rows
    req = int(luggage_kg)
    result = [
        r for r in rows
        if (nums := re.findall(r"\d+", r.get("checked_baggage", ""))) and int(nums[0]) >= req
    ]
    return result or rows   # fallback: trả tất cả nếu lọc sạch


# ─── Selenium driver ──────────────────────────────────────────────────────────

def make_driver(headless: bool = True):
    from selenium import webdriver
    from selenium.webdriver.edge.service import Service

    if not os.path.exists(EDGE_DRIVER_PATH):
        raise FileNotFoundError(f"Không tìm thấy WebDriver: {EDGE_DRIVER_PATH}")
    service = Service(EDGE_DRIVER_PATH)
    options = webdriver.EdgeOptions()
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
    )
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    return webdriver.Edge(service=service, options=options)


def scroll_full_page(driver):
    from selenium.webdriver.common.by import By
    card_xpath = "//div[@class='css-1dbjc4n r-9nbb9w r-otx420 r-1i1ao36 r-1x4r79x']"
    last_count, no_change = 0, 0
    while True:
        cards = driver.find_elements(By.XPATH, card_xpath)
        cur = len(cards)
        if cur == 0:
            time.sleep(1)
            continue
        if cur == last_count:
            no_change += 1
            if no_change >= 4:
                break
        else:
            last_count, no_change = cur, 0
        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center',behavior:'smooth'});",
                cards[-1],
            )
        except Exception:
            driver.execute_script("window.scrollBy(0,800);")
        time.sleep(1)
    driver.execute_script("window.scrollTo(0,0);")
    time.sleep(1)


def crawl_one_url(driver, url: str) -> list[dict]:
    """Crawl một URL Traveloka, trả list of row dicts."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    try:
        driver.get(url)
        time.sleep(6)
        wait = WebDriverWait(driver, 12)

        # Bật bộ lọc Bay thẳng
        try:
            btn = driver.find_element(
                By.XPATH,
                "//div[text()='Bay thẳng']/preceding::div[@aria-checked][1]",
            )
            if btn.get_attribute("aria-checked") == "false":
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(4)
        except Exception:
            pass

        scroll_full_page(driver)

        card_xpath = "//div[@class='css-1dbjc4n r-9nbb9w r-otx420 r-1i1ao36 r-1x4r79x']"
        total_cards = driver.find_elements(By.XPATH, card_xpath)
        log.info("[crawl] %s → %d cards", url, len(total_cards))

        rows: list[dict] = []
        for i in range(len(total_cards)):
            try:
                cards = driver.find_elements(By.XPATH, card_xpath)
                if i >= len(cards):
                    break
                card = cards[i]
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
                time.sleep(0.3)

                ct = card.text.lower()
                if "phổ thông đặc biệt" in ct or "thương gia" in ct:
                    log.info("Gặp hạng vé đặc biệt tại card %d — dừng.", i + 1)
                    break

                brand = card.find_element(
                    By.XPATH,
                    ".//div[@class='css-1dbjc4n r-1habvwh r-18u37iz r-1ssbvtb']//div[@dir='auto']",
                ).text
                raw_price = card.find_element(
                    By.XPATH, ".//h3[@data-testid='label_fl_inventory_price']"
                ).text
                price = raw_price.split("/")[0].strip() if "/" in raw_price else raw_price.strip()

                detail_btn = card.find_element(
                    By.XPATH,
                    ".//*[contains(text(),'Chi tiết') or contains(text(),'Flight Detail')]",
                )
                driver.execute_script("arguments[0].click();", detail_btn)

                try:
                    wait.until(
                        lambda d: len(
                            card.find_elements(
                                By.XPATH,
                                ".//*[contains(text(),'xách tay') or contains(text(),'hành lý')]",
                            )
                        ) > 0
                    )
                except Exception:
                    pass

                bag_els = card.find_elements(
                    By.XPATH,
                    ".//*[contains(text(),'kg') or contains(text(),'Xách tay') or contains(text(),'Hành lý')]",
                )
                hand, checked = "Không có", "Không có"
                for b in bag_els:
                    t = b.text.lower()
                    if "xách tay" in t:
                        hand = b.text
                    if "hành lý" in t or "ký gửi" in t:
                        checked = b.text

                flight_id = "UNKNOWN"
                try:
                    flight_id = card.find_element(
                        By.XPATH, ".//span[@data-element='flightNumber']"
                    ).text.strip()
                except Exception:
                    pass

                take_place, destination = "TP.HCM (SGN)", "Không rõ"
                try:
                    destination = card.find_element(
                        By.XPATH,
                        ".//div[contains(@class,'r-e8mqni') and contains(@class,'r-q3we1')]//div[contains(text(),'(')]",
                    ).text.strip()
                except Exception:
                    pass

                time_els = card.find_elements(
                    By.XPATH,
                    ".//div[@dir='auto' and contains(text(),':') and not(contains(text(),'h'))]",
                )
                start_time = time_els[0].text.strip() if len(time_els) > 0 else "Không rõ"
                end_time   = time_els[1].text.strip() if len(time_els) > 1 else "Không rõ"

                day_els = card.find_elements(
                    By.XPATH, ".//div[@dir='auto' and contains(text(),'thg')]"
                )
                start_day = day_els[0].text.strip() if len(day_els) > 0 else "Không rõ"
                end_day   = day_els[1].text.strip() if len(day_els) > 1 else start_day

                trip_time = "Không rõ"
                try:
                    trip_time = card.find_element(
                        By.XPATH,
                        ".//div[contains(@class,'r-13awgt0') and contains(@class,'r-fdjqy7')]",
                    ).text
                except Exception:
                    pass

                rows.append({
                    "id":              flight_id,
                    "brand":           brand,
                    "price":           price,
                    "start_time":      start_time,
                    "start_day":       start_day,
                    "end_time":        end_time,
                    "end_day":         end_day,
                    "trip_time":       trip_time,
                    "take_place":      take_place,
                    "destination":     destination,
                    "hand_luggage":    hand,
                    "checked_baggage": checked,
                    "crawl_date":      datetime.datetime.now().strftime("%d-%m-%Y"),
                })

                try:
                    driver.execute_script("arguments[0].click();", detail_btn)
                except Exception:
                    pass
                time.sleep(CRAWL_DELAY)

            except Exception as e:
                log.debug("Card %d lỗi: %s", i, e)
                continue

        # Ghi CSV lịch sử
        if rows:
            df_save = pd.DataFrame(rows, columns=COLUMNS)
            try:
                dest_m = re.search(r"\(([A-Z]{3})\)", rows[0].get("destination", ""))
                dc     = dest_m.group(1) if dest_m else "UNK"
                cd     = rows[0].get("start_day", "nodate").replace(" ", "_")
                fp     = DATA_DIR / f"SGN_{dc}_{cd}.csv"
                df_save.to_csv(fp, mode="a", index=False,
                               header=not fp.exists(), encoding="utf-8-sig")
            except Exception:
                df_save.to_csv(
                    DATA_DIR / f"SGN_UNKNOWN_{url_to_key(url)}.csv",
                    mode="a", index=False, encoding="utf-8-sig",
                )

        return rows

    except Exception as e:
        log.error("crawl_one_url error: %s", e)
        return []


# ─── Preprocess + Predict helper ─────────────────────────────────────────────
import numpy as np  # đã có sẵn ở đầu file

def _sanitize_row(row: dict) -> dict:
    """Convert numpy int64/float64 → Python native để jsonify không crash."""
    out = {}
    for k, v in row.items():
        if isinstance(v, np.integer):
            out[k] = int(v)
        elif isinstance(v, np.floating):
            out[k] = None if np.isnan(v) else float(v)
        elif isinstance(v, np.bool_):
            out[k] = bool(v)
        elif isinstance(v, np.ndarray):
            out[k] = v.tolist()
        else:
            out[k] = v
    return out

def _attach_predictions(rows: list[dict]) -> list[dict]:
    if not rows or not _predictor.is_ready():
        for r in rows:
            r["label"] = "UNKNOWN"
        return rows

    try:
        df_today = pd.DataFrame(rows)

        # ── Tìm file lịch sử khớp với destination + ngày bay ──
        dest_match = re.search(r"\(([A-Z]{3})\)", rows[0].get("destination", ""))
        start_day  = rows[0].get("start_day", "")          # ví dụ: "10 thg 6"
        
        if dest_match and start_day:
            dest_code  = dest_match.group(1)               # "PQC"
            clean_day  = start_day.replace(" ", "_")       # "10_thg_6"
            pattern    = DATA_DIR / f"SGN_{dest_code}_{clean_day}.csv"
            
            history_files = list(DATA_DIR.glob(f"SGN_{dest_code}_{clean_day}.csv"))
            if history_files:
                df_history = pd.read_csv(history_files[0], encoding="utf-8-sig")
                log.info("Đọc lịch sử: %s (%d rows)", history_files[0].name, len(df_history))
                
                # Gộp lịch sử + hôm nay, bỏ duplicate
                df_raw = pd.concat([df_history, df_today], ignore_index=True)
                df_raw = df_raw.drop_duplicates(subset=["id", "crawl_date"], keep="last")
            else:
                log.warning("Không tìm thấy file lịch sử cho SGN_%s_%s", dest_code, clean_day)
                df_raw = df_today
        else:
            df_raw = df_today

        df_clean = preprocess_dataframe(df_raw)

        # Chỉ predict các id vừa crawl hôm nay
        today_ids = set(df_today["id"].unique())
        df_clean  = df_clean[df_clean["id"].isin(today_ids)]

        if df_clean.empty:
            for r in rows:
                r["label"] = "UNKNOWN"
            return rows

        label_list = _predictor.predict_label(df_clean)
        label_map  = {str(item.get("id")): item for item in label_list}

        for r in rows:
            info           = label_map.get(str(r.get("id")), {})
            r["label"]         = info.get("label", "UNKNOWN")
            r["current_price"] = info.get("current_price")
            r["min_price"]     = info.get("min_price")
            r["min_day"]       = info.get("min_day")
            r["price_diff"]    = info.get("price_diff")

    except Exception as e:
        log.error("_attach_predictions lỗi: %s", e)
        for r in rows:
            r["label"] = "UNKNOWN"

    return rows


# ─── Flask app ────────────────────────────────────────────────────────────────
class NumpyJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return None if np.isnan(obj) else float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

app = Flask(__name__)
app.json_provider_class = NumpyJSONProvider
app.json = NumpyJSONProvider(app)
CORS(app)
# ── GET /api/health ───────────────────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status":      "ok",
        "model_ready": _predictor.is_ready(),
        "routes_loaded": len(_predictor.route_models),
    })


# ── POST /api/search ──────────────────────────────────────────────────────────
@app.route("/api/search", methods=["POST"])
def search_flights():
    """
    Body JSON:
      destination, departureDate (yyyy-MM-dd), departureTime?, luggage?, airline?
    Response:
      { flights: [...], total: n }
    Mỗi flight có thêm trường: label, current_price, min_price, min_day, price_diff
    """
    body         = request.get_json(force=True)
    destination  = body.get("destination", "")
    depart_date  = body.get("departureDate", "")
    depart_time  = body.get("departureTime", "")
    luggage      = body.get("luggage", "0")
    airline      = body.get("airline", "")

    if not destination or not depart_date:
        return jsonify({"error": "Thiếu destination hoặc departureDate"}), 400

    dest_code = DEST_CODES.get(destination)
    if not dest_code:
        return jsonify({"error": f"Không hỗ trợ điểm đến: {destination}"}), 400

    url = build_url(dest_code, depart_date)
    log.info("[API /search] → %s", url)

    existing_file = find_existing_csv(dest_code, depart_date)

    if existing_file:
        log.info("Đọc dữ liệu có sẵn: %s", existing_file)
        df = pd.read_csv(existing_file, encoding="utf-8-sig")
        rows = df.to_dict("records")

    else:
        log.info("Không có file cache → crawl Traveloka")
        driver = None
        try:
            driver = make_driver(headless=True)
            rows: list[dict] = []
            for attempt in range(1, MAX_RETRIES + 1):
                rows = crawl_one_url(driver, url)
                if rows:
                    break
                if attempt < MAX_RETRIES:
                    sleep(RETRY_WAIT)
        finally:
            if driver:
                driver.quit()

    # Lọc
    rows = filter_by_time_slot(rows, depart_time)
    rows = filter_by_airline(rows, airline)
    rows = filter_by_luggage(rows, luggage)

    # ── Preprocess + Predict ─────────────────────────────────────────────────
    rows = _attach_predictions(rows)

    return jsonify({"flights": rows, "total": len(rows)})


# ── POST /api/predict ─────────────────────────────────────────────────────────
@app.route("/api/predict", methods=["POST"])
def predict_only():
    """
    Nhận JSON { rows: [...] } (cùng schema crawler) hoặc { csv_path: "..." }
    → preprocess → predict → trả nhãn.
    Dùng để test offline không cần crawl.
    """
    body = request.get_json(force=True)

    if "csv_path" in body:
        p = Path(body["csv_path"])
        if not p.exists():
            return jsonify({"error": f"File không tồn tại: {p}"}), 400
        df_raw = pd.read_csv(p)
    elif "rows" in body:
        df_raw = pd.DataFrame(body["rows"])
    else:
        return jsonify({"error": "Cần trường rows hoặc csv_path"}), 400

    try:
        df_clean   = preprocess_dataframe(df_raw)
        label_list = _predictor.predict_label(df_clean)
        return jsonify({"predictions": label_list, "total": len(label_list)})
    except Exception as e:
        log.error(e)
        return jsonify({"error": str(e)}), 500


# ── POST /api/train ───────────────────────────────────────────────────────────
@app.route("/api/train", methods=["POST"])
def train_model():
    """
    Retrain model từ toàn bộ CSV thô trong DATA_DIR (data/raw/).
    Chạy background thread để không block request.
    Body: {} (không cần gì)
    """
    def _do_train():
        csv_files = list(DATA_DIR.glob("*.csv"))
        if not csv_files:
            log.warning("[train] Không tìm thấy CSV trong %s", DATA_DIR)
            return

        log.info("[train] Gộp %d file CSV...", len(csv_files))
        dfs = []
        for fp in csv_files:
            try:
                dfs.append(pd.read_csv(fp, encoding="utf-8-sig"))
            except Exception as e:
                log.warning("  Bỏ qua %s: %s", fp.name, e)

        if not dfs:
            log.warning("[train] Không đọc được file nào")
            return

        df_merged = pd.concat(dfs, ignore_index=True)
        log.info("[train] Merged shape: %s", df_merged.shape)

        try:
            df_clean = preprocess_dataframe(df_merged)
            _predictor.train(df_clean)
            log.info("[train] Hoàn thành train.")
        except Exception as e:
            log.error("[train] Lỗi: %s", e)

    t = threading.Thread(target=_do_train, daemon=True)
    t.start()

    return jsonify({
        "status": "training_started",
        "message": f"Đang train từ {len(list(DATA_DIR.glob('*.csv')))} file CSV trong background.",
    })


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
