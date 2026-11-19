#!/usr/bin/env python3
"""Run the full test suite and write a dashboard-ready test-results.json."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "test-results.raw.json"
COV = ROOT / "coverage.json"
RESULTS = ROOT / "test-results.json"
HISTORY = ROOT / "test-history.json"

FEATURES = {
    "google": ("Google / OAuth", ("google", "oauth", "account")),
    "gmail": ("Gmail", ("gmail", "email", "mail_parsing")),
    "voice": ("Voice", ("voice", "wake", "conversation_state", "speech", "vad")),
    "llm": ("LLM", ("llm", "decision", "prompt", "tool")),
    "memory": ("Memory", ("memory", "conversation_memory")),
    "initiative": ("Initiative", ("initiative", "proactive")),
    "gui": ("GUI", ("gui", "widget", "chat", "ui")),
    "security": ("Security", ("security", "path", "injection", "token")),
    "db": ("Database", ("vector_db", "sqlite", "gmail_store")),
    "config": ("Config", ("config", "fallback", "provider")),
    "other": ("Other", ()),
}


def feature_of(nodeid: str) -> str:
    low = nodeid.lower()
    for key, (_label, needles) in FEATURES.items():
        if key == "other":
            continue
        if any(n in low for n in needles):
            return key
    return "other"


def technology_of(nodeid: str) -> str:
    low = nodeid.lower()
    tags = []
    if "qt" in low or "widget" in low or "gui" in low:
        tags.append("PyQt6")
    if "sqlite" in low or "vector_db" in low or "gmail" in low:
        tags.append("SQLite")
    if "google" in low or "oauth" in low:
        tags.append("OAuth")
    if "voice" in low or "vad" in low or "wake" in low:
        tags.append("audio")
    if "llm" in low or "decision" in low:
        tags.append("LLM")
    return ", ".join(tags) or "pytest"


def audit_counts() -> dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    try:
        text = (ROOT / "AUDIT.md").read_text(encoding="utf-8")
    except Exception:
        return counts
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip().lower() for c in line.strip("|").split("|")]
        if len(cells) >= 2 and cells[1] in counts:
            counts[cells[1]] += 1
    return counts


def main() -> int:
    cmd = [
        sys.executable, "-m", "pytest", "-q",
        "--json-report", f"--json-report-file={RAW}",
        f"--cov=core", "--cov=actions", "--cov=memory",
        "--cov=ui", "--cov=main", "--cov=pc_bridge",
        "--cov-report=", f"--cov-report=json:{COV}",
        "--tb=short",
    ]
    print("Running:", " ".join(cmd), flush=True)
    code = subprocess.run(cmd, cwd=ROOT).returncode

    raw: dict[str, Any] = {}
    if RAW.exists():
        raw = json.loads(RAW.read_text(encoding="utf-8"))
    cov: dict[str, Any] = {}
    if COV.exists():
        cov = json.loads(COV.read_text(encoding="utf-8"))

    tests = []
    for t in raw.get("tests", []):
        nodeid = t.get("nodeid", "")
        failure = ""
        call = t.get("call") or {}
        longrepr = call.get("longrepr")
        if longrepr:
            failure = str(longrepr)
        tests.append({
            "name": t.get("name", nodeid),
            "nodeid": nodeid,
            "outcome": t.get("outcome", "unknown"),
            "duration": round(float(t.get("duration") or 0), 4),
            "feature": feature_of(nodeid),
            "technology": technology_of(nodeid),
            "markers": [str(m) for m in t.get("markers", [])],
            "failure": failure,
        })

    files_cov = {}
    for name, data in cov.get("files", {}).items():
        s = data.get("summary", {})
        files_cov[name] = {
            "percent": round(float(s.get("percent_covered") or 0), 1),
            "missing": int(s.get("missing_lines") or 0),
            "statements": int(s.get("num_statements") or 0),
            "missing_lines": list(data.get("missing_lines", [])),
        }

    history: list[dict[str, Any]] = []
    if HISTORY.exists():
        try:
            history = json.loads(HISTORY.read_text(encoding="utf-8"))
        except Exception:
            history = []
    totals = cov.get("totals", {})
    summary = dict(raw.get("summary", {}))
    summary.setdefault("total", len(tests))
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration": round(float(raw.get("duration") or 0), 2),
        "exit_code": code,
        "summary": summary,
        "coverage": {
            "percent": round(float(totals.get("percent_covered") or 0), 1),
            "covered": int(totals.get("covered_lines") or 0),
            "missing": int(totals.get("missing_lines") or 0),
            "files": files_cov,
        },
        "audit": audit_counts(),
        "tests": tests,
        "history": history,
    }

    RESULTS.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    new_entry = {
        "at": result["generated_at"],
        "passed": summary.get("passed", 0),
        "failed": summary.get("failed", 0),
        "skipped": summary.get("skipped", 0),
        "coverage": result["coverage"]["percent"],
        "duration": result["duration"],
    }
    result["history"] = history + [new_entry]
    history.append(new_entry)
    HISTORY.write_text(json.dumps(history[-30:], indent=2), encoding="utf-8")
    print(f"Wrote {RESULTS} ({len(tests)} tests, {result['coverage']['percent']}% coverage)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
