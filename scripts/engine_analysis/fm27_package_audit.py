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
