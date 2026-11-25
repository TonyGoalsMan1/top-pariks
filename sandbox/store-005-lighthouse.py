"""Summarize repeated Lighthouse lab measurements."""
import json
import statistics
import sys
from pathlib import Path

folder = Path(sys.argv[1])
metrics = {
    "LCP ms": "largest-contentful-paint",
    "CLS": "cumulative-layout-shift",
    "TBT ms": "total-blocking-time",
    "Total bytes": "total-byte-weight",
}
summary = {}
for profile in ("mobile", "desktop"):
    for page in ("home", "product"):
        name = f"{profile}-{page}"
        reports = [json.loads((folder / f"{name}-{i}.json").read_text(encoding="utf-8"))
                   for i in range(1, 4)]
        samples = {
            label: [report["audits"][audit]["numericValue"] for report in reports]
            for label, audit in metrics.items()
        }
        requests = [report["audits"]["network-requests"]["details"]["items"] for report in reports]
        samples["Requests"] = [len(items) for items in requests]
        samples["Image transferred bytes"] = [
            sum(item.get("transferSize", 0) for item in items if item.get("resourceType") == "Image")
            for items in requests
        ]
        summary[name] = {
            key: {"median": round(statistics.median(values), 3), "runs": values}
            for key, values in samples.items()
        }
(folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2))
