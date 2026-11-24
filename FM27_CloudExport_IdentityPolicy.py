#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate cloud-export player identity accounting without requiring zero unresolved rows.

Unknown identities remain explicitly unresolved in the report. This policy allows a
useful partial report to be published, but rejects inconsistent accounting or a
report with no identified appearances at all.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def evaluate_identity_coverage(audit: dict[str, Any]) -> dict[str, Any]:
    scope = audit.get("scope")
    if not isinstance(scope, dict):
        raise ValueError("identity audit is missing the scope object")

    def count(name: str) -> int:
        value = scope.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"scope.{name} must be a non-negative integer")
        return value

    identified = count("identified_appearance_rows")
    actual = count("actual_appearance_rows")
    unresolved = count("unresolved_appearance_rows")

    if actual == 0:
        raise ValueError("no active player appearances were detected")
    if identified == 0:
        raise ValueError("no player appearances could be identified; refusing to publish an unusable report")
    if identified + unresolved != actual:
        raise ValueError(
            "identity accounting mismatch: "
            f"identified ({identified}) + unresolved ({unresolved}) != actual appearances ({actual})"
        )

    complete = unresolved == 0
    return {
        "status": "complete" if complete else "partial",
        "complete": complete,
        "identified_appearances": identified,
        "actual_appearances": actual,
        "unresolved_appearances": unresolved,
        "identified_share": round(identified / actual, 6),
        "policy": "publish_partial_with_explicit_unresolved_rows; never infer or fabricate player identities",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("identity_audit", type=Path)
    args = parser.parse_args()
    try:
        audit = json.loads(args.identity_audit.read_text(encoding="utf-8-sig"))
        if not isinstance(audit, dict):
            raise ValueError("identity audit root must be a JSON object")
        result = evaluate_identity_coverage(audit)
    except Exception as exc:
        print(f"IDENTITY_POLICY_ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
