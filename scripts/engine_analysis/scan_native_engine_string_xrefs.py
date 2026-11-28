#!/usr/bin/env python3
"""Locate native FM27 match/ball engine functions from embedded symbol/assertion strings.

This is a focused read-only PE scan. It finds exact ASCII/UTF-16 string RVAs,
then finds x64 RIP-relative code references and static VA/RVA pointers to those
strings. It maps code sites to PE .pdata runtime function bounds for Ghidra.
"""
from __future__ import annotations
import argparse, bisect, json, mmap, re, struct
from collections import defaultdict
from pathlib import Path

DEFAULT_TERMS = [
    "simatch::MATCH::play",
    "MATCH_BALL::iterate_one_slice",
    "iterate_one_slice",
    "MATCH_BALL",
    "match_ball_path",
    "ball_velocity",
    "ball_position",
    "goalkeeper_save",
    "goal_line",
    "shot_result",
]

def parse_pe(mm):
    if mm[:2] != b"MZ":
        raise ValueError("not an MZ executable")
    peoff=struct.unpack_from("<I",mm,0x3c)[0]
    if mm[peoff:peoff+4] != b"PE\0\0":
        raise ValueError("PE signature missing")
    coff=peoff+4
    machine,nsects,_,_,_,opt_size,_=struct.unpack_from("<HHIIIHH",mm,coff)
    opt=coff+20
    magic=struct.unpack_from("<H",mm,opt)[0]
    if magic!=0x20b:
        raise ValueError(f"expected PE32+, got {magic:#x}")
    image_base=struct.unpack_from("<Q",mm,opt+24)[0]
    image_size=struct.unpack_from("<I",mm,opt+56)[0]
    headers_size=struct.unpack_from("<I",mm,opt+60)[0]
    ex_rva,ex_size=struct.unpack_from("<II",mm,opt+112+3*8)
    sections=[]
    sh=opt+opt_size
    for i in range(nsects):
        off=sh+i*40
        name=mm[off:off+8].split(b"\0",1)[0].decode("ascii","replace")
        vs,va,rs,rp=struct.unpack_from("<IIII",mm,off+8)
        flags=struct.unpack_from("<I",mm,off+36)[0]
        sections.append({"name":name,"va":va,"virtual_size":vs,"raw_size":rs,
                         "raw_ptr":rp,"executable":bool(flags&0x20000000)})
    return image_base,image_size,headers_size,ex_rva,ex_size,sections

def rva_to_raw(rva,headers,sections):
    if rva<headers: return rva
    for s in sections:
        if s["va"]<=rva<s["va"]+s["raw_size"]:
            return s["raw_ptr"]+rva-s["va"]
    return None

def scan_strings(mm,sections,terms):
    hits=[]
    seen=set()
    for term in terms:
        raw=term.encode("ascii","ignore")
        encodings=((raw,"ascii"),(term.encode("utf-16le"),"utf16le"))
        for sec in sections:
            lo=sec["raw_ptr"]; hi=min(lo+sec["raw_size"],len(mm))
            for needle,label in encodings:
                pos=mm.find(needle,lo,hi)
                while pos!=-1:
                    rva=sec["va"]+pos-sec["raw_ptr"]
                    key=(term,label,rva)
                    if key not in seen:
                        seen.add(key)
                        hits.append({"term":term,"encoding":label,"rva":rva,
                                     "section":sec["name"],"file_offset":pos,
                                     "length":len(needle)})
                    pos=mm.find(needle,pos+1,hi)
    hits.sort(key=lambda x:(x["term"].lower(),x["rva"]))
    return hits

def scan_refs(mm,sections,image_base,strings):
    # String RVAs indexed by start/end so references into the string contents
    # are also recognized. RIP-relative operands are the common x64 idiom.
    by_start=defaultdict(list)
    for h in strings:
        by_start[h["rva"]].append(h)
    starts=sorted(by_start)
    all_hits=[]
    patterns=[]
    # REX + opcode + ModRM (mod=00, r/m=101); disp32 at +3, len 7 (or 10 for C7).
    rex_ops=b"\x8d\x8b\x89\x3b\x39\x85\xc7"
    rex_regex=re.compile(rb"[\x40-\x4f]["+rex_ops+rb"][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]")
    plain_ops=b"\x8d\x8b\x89\x3b\x39\x85"
    plain_regex=re.compile(rb"["+plain_ops+rb"][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]")
    indirect_regex=re.compile(rb"\xff[\x15\x25]")
    def add(sec,pos,ins_len,disp,kind):
        site=sec["va"]+pos
        target=site+ins_len+disp
        idx=bisect.bisect_right(starts,target)-1
        if idx<0: return
        sr=starts[idx]
        for h in by_start[sr]:
            if target < h["rva"]+h["length"]:
                all_hits.append({
                    "from_rva":f"0x{site:X}","to_rva":f"0x{h['rva']:X}",
                    "reference_kind":kind,"target_name":h["term"],
                    "instruction_pattern":kind,
                    "caller_function_rva":"","caller_function_end_rva":"",
                    "unwind_info_rva":"","target_encoding":h["encoding"]
                })
    for sec in sections:
        if not sec["executable"] or sec["raw_size"]<8: continue
        lo=sec["raw_ptr"]; hi=min(lo+sec["raw_size"],len(mm))
        blob=mm[lo:hi]
        for m in rex_regex.finditer(blob):
            pos=m.start(); op=blob[pos+1]
            ins_len=10 if op==0xc7 else 7
            if pos+ins_len<=len(blob):
                disp=struct.unpack_from("<i",blob,pos+3)[0]
                add(sec,pos,ins_len,disp,"RIP_REL_REX")
        for m in plain_regex.finditer(blob):
            pos=m.start()
            if pos>0 and 0x40<=blob[pos-1]<=0x4f: continue
            if pos+6<=len(blob):
                disp=struct.unpack_from("<i",blob,pos+2)[0]
                add(sec,pos,6,disp,"RIP_REL")
        for m in indirect_regex.finditer(blob):
            pos=m.start()
            if pos+6<=len(blob):
                disp=struct.unpack_from("<i",blob,pos+2)[0]
                add(sec,pos,6,disp,"RIP_INDIRECT")
    # Non-executable sections: absolute VA and 32-bit module-relative pointers.
    static=[]
    for sec in sections:
        if sec["executable"] or sec["raw_size"]<4: continue
        lo=sec["raw_ptr"]; hi=min(lo+sec["raw_size"],len(mm)); blob=mm[lo:hi]
        for h in strings:
            for encoded,kind in ((struct.pack("<Q",image_base+h["rva"]),"ABSOLUTE_VA"),
                                 (struct.pack("<I",h["rva"]),"MODULE_RVA32")):
                pos=blob.find(encoded)
                while pos!=-1:
                    static.append({"section":sec["name"],
                        "file_offset":f"0x{lo+pos:X}",
                        "section_rva":f"0x{sec['va']+pos:X}",
                        "target_rva":f"0x{h['rva']:X}",
                        "target_name":h["term"],"encoding":kind})
                    pos=blob.find(encoded,pos+1)
    return all_hits,static

def map_callers(mm,headers,sections,ex_rva,ex_size,image_size,code_refs,image_base):
    off=rva_to_raw(ex_rva,headers,sections)
    ranges=[]
    if off is not None and ex_size:
        for pos in range(off,min(off+ex_size,len(mm))-11,12):
            b,e,u=struct.unpack_from("<III",mm,pos)
            if b<e<=image_size:
                ranges.append((b,e,u))
    ranges.sort()
    starts=[x[0] for x in ranges]
    for h in code_refs:
        site=int(h["from_rva"],16)
        i=bisect.bisect_right(starts,site)-1
        if i>=0:
            b,e,u=ranges[i]
            if b<=site<e:
                h["caller_function_rva"]=f"0x{b:X}"
                h["caller_function_end_rva"]=f"0x{e:X}"
                h["unwind_info_rva"]=f"0x{u:X}"
    return len(ranges)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--binary",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--term",action="append",default=[])
    args=ap.parse_args()
    terms=args.term or DEFAULT_TERMS
    args.out.mkdir(parents=True,exist_ok=True)
    with args.binary.open("rb") as f:
        mm=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
        try:
            image_base,image_size,headers,ex_rva,ex_size,sections=parse_pe(mm)
            strings=scan_strings(mm,sections,terms)
            refs,static=scan_refs(mm,sections,image_base,strings)
            runtime_count=map_callers(mm,headers,sections,ex_rva,ex_size,image_size,refs,image_base)
            (args.out/"native-engine-string-hits.json").write_text(json.dumps(strings,indent=2),encoding="utf-8")
            (args.out/"native-engine-string-xrefs.json").write_text(json.dumps(refs,indent=2),encoding="utf-8")
            with (args.out/"native-engine-string-hits.tsv").open("w",encoding="utf-8") as o:
                o.write("term\tencoding\trva\tsection\tfile_offset\tlength\n")
                for h in strings:
                    o.write(f'{h["term"]}\t{h["encoding"]}\t0x{h["rva"]:X}\t{h["section"]}\t0x{h["file_offset"]:X}\t{h["length"]}\n')
            with (args.out/"native-engine-string-xrefs.tsv").open("w",encoding="utf-8") as o:
                o.write("from_rva\tto_rva\treference_kind\ttarget_name\tinstruction_pattern\tcaller_function_rva\tcaller_function_end_rva\tunwind_info_rva\n")
                for h in refs:
                    o.write("\t".join(h[k] for k in ("from_rva","to_rva","reference_kind","target_name","instruction_pattern","caller_function_rva","caller_function_end_rva","unwind_info_rva"))+"\n")
            with (args.out/"native-engine-string-static-pointers.tsv").open("w",encoding="utf-8") as o:
                o.write("section\tfile_offset\tsection_rva\ttarget_rva\ttarget_name\tencoding\n")
                for h in static:
                    o.write("\t".join(h[k] for k in ("section","file_offset","section_rva","target_rva","target_name","encoding"))+"\n")
            summary={"image_base":f"0x{image_base:X}","runtime_function_count":runtime_count,
                     "term_count":len(terms),"string_hits":len(strings),
                     "code_string_references":len(refs),"static_string_pointers":len(static),
                     "terms":terms}
            (args.out/"native-engine-string-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
            print(json.dumps(summary,indent=2))
            if not strings:
                raise SystemExit("none of the requested native engine strings were found")
        finally:
            mm.close()

if __name__=="__main__":
    main()
