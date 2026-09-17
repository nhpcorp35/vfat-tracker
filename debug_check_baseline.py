import json
import os
import time

HISTORY_DIR = os.environ.get("HISTORY_DIR", "/data")
path = os.path.join(HISTORY_DIR, "known_positions.json")

with open(path) as f:
    known = json.load(f)

key = "base:uniswap_v3:5992616"
entry = known.get(key)
if entry is None:
    print(f"No entry found for {key}")
    print("Available keys:", list(known.keys()))
else:
    print(f"Entry for {key}:")
    for k, v in entry.items():
        print(f"  {k}: {v}")
    if "baseline_ts" in entry:
        age_hours = (time.time() - entry["baseline_ts"]) / 3600
        print(f"\nBaseline set {age_hours:.1f} hours ago")

# Also check the position's recorded history to see the value trend
hist_path = os.path.join(HISTORY_DIR, f"history_pos_{key}.json")
try:
    with open(hist_path) as f:
        hist = json.load(f)
    print(f"\n{len(hist)} history snapshots for this position")
    print("First 5:", hist[:5])
    print("Last 5:", hist[-5:])
except FileNotFoundError:
    print(f"\nNo history file found at {hist_path}")
