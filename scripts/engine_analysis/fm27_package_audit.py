#!/usr/bin/env python3
"""Read-only inventory and targeted string/metadata audit for an FM27 engine package."""
from __future__ import annotations
import argparse, hashlib, json, mmap, re, struct
from pathlib import Path

EXPECTED = {
    "game_plugin.dll": "fm_Data/Plugins/x86_64/game_plugin.dll",
    "GameAssembly.dll": "GameAssembly.dll",
    "UnityPlayer.dll": "UnityPlayer.dll",
    "fm.exe": "fm.exe",
    "global-metadata.dat": "fm_Data/il2cpp_data/Metadata/global-metadata.dat",
    "simatch.fmf": "shared/data/simatch.fmf",
    "simatchshared.fmf": "shared/data/simatchshared.fmf",
}
TOKENS = (
    b"match", b"tactic", b"press", b"movement", b"decision", b"scoring",
    b"player", b"ball", b"shoot", b"pass", b"dribbl", b"position",
    b"weight", b"attack", b"defend", b"cross", b"mark", b"intercept",
    b"offside", b"counter", b"role", b"duty", b"instruction",
    b"iterate_one_slice", b"setup_basic_tactical_positions", b"load_tactics",
    b"oop_attributes_scoring", b"oop_pitch_proximity_scores",
)

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def rva_to_offset(rva: int, sections: list[dict], headers: int):
    if rva < headers: return rva
    for s in sections:
        if s["va"] <= rva < s["va"] + s["raw_size"]:
            return s["raw_ptr"] + rva - s["va"]
    return None

def pe_summary(path: Path) -> dict:
    with path.open("rb") as f:
        head = f.read(0x100)
        if len(head) < 0x40 or head[:2] != b"MZ": return {"is_pe": False}
        peoff = struct.unpack_from("<I", head, 0x3C)[0]
        f.seek(peoff)
        if f.read(4) != b"PE\0\0": return {"is_pe": False}
        machine, nsects, timestamp, _, _, opt_size, characteristics = struct.unpack("<HHIIIHH", f.read(20))
        opt = f.read(opt_size)
        magic = struct.unpack_from("<H", opt, 0)[0]
        if magic == 0x20B: image_base, dd_off, is64 = struct.unpack_from("<Q", opt, 24)[0], 112, True
        elif magic == 0x10B: image_base, dd_off, is64 = struct.unpack_from("<I", opt, 28)[0], 96, False
        else: return {"is_pe": False, "optional_magic": hex(magic)}
        entry, image_size, headers_size = struct.unpack_from("<I", opt, 16)[0], struct.unpack_from("<I", opt, 56)[0], struct.unpack_from("<I", opt, 60)[0]
        sections = []
        for _ in range(nsects):
            row = f.read(40)
            if len(row) != 40: break
            name, vs, va, rs, rp, _, _, _, _, flags = struct.unpack("<8sIIIIIIHHI", row)
            sections.append({"name":name.rstrip(b"\0").decode("ascii","replace"),"va":va,"raw_size":rs,"raw_ptr":rp,"virtual_size":vs,"flags":hex(flags),"executable":bool(flags&0x20000000)})
        dirs = [struct.unpack_from("<II",opt,dd_off+i*8) for i in range(min(16,max(0,(len(opt)-dd_off)//8)))]
        imports=[]
        if len(dirs)>1 and dirs[1][0]:
            io=rva_to_offset(dirs[1][0],sections,headers_size)
            if io is not None:
                f.seek(io)
                for i in range(4096):
                    desc=f.read(20)
                    if len(desc)!=20: break
                    oft,_,_,name_rva,ft=struct.unpack("<IIIII",desc)
                    if not any((oft,name_rva,ft)): break
                    no=rva_to_offset(name_rva,sections,headers_size)
                    if no is not None:
                        f.seek(no); imports.append(f.read(512).split(b"\0",1)[0].decode("ascii","replace"))
                    f.seek(io+(i+1)*20)
        return {"is_pe":True,"machine":hex(machine),"pe32_plus":is64,"timestamp":timestamp,
                "image_base":hex(image_base),"entry_rva":hex(entry),"size_of_image":hex(image_size),
                "characteristics":hex(characteristics),"sections":sections,"import_dlls":imports}

def targeted_strings(path: Path, limit: int = 2500) -> list[str]:
    found=set()
    patterns=((re.compile(rb"[\x20-\x7e]{5,240}"),False),(re.compile(rb"(?:[\x20-\x7e]\x00){5,240}"),True))
    with path.open("rb") as f:
        mm=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
        try:
            for regex,wide in patterns:
                for m in regex.finditer(mm):
                    raw=m.group(0)
                    if any(t in raw.lower() for t in TOKENS):
                        s=raw.decode("utf-16le" if wide else "ascii","replace").strip()
                        if s: found.add(s)
                        if len(found)>=limit: break
                if len(found)>=limit: break
        finally: mm.close()
    return sorted(found,key=str.casefold)


def native_rtti_scan(path: Path, pe: dict, out_dir: Path) -> dict:
    """Recover MSVC x64 type descriptors, complete-object locators and vtable slots."""
    if not pe.get("is_pe") or not pe.get("pe32_plus"):
        return {"supported": False, "reason": "not a PE32+ image"}
    image_base = int(pe["image_base"], 16)
    image_size = int(pe["size_of_image"], 16)
    sections = pe.get("sections", [])
    data_sections = [s for s in sections if not s.get("executable") and s["raw_size"] >= 64]
    exec_ranges = [(s["va"], s["va"] + max(s["virtual_size"], s["raw_size"])) for s in sections if s.get("executable")]

    def raw_to_rva(off: int):
        for s in sections:
            if s["raw_ptr"] <= off < s["raw_ptr"] + s["raw_size"]:
                return s["va"] + off - s["raw_ptr"]
        return None

    def is_exec(rva: int):
        return any(a <= rva < b for a, b in exec_ranges)

    def demangle(name: str):
        name = name.strip("\0")
        if name.startswith(".?AV") or name.startswith(".?AU") or name.startswith(".?AT"):
            name = name[4:]
        if name.endswith("@@"):
            name = name[:-2]
        parts = [p for p in name.split("@") if p]
        return "::".join(reversed(parts)) if parts else name

    type_descs = {}
    decorated_re = re.compile(rb"\.\?[AVUT][A-Za-z0-9_?$@.,<> -]{2,220}?@@")
    with path.open("rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            for sec in data_sections:
                lo = sec["raw_ptr"]
                hi = min(lo + sec["raw_size"], len(mm))
                for match in decorated_re.finditer(mm, lo, hi):
                    name_start = match.start()
                    td_off = name_start - 16
                    if td_off < lo:
                        continue
                    td_rva = raw_to_rva(td_off)
                    if td_rva is not None:
                        type_descs[td_rva] = match.group(0).decode("ascii", "replace")

            # MSVC x64 CompleteObjectLocator: six 32-bit fields; pSelf is
            # the RVA of the locator itself and pTypeDescriptor is an RVA.
            locators = {}
            for sec in data_sections:
                lo = (sec["raw_ptr"] + 3) & ~3
                hi = min(sec["raw_ptr"] + sec["raw_size"] - 24, len(mm) - 24)
                for off in range(lo, hi, 4):
                    sig, obj_off, cd_off, td_rva, chd_rva, self_rva = struct.unpack_from("<6I", mm, off)
                    if sig != 1 or self_rva >= image_size or td_rva not in type_descs:
                        continue
                    if raw_to_rva(off) != self_rva:
                        continue
                    locators[self_rva] = {
                        "type_descriptor_rva": td_rva,
                        "class_hierarchy_rva": chd_rva,
                        "object_offset": obj_off,
                        "cd_offset": cd_off,
                        "decorated_name": type_descs[td_rva],
                        "type_name": demangle(type_descs[td_rva]),
                    }

            # Find vftable[-1] pointers to each COL, then collect executable slots.
            col_by_va = {image_base + rva: rva for rva in locators}
            tables = []
            for sec in data_sections:
                lo = (sec["raw_ptr"] + 7) & ~7
                hi = min(sec["raw_ptr"] + sec["raw_size"] - 8, len(mm) - 8)
                for off in range(lo, hi, 8):
                    ptr = struct.unpack_from("<Q", mm, off)[0]
                    col_rva = col_by_va.get(ptr)
                    if col_rva is None:
                        continue
                    vft_off = off + 8
                    vft_rva = raw_to_rva(vft_off)
                    slots = []
                    for i in range(64):
                        slot_off = vft_off + i * 8
                        if slot_off + 8 > len(mm):
                            break
                        target = struct.unpack_from("<Q", mm, slot_off)[0]
                        if target < image_base or target >= image_base + image_size:
                            break
                        target_rva = target - image_base
                        if not is_exec(target_rva):
                            break
                        slots.append(target_rva)
                    if slots:
                        info = dict(locators[col_rva])
                        info.update({
                            "col_rva": col_rva,
                            "vftable_rva": vft_rva,
                            "slot_count": len(slots),
                            "slot_rvas": [f"0x{x:X}" for x in slots],
                        })
                        tables.append(info)

            important = re.compile(
                r"(MATCH|TACTIC|PRESS|SCOR|WEIGHT|MOVEMENT|PLAYER|BALL|DECISION|POSITION|"
                r"ROLE|OOP|IN.?POSSESSION|OUT.?OF.?POSSESSION|SIMATCH)",
                re.IGNORECASE,
            )
            native_namespace = re.compile(r"^simatch(shared)?::", re.IGNORECASE)
            engine_terms = re.compile(
                r"(MATCH|TACTIC|ROLE|PRESS|MOVEMENT|POSITION|BALL|PLAYER_INSTRUCTION|"
                r"SCOR|WEIGHT|DECISION|INPUT|SHOT_ZONE|XG|TEAM_SELECTOR|PLAYING_DATA)",
                re.IGNORECASE,
            )
            relevant_types = [
                {
                    "type_descriptor_rva": f"0x{rva:X}",
                    "decorated_name": name,
                    "type_name": demangle(name),
                }
                for rva, name in type_descs.items()
                if important.search(name)
            ]
            relevant_tables = [t for t in tables if important.search(t["decorated_name"])]
            relevant_tables.sort(key=lambda x: (x["type_name"], x["vftable_rva"]))

            out_dir.mkdir(parents=True, exist_ok=True)
            # Recover common x64 RIP-relative code references to RTTI type descriptors
            # and vftables. This is a bounded byte-pattern index, not a full disassembly.
            ref_targets = {}
            for rva, decorated in type_descs.items():
                name = demangle(decorated)
                if native_namespace.search(name) and engine_terms.search(name):
                    ref_targets[rva] = ("TYPE_DESCRIPTOR", name)
            for table in tables:
                name = table["type_name"]
                if native_namespace.search(name) and engine_terms.search(name):
                    ref_targets[table["vftable_rva"]] = ("VFTABLE", name)

            code_xrefs = []
            # REX.W/R + common RIP-relative memory operands: LEA/MOV/CMP/TEST/etc.
            rex_ops = {0x8D, 0x8B, 0x89, 0x3B, 0x39, 0x85, 0xC7}
            plain_ops = {0x8D, 0x8B, 0x89, 0x3B, 0x39, 0x85}
            for sec in sections:
                if not sec.get("executable") or sec["raw_size"] < 8:
                    continue
                lo = sec["raw_ptr"]
                hi = min(lo + sec["raw_size"], len(mm))
                blob = mm[lo:hi]
                length = len(blob)
                for pos in range(max(0, length - 10)):
                    first = blob[pos]
                    second = blob[pos + 1]
                    if 0x40 <= first <= 0x4F and second in rex_ops and pos + 7 <= length:
                        modrm = blob[pos + 2]
                        if (modrm & 0xC7) == 0x05:
                            disp = struct.unpack_from("<i", blob, pos + 3)[0]
                            ins_len = 10 if second == 0xC7 else 7
                            target_rva = sec["va"] + pos + ins_len + disp
                            if target_rva in ref_targets:
                                kind, name = ref_targets[target_rva]
                                code_xrefs.append({
                                    "from_rva": f"0x{sec['va'] + pos:X}",
                                    "to_rva": f"0x{target_rva:X}",
                                    "reference_kind": kind,
                                    "target_name": name,
                                    "instruction_pattern": f"{first:02X} {second:02X} {modrm:02X}",
                                })
                    elif first in plain_ops and pos + 6 <= length:
                        modrm = blob[pos + 1]
                        # The previous iteration already handled REX+opcode+ModRM.
                        # Skip this opcode-only view of the same instruction.
                        if pos > 0 and 0x40 <= blob[pos - 1] <= 0x4F and (modrm & 0xC7) == 0x05:
                            continue
                        if (modrm & 0xC7) == 0x05:
                            disp = struct.unpack_from("<i", blob, pos + 2)[0]
                            target_rva = sec["va"] + pos + 6 + disp
                            if target_rva in ref_targets:
                                kind, name = ref_targets[target_rva]
                                code_xrefs.append({
                                    "from_rva": f"0x{sec['va'] + pos:X}",
                                    "to_rva": f"0x{target_rva:X}",
                                    "reference_kind": kind,
                                    "target_name": name,
                                    "instruction_pattern": f"{first:02X} {modrm:02X}",
                                })
                    elif first == 0xFF and pos + 6 <= length and blob[pos + 1] in (0x15, 0x25):
                        disp = struct.unpack_from("<i", blob, pos + 2)[0]
                        target_rva = sec["va"] + pos + 6 + disp
                        if target_rva in ref_targets:
                            kind, name = ref_targets[target_rva]
                            code_xrefs.append({
                                "from_rva": f"0x{sec['va'] + pos:X}",
                                "to_rva": f"0x{target_rva:X}",
                                "reference_kind": kind,
                                "target_name": name,
                                "instruction_pattern": f"FF {blob[pos+1]:02X}",
                            })

            # Collapse repeated byte-pattern hits but preserve distinct call sites.
            code_xrefs = list({
                (x["from_rva"], x["to_rva"], x["instruction_pattern"]): x
                for x in code_xrefs
            }.values())
            code_xrefs.sort(key=lambda x: (int(x["to_rva"], 16), int(x["from_rva"], 16)))

            # Map each candidate code reference to its containing x64 function
            # using PE .pdata RUNTIME_FUNCTION entries.
            runtime_functions = []
            for sec in sections:
                if sec["name"] != ".pdata":
                    continue
                off = sec["raw_ptr"]
                limit = min(off + sec["raw_size"], len(mm))
                while off + 12 <= limit:
                    begin_rva, end_rva, unwind_rva = struct.unpack_from("<3I", mm, off)
                    if (begin_rva < end_rva <= image_size and
                        is_exec(begin_rva) and is_exec(end_rva - 1) and
                        unwind_rva < image_size):
                        runtime_functions.append((begin_rva, end_rva, unwind_rva))
                    off += 12
            runtime_functions.sort()
            runtime_starts = [x[0] for x in runtime_functions]
            for x in code_xrefs:
                caller_rva = int(x["from_rva"], 16)
                idx = bisect.bisect_right(runtime_starts, caller_rva) - 1
                if idx >= 0:
                    begin_rva, end_rva, unwind_rva = runtime_functions[idx]
                    if begin_rva <= caller_rva < end_rva:
                        x["caller_function_rva"] = f"0x{begin_rva:X}"
                        x["caller_function_end_rva"] = f"0x{end_rva:X}"
                        x["unwind_info_rva"] = f"0x{unwind_rva:X}"

            (out_dir / "native-rtti-code-xrefs.json").write_text(
                json.dumps({
                    "method": "x64 RIP-relative operand pattern scan over executable sections",
                    "note": "Candidate references only; confirm each address by Ghidra disassembly.",
                    "target_count": len(ref_targets),
                    "reference_count": len(code_xrefs),
                    "runtime_function_count": len(runtime_functions),
                    "references": code_xrefs,
                }, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            with (out_dir / "native-rtti-code-xrefs.tsv").open("w", encoding="utf-8") as xout:
                xout.write("from_rva\tto_rva\treference_kind\ttarget_name\tinstruction_pattern\tcaller_function_rva\tcaller_function_end_rva\tunwind_info_rva\n")
                for x in code_xrefs:
                    xout.write(
                        f'{x["from_rva"]}\t{x["to_rva"]}\t{x["reference_kind"]}\t'
                        f'{x["target_name"]}\t{x["instruction_pattern"]}\t{x.get("caller_function_rva","")}\t{x.get("caller_function_end_rva","")}\t{x.get("unwind_info_rva","")}\n'
                    )

            json_path = out_dir / "native-rtti-vtables.json"
            json_path.write_text(json.dumps({
                "type_descriptor_count": len(type_descs),
                "complete_object_locator_count": len(locators),
                "vtable_count": len(tables),
                "relevant_type_descriptor_count": len(relevant_types),
                "relevant_vtable_count": len(relevant_tables),
                "relevant_types": sorted(relevant_types, key=lambda x: x["type_name"]),
                "relevant_vtables": relevant_tables,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            tsv_path = out_dir / "native-rtti-vtables.tsv"
            with tsv_path.open("w", encoding="utf-8") as out:
                out.write("type_name\ttype_descriptor_rva\tcol_rva\tvftable_rva\tslot_count\tslot_rvas\n")
                for t in relevant_tables:
                    out.write(
                        f'{t["type_name"]}\t0x{t["type_descriptor_rva"]:X}\t'
                        f'0x{t["col_rva"]:X}\t0x{t["vftable_rva"]:X}\t'
                        f'{t["slot_count"]}\t{",".join(t["slot_rvas"])}\n'
                    )
            return {
                "supported": True,
                "type_descriptor_count": len(type_descs),
                "complete_object_locator_count": len(locators),
                "vtable_count": len(tables),
                "relevant_type_descriptor_count": len(relevant_types),
                "relevant_vtable_count": len(relevant_tables),
                "json": str(json_path),
                "tsv": str(tsv_path),
            }
        finally:
            mm.close()

def metadata_strings(path: Path) -> dict:
    data=path.read_bytes()
    if len(data)<32: return {"valid_magic":False,"size":len(data)}
    magic,version=struct.unpack_from("<Ii",data,0)
    if magic!=0xFAB11BAF: return {"valid_magic":False,"magic":hex(magic),"version":version,"size":len(data)}
    def pair(pos):
        a,b=struct.unpack_from("<II",data,pos)
        return (a,b) if a<=len(data) and b<=len(data) and a+b<=len(data) else None
    literal_pair, literal_bytes_pair, heap_pair = pair(8),pair(16),pair(24)
    hits=[]
    if heap_pair:
        start,size=heap_pair
        heap=data[start:start+size]
        for m in re.finditer(rb"[\x20-\x7e]{3,240}\0",heap):
            s=m.group(0)[:-1].decode("ascii","replace")
            if any(t.decode() in s.lower() for t in TOKENS): hits.append(s)
    literals=[]
    if literal_pair and literal_bytes_pair:
        table_off,table_size=literal_pair
        bytes_off,bytes_size=literal_bytes_pair
        table=data[table_off:table_off+table_size]
        blob=data[bytes_off:bytes_off+bytes_size]
        for p in range(0,len(table)-7,8):
            n,index=struct.unpack_from("<II",table,p)
            if 0<n<=4096 and index+n<=len(blob):
                s=blob[index:index+n].decode("utf-8","replace").strip("\0")
                if s and any(t.decode() in s.lower() for t in TOKENS): literals.append(s)
    return {"valid_magic":True,"version":version,"size":len(data),
            "string_heap":{"offset":heap_pair[0] if heap_pair else None,"size":heap_pair[1] if heap_pair else None,"matched_strings":sorted(set(hits),key=str.casefold)},
            "string_literals":sorted(set(literals),key=str.casefold),
            "note":"Header and string extraction only; not a complete MethodDefinition-to-native-RVA map."}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    root=args.root.resolve(); out=args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
    by_name={p.name.casefold():p for p in root.rglob("*") if p.is_file()}
    files=[]; missing=[]
    for name,rel in EXPECTED.items():
        p=root/rel
        if not p.is_file(): p=by_name.get(name.casefold())
        if p is None or not p.is_file(): missing.append(name); continue
        item={"name":name,"path":str(p.relative_to(root)),"size":p.stat().st_size,"sha256":sha256(p)}
        if p.suffix.lower() in (".dll",".exe"):
            item["pe"]=pe_summary(p); item["targeted_strings"]=targeted_strings(p)
            if name=="game_plugin.dll":
                item["native_rtti"] = native_rtti_scan(p, item["pe"], out/"native-rtti")
        if name=="global-metadata.dat": item["metadata"]=metadata_strings(p)
        if name.endswith(".fmf"):
            with p.open("rb") as f: item["header_hex"]=f.read(64).hex()
            item["targeted_strings"]=targeted_strings(p,500)
        files.append(item)
    report={"schema":1,"package_root":str(root),"expected_files":EXPECTED,"missing_files":missing,"files":files}
    (out/"package-audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["FM27 v2 ENGINE PACKAGE AUDIT",f"ROOT={root}",f"MISSING={','.join(missing) if missing else 'NONE'}",""]
    for item in files:
        lines += [f"[{item['name']}]","path="+item["path"],"size="+str(item["size"]),"sha256="+item["sha256"]]
        pe=item.get("pe")
        if pe and pe.get("is_pe"):
            lines += [f"machine={pe['machine']} image_base={pe['image_base']} size_of_image={pe['size_of_image']}","imports="+", ".join(pe.get("import_dlls",[]))]
        meta=item.get("metadata")
        if meta:
            lines += [f"metadata_magic={meta.get('valid_magic')} version={meta.get('version')}",
                      "metadata_strings:"]+meta.get("string_heap",{}).get("matched_strings",[])[:700]+meta.get("string_literals",[])[:700]
        hits=item.get("targeted_strings",[])
        if hits: lines += [f"targeted_strings={len(hits)}"]+hits[:700]
        lines.append("")
    (out/"package-audit.txt").write_text("\n".join(lines),encoding="utf-8")
    print(f"AUDIT_FILES={len(files)} MISSING={len(missing)} OUT={out}")
    return 0 if not missing else 2

if __name__=="__main__": raise SystemExit(main())
