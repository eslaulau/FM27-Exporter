#!/usr/bin/env python3
"""Derive FM27 IP/OOP compact role and duty IDs from IL2CPP enums and Ghidra decompilation."""
from __future__ import annotations
import argparse
import csv
import json
import re
from pathlib import Path

ENUMS = [
    ("IP", "InPossessionRole", "104760"),
    ("OOP", "OutOfPossessionRole", "1043b0"),
]

def enum_block(source: str, name: str) -> str:
    m = re.search(r"public enum\s+" + re.escape(name) + r"\b", source)
    if not m:
        raise ValueError(f"enum not found: {name}")
    start = source.find("{", m.end())
    end = source.find("\n}", start)
    if start < 0 or end < 0:
        raise ValueError(f"enum block malformed: {name}")
    return source[start + 1:end]

def parse_enum(source: str, name: str):
    block = enum_block(source, name)
    rows = []
    pattern = re.compile(
        r"public const\s+" + re.escape(name) + r"\s+(\w+)\s*=\s*(\d+)\s*;"
    )
    for role_name, raw in pattern.findall(block):
        value = int(raw)
        if value == 0 or value & (value - 1) == 0:
            rows.append((role_name, value))
    if not rows:
        raise ValueError(f"no flag values parsed for {name}")
    return rows

def method_block(decomp: str, rva: str) -> str:
    marker = re.compile(r"^// ===== 180" + re.escape(rva) + r"\b", re.I | re.M)
    m = marker.search(decomp)
    if not m:
        raise ValueError(f"decompilation missing for helper RVA 0x{rva}")
    nxt = re.search(r"^// ===== ", decomp[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(decomp)
    return decomp[m.start():end]

def parse_converter(block: str) -> dict[int, int]:
    mapping: dict[int, int] = {}
    # Exact switch cases with immediate returns.
    for raw_value, raw_result in re.findall(
        r"case\s+(0x[0-9a-fA-F]+|\d+)\s*:\s*return\s+(0x[0-9a-fA-F]+|\d+)\s*;",
        block,
    ):
        mapping[int(raw_value, 0)] = int(raw_result, 0)
    # Exact if(param_1 == bit) { return compact; } branches.
    for raw_value, raw_result in re.findall(
        r"if\s*\(\s*param_1\s*==\s*(0x[0-9a-fA-F]+|\d+)\s*\)\s*\{\s*return\s+(0x[0-9a-fA-F]+|\d+)\s*;",
        block,
        re.S,
    ):
        mapping[int(raw_value, 0)] = int(raw_result, 0)
    return mapping

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", type=Path, required=True)
    ap.add_argument("--decomp", type=Path, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    args = ap.parse_args()

    dump = args.dump.read_text(encoding="utf-8", errors="replace")
    decomp = args.decomp.read_text(encoding="utf-8", errors="replace")
    args.outdir.mkdir(parents=True, exist_ok=True)

    rows = []
    helper_stats = {}
    for phase, enum_name, rva in ENUMS:
        mapping = parse_converter(method_block(decomp, rva))
        helper_stats[enum_name] = {
            "helper_rva": "0x" + rva.upper(),
            "explicit_mappings": len(mapping),
        }
        for name, bit in parse_enum(dump, enum_name):
            compact = mapping.get(bit, 0)
            kind = "DUTY" if "Duty" in name else "ROLE"
            if bit == 0:
                note = "zero/no-role sentinel"
            elif bit in mapping:
                note = "explicit exact-match mapping in native helper"
            else:
                note = "native helper falls through to return 0 for this exact flag"
            rows.append({
                "phase": phase,
                "kind": kind,
                "enum_name": name,
                "enum_bitmask_hex": f"0x{bit:X}",
                "compact_id_decimal": compact,
                "compact_id_hex": f"0x{compact:X}",
                "helper_rva": f"0x{rva.upper()}",
                "mapping_status": note,
            })

    rows.sort(key=lambda x: (
        x["phase"], x["kind"], int(x["enum_bitmask_hex"], 16)
    ))
    json_path = args.outdir / "role-duty-compact-ids.json"
    tsv_path = args.outdir / "role-duty-compact-ids.tsv"
    summary_path = args.outdir / "role-duty-compact-ids-summary.json"

    json_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with tsv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "enum_entries": len(rows),
        "mapped_entries": sum(
            1 for x in rows
            if x["enum_bitmask_hex"] == "0x0" or
               x["mapping_status"].startswith("explicit")
        ),
        "zero_fallback_entries": sum(
            1 for x in rows
            if x["mapping_status"].startswith("native helper falls")
        ),
        "helpers": helper_stats,
        "files": {
            "json": str(json_path),
            "tsv": str(tsv_path),
        },
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if summary["enum_entries"] < 80:
        raise SystemExit("role/duty enum parse unexpectedly incomplete")
    if summary["zero_fallback_entries"] > 10:
        print("WARNING: multiple enum flags do not map to nonzero compact IDs")

if __name__ == "__main__":
    main()
