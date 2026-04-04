#!/usr/bin/env python3
import sys
import json
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rules.hard_rules import check_hard_rules
from rules.soft_rules import check_soft_rules


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 rules/evaluate.py <itinerary.json> <guardrails.yaml> [--soft]", file=sys.stderr)
        sys.exit(2)

    itinerary_path = Path(sys.argv[1])
    guardrails_path = Path(sys.argv[2])
    include_soft = "--soft" in sys.argv

    if not itinerary_path.exists():
        print(f"Error: {itinerary_path} not found", file=sys.stderr)
        sys.exit(2)
    if not guardrails_path.exists():
        print(f"Error: {guardrails_path} not found", file=sys.stderr)
        sys.exit(2)

    try:
        itinerary = json.loads(itinerary_path.read_text())
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {itinerary_path}: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        guardrails = yaml.safe_load(guardrails_path.read_text())
    except yaml.YAMLError as e:
        print(f"Error: invalid YAML in {guardrails_path}: {e}", file=sys.stderr)
        sys.exit(2)

    hard_violations = check_hard_rules(itinerary, guardrails)
    soft_warnings = check_soft_rules(itinerary, guardrails) if include_soft else []

    report = {
        "hard_violations": hard_violations,
        "soft_warnings": soft_warnings,
        "pass": len(hard_violations) == 0,
    }
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    print()
    sys.exit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
