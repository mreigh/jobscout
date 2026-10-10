"""Probe a slug that cannot exist on every ATS. Any 'found' is a false-positive bug."""

import sys

from jobscout.detect.probers import PROBERS, safe_probe
from jobscout.http import PoliteClient

SLUG = "jobscout-canary-zq9x7"
bad = []
with PoliteClient() as http:
    for ats, fn in PROBERS.items():
        p = safe_probe(fn, http, ats, SLUG)
        state = "ERROR " + p.error if p.error else ("FOUND (bug!)" if p.found else "ok, not found")
        level = "error" if p.found else "notice"
        print(f"::{level} title=canary {ats}::{state}")
        if p.found:
            bad.append(ats)
sys.exit(1 if bad else 0)
