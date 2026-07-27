"""Score a human-labeled gold JSONL: extraction precision + verdict accuracy."""
from __future__ import annotations

import argparse
import json


def score(lines) -> dict:
    total = claim_ok = status_labeled = status_ok = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("label_claim_ok") is None:
            continue
        total += 1
        if row["label_claim_ok"]:
            claim_ok += 1
        if row.get("label_status_ok") is not None:
            status_labeled += 1
            if row["label_status_ok"]:
                status_ok += 1
    return {
        "labeled": total,
        "claim_precision": claim_ok / total if total else 0.0,
        "status_accuracy": status_ok / status_labeled if status_labeled else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score labeled gold JSONL")
    parser.add_argument("path")
    args = parser.parse_args()
    with open(args.path, encoding="utf-8") as fh:
        result = score(fh)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
