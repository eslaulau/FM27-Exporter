#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-save routing for the FM27 named player match-history archive."""
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def run_archiver(a, target: Path):
    cmd = [sys.executable, str(a.archive_script), "--export-dir", str(a.export_dir),
           "--archive-dir", str(target), "--team-id", str(a.team_id), "--club-uid", str(a.club_uid)]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def conflict(result) -> bool:
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    return "SAVE-BRANCH CONFLICT" in output or "PLAYER-ROW CONFLICT" in output


def next_branch(base: Path, current: Path | None):
    for n in range(1, 10000):
        candidate = base if n == 1 else base.with_name(f"{base.name}_branch_{n:03d}")
        if current is not None and candidate.resolve(strict=False) == current.resolve(strict=False): continue
        if (candidate / "player-match-history-archive.json").exists() or (candidate / "archive-manifest.json").exists(): continue
        return candidate, n
    raise RuntimeError("Could not allocate a fresh isolated history archive branch.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-script", required=True, type=Path)
    p.add_argument("--export-dir", required=True, type=Path)
    p.add_argument("--save-path", required=True, type=Path)
    p.add_argument("--archive-root", required=True, type=Path)
    p.add_argument("--team-id", type=int, default=539)
    p.add_argument("--club-uid", type=int, default=680)
    a = p.parse_args()
    for path, label in ((a.archive_script,"archive helper"),(a.export_dir,"export folder")):
        if not path.exists(): raise FileNotFoundError(f"{label} not found: {path}")
    norm = os.path.normcase(str(a.save_path.expanduser().resolve(strict=False)))
    key = hashlib.sha256(norm.encode("utf-8")).hexdigest()
    root = a.archive_root.resolve()
    route_file = root / ".routes" / (key + ".json")
    stem = re.sub(r"[^A-Za-z0-9._-]+","_",a.save_path.stem).strip("._-") or "FM27_Save"
    base = root / f"{stem}_{key[:12]}"
    if route_file.is_file():
        route = json.loads(route_file.read_text(encoding="utf-8-sig"))
        if route.get("save_path_key") != key: raise RuntimeError(f"Route key mismatch: {route_file}")
        raw_dir = route.get("archive_dir")
        if not isinstance(raw_dir,str) or not raw_dir.strip(): raise RuntimeError(f"Route has no archive_dir: {route_file}")
        target = Path(raw_dir).expanduser()
        if not target.is_absolute(): target = (route_file.parent / target).resolve()
        source = str(route.get("source") or "saved_route")
        branch = int(route.get("branch_number") or 1)
    else:
        target, branch = next_branch(base,None)
        source = "new_save_archive"
    first = run_archiver(a,target)
    if first.stdout: print(first.stdout.rstrip())
    if first.stderr: print(first.stderr.rstrip(),file=sys.stderr)
    if first.returncode and conflict(first):
        target,branch = next_branch(base,target)
        print("HISTORY ARCHIVE ISOLATED: conflicting old history was not modified.")
        print(f"Retrying with isolated branch {branch:03d}: {target}")
        result = run_archiver(a,target)
        if result.stdout: print(result.stdout.rstrip())
        if result.stderr: print(result.stderr.rstrip(),file=sys.stderr)
        if result.returncode: return result.returncode or 2
        source = "automatic_conflict_isolation"
    elif first.returncode:
        return first.returncode or 2
    payload = {
        "route_version":1, "save_path_key":key, "save_file_name":a.save_path.name,
        "archive_dir":str(target.resolve()), "source":source, "branch_number":branch,
        "updated_at_utc":datetime.now(timezone.utc).isoformat(),
        "note":"Path-scoped route. Conflicting fixture/player history is forked, never merged."
    }
    atomic_json(route_file,payload)
    print("HISTORY ARCHIVE ROUTE OK")
    print(json.dumps({"archive_dir":str(target.resolve()),"route_file":str(route_file.resolve()),
                      "branch_number":branch,"source":source,"branch_guard":"passed"},
                     ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        print("ERROR: "+str(exc),file=sys.stderr)
        raise SystemExit(2)
