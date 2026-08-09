import json

with open("coverage.json") as f:
    pct = round(json.load(f)["totals"]["percent_covered"])

if pct >= 90:
    color = "brightgreen"
elif pct >= 75:
    color = "green"
elif pct >= 50:
    color = "yellow"
else:
    color = "red"

badge = {"schemaVersion": 1, "label": "coverage", "message": f"{pct}%", "color": color}
with open("coverage-badge.json", "w") as f:
    json.dump(badge, f)
