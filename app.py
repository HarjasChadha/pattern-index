"""
Pattern Index — Dashboard Server
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
            return json.load(f)
    return []

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
    if not history:
        return jsonify({"error": "No data yet"})
    return jsonify(history[-1])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
