#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def merge_reports(rule_report: dict, codex_report: dict) -> dict:
    items = []

    for v in rule_report.get("hard_violations", []):
        items.append({
            "ref": v.get("item", "unknown"),
            "source": "hard_rule",
            "verdict": "reject",
            "rule_id": v.get("rule", ""),
            "reason": v.get("detail", ""),
        })

    for w in rule_report.get("soft_warnings", []):
        items.append({
            "ref": f"day_{w.get('day_num', '?')}",
            "source": "soft_rule",
            "verdict": "flag",
            "rule_id": w.get("rule", ""),
            "reason": w.get("detail", ""),
        })

    for it in codex_report.get("items", []):
        items.append({
            "ref": it.get("ref", "unknown"),
            "source": "codex",
            "verdict": it.get("verdict", "flag"),
            "reason": it.get("reason", ""),
            "suggestion": it.get("suggestion", ""),
        })

    accepted = sum(1 for it in items if it["verdict"] == "accept")
    flagged = sum(1 for it in items if it["verdict"] == "flag")
    rejected = sum(1 for it in items if it["verdict"] == "reject")

    return {
        "trip_id": rule_report.get("trip_id", "unknown"),
        "generated_at": "",
        "summary": {
            "total_items": len(items),
            "accepted": accepted,
            "flagged": flagged,
            "rejected": rejected,
        },
        "items": items,
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: merge_report.py <rule-report.json> <codex-report.json>", file=sys.stderr)
        sys.exit(2)

    rule_report = json.loads(Path(sys.argv[1]).read_text())
    codex_report = json.loads(Path(sys.argv[2]).read_text())

    merged = merge_reports(rule_report, codex_report)
    json.dump(merged, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
