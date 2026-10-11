"""Turn detection + collection results into GitHub annotations and a job summary.

Fails the job when nothing was found or nothing could be collected: that means
the probers/collectors broke (or every ATS changed at once), not that ten real
companies vanished overnight.
"""

import json
import os
import sqlite3
import sys

db = sqlite3.connect(sys.argv[1])
db.row_factory = sqlite3.Row
rows = db.execute(
    "SELECT id, name, ats, ats_token, detect_status, detect_confidence, detect_detail,"
    " collect_status, collect_detail, open_jobs FROM companies WHERE active = 1 ORDER BY name"
).fetchall()

lines = ["| Company | Detect | Board | Collect | Open jobs | Example |",
         "|---|---|---|---|---|---|"]
found = collected = 0
for r in rows:
    board = f"{r['ats']}/{r['ats_token']}" if r["ats_token"] else (r["ats"] or "")
    status = r["detect_status"] or "unchecked"
    if status in ("found", "override"):
        found += 1
    if r["collect_status"] == "ok":
        collected += 1
    ex = db.execute(
        "SELECT title, comp_min, comp_max, remote, length(description) AS dlen FROM jobs"
        " WHERE company_id = ? AND closed_at IS NULL ORDER BY description IS NULL, id LIMIT 1",
        (r["id"],),
    ).fetchone()
    example = ""
    if ex:
        pay = f" ${ex['comp_min']:,}-${ex['comp_max']:,}" if ex["comp_min"] else ""
        example = f"{ex['title']} (desc {ex['dlen'] or 0} chars{pay})"
    msg = json.loads(r["detect_detail"] or "{}").get("message", "")
    level = "error" if "error" in (status, r["collect_status"]) else "notice"
    print(f"::{level} title={r['name']}::detect={status} {board} [{r['detect_confidence'] or '-'}]"
          f" | collect={r['collect_status']} open={r['open_jobs']} {r['collect_detail'] or ''}"
          f" | {example} | {msg}")
    lines.append(f"| {r['name']} | {status} | {board} | {r['collect_status'] or ''} "
                 f"| {r['open_jobs'] if r['open_jobs'] is not None else ''} | {example} |")

summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a") as f:
        f.write(f"## Live check: {found}/{len(rows)} detected, {collected} boards collected\n\n"
                + "\n".join(lines) + "\n")

print(f"detected {found}/{len(rows)}, collected {collected}")
sys.exit(0 if found and collected else 1)
