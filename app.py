"""
Pattern Index - Dashboard Server
Serves the live web dashboard from data/history.json.
Deploy on Railway or Render (free tier).
"""
from flask import Flask, jsonify, render_template
from pathlib import Path
import json, os

app = Flask(__name__)

DATA_FILE  = Path("data/history.json")
PARAM_FILE = Path("params.json")

def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            raw = json.load(f)
        # New format: dict with lookback_data and live_rows
        # Old format: flat list (legacy)
        if isinstance(raw, dict):
            return raw
        else:
            return {"lookback_data": raw, "live_rows": []}
    return {"lookback_data": [], "live_rows": []}

def load_params():
    if PARAM_FILE.exists():
        with open(PARAM_FILE) as f:
            return json.load(f)
    return {}

@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/api/data")
def api_data():
    history = load_data()
    params  = load_params()
    return jsonify({"history": history, "params": params})

@app.route("/api/latest")
def api_latest():
    history = load_data()
    live_rows = history.get("live_rows", [])
    if not live_rows:
        return jsonify({"error": "No live data yet"})
    return jsonify(live_rows[-1])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
