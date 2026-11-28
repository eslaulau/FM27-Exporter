#!/usr/bin/env python3
"""Extract only match/tactics-related IL2CPP method names for Ghidra annotation."""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

PATTERN = re.compile(
    r"(Tactic|TeamInstruction|PlayerInstruction|RoleDataEntry|FormationEntry|"
    r"InPossessionRole|OutOfPossessionRole|GenericTacticData|"
    r"Match|Simulation|Press|Scor|Decision|Movement|Position|"
    r"Attack|Defend|Cross|Pass|Shot|Dribbl|Intercept|Marking|"
    r"Goalkeeper|ForwardRun|Ball)",
    re.IGNORECASE,
)

def clean(value: str) -> str:
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    methods = data.get("ScriptMethod", [])
    selected = []
    seen = set()
    for row in methods:
        name = clean(row.get("Name", ""))
        if not name or not PATTERN.search(name):
            continue
        address = int(row.get("Address", 0))
        if address <= 0:
            continue
        key = (address, name)
        if key in seen:
            continue
        seen.add(key)
        selected.append((
            address, name,
            clean(row.get("Signature", "")),
            clean(row.get("TypeSignature", "")),
        ))
    selected.sort(key=lambda x: (x[0], x[1]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for address, name, signature, type_signature in selected:
            f.write(f"0x{address:X}\t{name}\t{signature}\t{type_signature}\n")
    unique_addresses = len({x[0] for x in selected})
    summary = {
        "input_methods": len(methods),
        "selected_method_entries": len(selected),
        "unique_native_addresses": unique_addresses,
        "output": str(args.output),
    }
    (args.output.parent / "match-relevant-methods-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    if not selected:
        raise SystemExit("No relevant IL2CPP methods selected")

if __name__ == "__main__":
    main()
