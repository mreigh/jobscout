"""Turn detection results into GitHub annotations and a job summary.

Fails the job if nothing at all was found, since that means the probers broke
(or every ATS changed at once), not that ten real companies vanished.
"""

import json
import os
import sqlite3
import sys

db = sqlite3.connect(sys.argv[1])
db.row_factory = sqlite3.Row
rows = db.execute(
    "SELECT name, ats, ats_token, detect_status, detect_confidence, job_count, detect_detail"
    " FROM companies WHERE active = 1 ORDER BY name"
).fetchall()

lines = ["| Company | Status | Board | Confidence | Jobs |", "|---|---|---|---|---|"]
found = 0
for r in rows:
    board = f"{r['ats']}/{r['ats_token']}" if r["ats_token"] else (r["ats"] or "")
    status = r["detect_status"] or "unchecked"
    if status in ("found", "override"):
        found += 1
    msg = json.loads(r["detect_detail"] or "{}").get("message", "")
    level = "error" if status == "error" else "notice"
    print(f"::{level} title={r['name']}::{status} {board} "
          f"[{r['detect_confidence'] or '-'}] jobs={r['job_count']} | {msg}")
    lines.append(f"| {r['name']} | {status} | {board} | {r['detect_confidence'] or ''} "
                 f"| {r['job_count'] if r['job_count'] is not None else ''} |")

summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a") as f:
        f.write(f"## Detection: {found}/{len(rows)} found\n\n" + "\n".join(lines) + "\n")

print(f"found {found}/{len(rows)}")
sys.exit(0 if found else 1)
