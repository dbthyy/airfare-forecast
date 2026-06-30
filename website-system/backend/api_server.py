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
# Thiết lập JSON Provider theo cách chuẩn của Flask cải tiến
app.json_provider_class = NumpyJSONProvider

# Kích hoạt CORS TRƯỚC rồi mới bọc cấu hình mở rộng
CORS(app, resources={r"/api/*": {"origins": "*", "methods": ["GET", "POST", "OPTIONS"]}}, supports_credentials=True)

# ── GET /api/health ───────────────────────────────────────────────────────────
@app.route("/api/health", methods=["GET", "POST"])
def health():
    return jsonify({
        "status":      "ok",
        "model_ready": _predictor.is_ready(),
        "routes_loaded": len(_predictor.route_models),
    })


# ── POST /api/search ──────────────────────────────────────────────────────────
@app.route("/api/search", methods=["POST", "GET"], strict_slashes=False)
def search_flights():
    """
    Body JSON:
      destination, departureDate (yyyy-MM-dd), departureTime?, luggage?, airline?
    Response:
      { flights: [...], total: n }
    """
    # Bộ lọc dự phòng: Nếu nhận request GET (thăm dò hoặc test link), phản hồi 200 OK ngay lập tức
    if request.method == "GET":
        return jsonify({
            "status": "active",
            "message": "API Search đang hoạt động tốt. Hãy dùng phương thức POST từ giao diện Frontend để tìm kiếm."
        }), 200

    # XỬ LÝ PHƯƠNG THỨC POST CHÍNH THỨC
    try:
        body = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Định dạng JSON body không hợp lệ"}), 400

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

    # Lọc dữ liệu
    rows = filter_by_time_slot(rows, depart_time)
    rows = filter_by_airline(rows, airline)
    rows = filter_by_luggage(rows, luggage)

    # ── Preprocess + Predict ─────────────────────────────────────────────────
    rows = _attach_predictions(rows)

    return jsonify({"flights": rows, "total": len(rows)})
