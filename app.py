"""
Pattern Index - Dashboard Server
Serves the live web dashboard from data/history.json.
Deploy on Railway or Render (free tier).
"""
from flask import Flask, Response, jsonify, render_template, send_from_directory
from pathlib import Path
import json
import os

from updater import sanitize_json

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "history.json"
PARAM_FILE = BASE_DIR / "params.json"


def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            return sanitize_json(raw)
        return sanitize_json({"lookback_data": raw, "live_rows": []})
    return {"lookback_data": [], "live_rows": []}


def load_params():
    if PARAM_FILE.exists():
        with open(PARAM_FILE) as f:
            return sanitize_json(json.load(f))
    return {}


def _json_response(payload):
    body = json.dumps(sanitize_json(payload), allow_nan=False)
    return Response(body, mimetype="application/json")


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/charts")
@app.route("/charts.html")
def charts():
    return send_from_directory(BASE_DIR, "charts.html")


@app.route("/data/history.json")
def data_history():
    return _json_response(load_data())


@app.route("/params.json")
def params_json():
    return _json_response(load_params())


@app.route("/api/data")
def api_data():
    history = load_data()
    params = load_params()
    return _json_response({"history": history, "params": params})


@app.route("/api/latest")
def api_latest():
    history = load_data()
    live_rows = history.get("live_rows", [])
    if not live_rows:
        return jsonify({"error": "No live data yet"})
    return _json_response(live_rows[-1])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
