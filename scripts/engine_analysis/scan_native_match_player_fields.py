#!/usr/bin/env python3
"""Locate native functions that read/write key MATCH_PLAYER and OOP tactic fields."""
from __future__ import annotations
import argparse, json, mmap, struct
from collections import defaultdict
from pathlib import Path

FIELD_LABELS = {
    0x23F1: "MATCH_PLAYER_OOP_SLOT_INDEX",
    0x1300: "MATCH_PLAYER_IP_ROLE_FLAGS_PRIMARY",
    0x12B8: "MATCH_PLAYER_IP_ROLE_FLAGS_MIRROR",
    0x13D8: "MATCH_PLAYER_OOP_ROLE_FLAGS_PRIMARY",
    0x1390: "MATCH_PLAYER_OOP_ROLE_FLAGS_MIRROR",
    0x22D8: "MATCH_PLAYER_IP_ROLE_COMPACT_ID",
    0x22DC: "MATCH_PLAYER_IP_DUTY_COMPACT_ID",
    0x22E0: "MATCH_PLAYER_OOP_ROLE_COMPACT_ID",
    0x22E4: "MATCH_PLAYER_OOP_DUTY_COMPACT_ID",
    0x12C0: "MATCH_PLAYER_OOP_RECORD_PRIMARY",
    0x1278: "MATCH_PLAYER_OOP_RECORD_MIRROR",
    0x1398: "MATCH_PLAYER_SECONDARY_RECORD",
    0x1350: "MATCH_PLAYER_SECONDARY_RECORD_MIRROR",
    0x23CD: "MATCH_PLAYER_DERIVED_SLOT_BYTE",
    0x23CF: "MATCH_PLAYER_TACTIC_REFRESH_BYTE",
    0x23EF: "MATCH_PLAYER_PI_BEHAVIOR_GATE_FLAG",
    0x23A0: "MATCH_PLAYER_SLOT_DERIVED_VALUE",
    0x23C7: "MATCH_PLAYER_SIDE_ORIENTATION_BYTE",
    0x23D0: "MATCH_PLAYER_CANDIDATE_STATE_A",
    0x23D1: "MATCH_PLAYER_CANDIDATE_STATE_B",
    0x23E0: "MATCH_PLAYER_CANDIDATE_GATE_BYTE",
    0x20C0: "MATCH_PLAYER_AUXILIARY_CONTEXT_POINTER",
    0x16E0: "MATCH_PLAYER_SLOT_AUXILIARY_VALUE",
    0x1925: "MATCH_PLAYER_STATE_BYTE",
    0x1938: "TEAM_IP_SLOT_RECORDS",
    0x1C58: "TEAM_IP_MAPPED_SLOT_RECORDS",
    0x1978: "TEAM_OOP_EXTENDED_SLOT_RECORDS",
    0x1C98: "TEAM_OOP_MAPPED_EXTENDED_RECORDS",
    0x1FBC: "TEAM_OOP_SLOT_REMAP",
    0x1820: "TEAM_OOP_SLOT_AUXILIARY_RECORDS",
    0x34C4: "TEAM_TACTIC_REVISION",
    0x1556E: "TEAM_OOP_EXTENDED_MODE_FLAG",
    0x15575: "TEAM_OOP_EXTENDED_MODE_SELECTOR",
    0x154EC: "TEAM_OOP_PLAYER_EXTENSION_MODE",
    0x15340: "TEAM_PLAYER_REVERSE_LOOKUP",
}

def parse_pe(mm):
    if mm[:2] != b"MZ":
        raise ValueError("not an MZ executable")
    peoff = struct.unpack_from("<I", mm, 0x3c)[0]
    if mm[peoff:peoff+4] != b"PE\0\0":
        raise ValueError("PE signature missing")
    coff = peoff+4
    machine, nsects, _, _, _, opt_size, _ = struct.unpack_from("<HHIIIHH", mm, coff)
    opt = coff+20
    magic = struct.unpack_from("<H",mm,opt)[0]
    if magic != 0x20b:
        raise ValueError(f"expected PE32+, got {magic:#x}")
    image_base = struct.unpack_from("<Q",mm,opt+24)[0]
    image_size = struct.unpack_from("<I",mm,opt+56)[0]
    headers_size = struct.unpack_from("<I",mm,opt+60)[0]
    dirs_base = opt+112
    exception_rva, exception_size = struct.unpack_from("<II",mm,dirs_base+3*8)
    sections=[]
    sh=opt+opt_size
    for i in range(nsects):
        off=sh+i*40
        name=mm[off:off+8].split(b"\0",1)[0].decode("ascii","replace")
        vs,va,rs,rp=struct.unpack_from("<IIII",mm,off+8)
        flags=struct.unpack_from("<I",mm,off+36)[0]
        sections.append({"name":name,"va":va,"virtual_size":vs,"raw_size":rs,
                         "raw_ptr":rp,"executable":bool(flags&0x20000000)})
    return image_base,image_size,headers_size,exception_rva,exception_size,sections

def rva_to_raw(rva, headers_size, sections):
    if rva < headers_size:
        return rva
    for s in sections:
        if s["va"] <= rva < s["va"] + s["raw_size"]:
            return s["raw_ptr"] + rva - s["va"]
    return None

def is_executable(rva, sections):
    return any(s["executable"] and s["va"] <= rva < s["va"]+max(s["virtual_size"],s["raw_size"])
               for s in sections)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--binary",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--max-function-size",type=lambda x:int(x,0),default=0x20000)
    args=ap.parse_args()
    try:
        from capstone import Cs, CS_ARCH_X86, CS_MODE_64, CS_OP_MEM
    except ImportError as exc:
        raise SystemExit("capstone is required: pip install capstone==5.0.6") from exc

    args.out.mkdir(parents=True,exist_ok=True)
    with args.binary.open("rb") as f:
        mm=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
        try:
            image_base,image_size,headers_size,ex_rva,ex_size,sections=parse_pe(mm)
            if not ex_rva or ex_size<12:
                raise SystemExit(f"Exception Directory missing: rva={ex_rva:#x}, size={ex_size:#x}")
            ex_off=rva_to_raw(ex_rva,headers_size,sections)
            if ex_off is None:
                raise SystemExit(f"Exception Directory RVA {ex_rva:#x} cannot map to file offset")
            limit=min(ex_off+ex_size,len(mm))
            runtime=[]
            for off in range(ex_off,limit-11,12):
                begin,end,unwind=struct.unpack_from("<III",mm,off)
                if begin<end<=image_size and unwind<image_size and is_executable(begin,sections):
                    runtime.append((begin,end,unwind))
            runtime.sort()
            if not runtime:
                raise SystemExit("no valid RUNTIME_FUNCTION entries in Exception Directory")

            # Stage 1: search executable bytes for the exact disp32 encodings.
            # Stage 2: use Capstone only on functions containing candidate encodings.
            runtime_starts=[x[0] for x in runtime]
            runtime_by_start={a:(b,u) for a,b,u in runtime}
            candidate_fields=defaultdict(set)
            raw_pattern_hits=0
            for sec in sections:
                if not sec["executable"] or sec["raw_size"]<4:
                    continue
                lo=sec["raw_ptr"]
                hi=min(lo+sec["raw_size"],len(mm))
                for disp in FIELD_LABELS:
                    pattern=struct.pack("<I",disp)
                    pos=mm.find(pattern,lo,hi)
                    while pos!=-1:
                        rva=sec["va"]+(pos-sec["raw_ptr"])
                        idx=__import__("bisect").bisect_right(runtime_starts,rva)-1
                        if idx>=0:
                            begin,end,unwind=runtime[idx]
                            if begin<=rva<end:
                                candidate_fields[begin].add(disp)
                                raw_pattern_hits+=1
                        pos=mm.find(pattern,pos+1,hi)

            md=Cs(CS_ARCH_X86,CS_MODE_64)
            md.detail=True
            md.skipdata=True
            hits=[]
            function_fields=defaultdict(set)
            scanned_functions=0
            scanned_bytes=0
            for begin,fields in candidate_fields.items():
                end,unwind=runtime_by_start[begin]
                size=end-begin
                if size<=0 or size>args.max_function_size:
                    continue
                raw=rva_to_raw(begin,headers_size,sections)
                if raw is None or raw+size>len(mm):
                    continue
                scanned_functions+=1
                scanned_bytes+=size
                code=mm[raw:raw+size]
                for ins in md.disasm(code,image_base+begin):
                    if ins.id==0:
                        continue
                    try:
                        operands=ins.operands
                    except Exception:
                        continue
                    found={}
                    for op in operands:
                        if op.type==CS_OP_MEM and op.mem.disp in FIELD_LABELS:
                            access=getattr(op,"access",0)
                            access_name=("R" if access & 1 else "")+("W" if access & 2 else "")
                            if not access_name:
                                access_name="?"
                            try:
                                base_reg=ins.reg_name(op.mem.base) if op.mem.base else ""
                            except Exception:
                                base_reg=""
                            found[op.mem.disp]=(access_name,base_reg)
                    if not found:
                        continue
                    ins_rva=ins.address-image_base
                    for disp,(access_name,base_reg) in sorted(found.items()):
                        hits.append({
                            "field_offset":f"0x{disp:X}",
                            "field_label":FIELD_LABELS[disp],
                            "access":access_name,
                            "base_register":base_reg,
                            "from_rva":f"0x{ins_rva:X}",
                            "function_start_rva":f"0x{begin:X}",
                            "function_end_rva":f"0x{end:X}",
                            "instruction":ins.mnemonic+" "+ins.op_str,
                            "unwind_info_rva":f"0x{unwind:X}",
                        })
                        function_fields[begin].add(disp)

            hits.sort(key=lambda x:(int(x["function_start_rva"],16),
                                    int(x["from_rva"],16),int(x["field_offset"],16)))
            summary={
                "binary":str(args.binary),
                "image_base":f"0x{image_base:X}",
                "image_size":f"0x{image_size:X}",
                "exception_directory_rva":f"0x{ex_rva:X}",
                "exception_directory_size":f"0x{ex_size:X}",
                "runtime_function_entries":len(runtime),
                "candidate_functions":len(candidate_fields),
                "raw_pattern_hits":raw_pattern_hits,
                "scanned_functions":scanned_functions,
                "scanned_function_bytes":scanned_bytes,
                "field_reference_count":len(hits),
                "unique_consumer_functions":len(function_fields),
                "fields":FIELD_LABELS,
            }
            (args.out/"match-player-field-scan-summary.json").write_text(
                json.dumps(summary,indent=2),encoding="utf-8")
            (args.out/"match-player-field-xrefs.json").write_text(
                json.dumps(hits,indent=2),encoding="utf-8")
            with (args.out/"match-player-field-xrefs.tsv").open("w",encoding="utf-8") as out:
                out.write("field_offset\tfield_label\taccess\tbase_register\tfrom_rva\tfunction_start_rva\tfunction_end_rva\tinstruction\tunwind_info_rva\n")
                for x in hits:
                    out.write("\t".join(x[k] for k in (
                        "field_offset","field_label","access","base_register","from_rva",
                        "function_start_rva","function_end_rva","instruction","unwind_info_rva"))+"\n")
            ranked=sorted(function_fields.items(),key=lambda x:(-len(x[1]),x[0]))
            with (args.out/"match-player-field-consumer-functions.tsv").open("w",encoding="utf-8") as out:
                out.write("function_start_rva\tfunction_end_rva\tfield_count\tfield_offsets\tfield_labels\n")
                ranges={a:(b,u) for a,b,u in runtime}
                for start,fields in ranked:
                    end,unwind=ranges[start]
                    out.write(f"0x{start:X}\t0x{end:X}\t{len(fields)}\t"+
                              ",".join(f"0x{x:X}" for x in sorted(fields))+"\t"+
                              ",".join(FIELD_LABELS[x] for x in sorted(fields))+"\n")
            with (args.out/"match-player-field-xrefs-ghidra.tsv").open("w",encoding="utf-8") as out:
                out.write("from_rva\tto_rva\treference_kind\ttarget_name\tinstruction_pattern\tcaller_function_rva\tcaller_function_end_rva\tunwind_info_rva\n")
                for x in hits:
                    label="MATCH_PLAYER_FIELD_"+x["field_offset"].replace("0x","")
                    out.write(
                        f'{x["from_rva"]}\t{x["field_offset"]}\t{x["access"]}_FIELD_ACCESS\t{label}\t'
                        f'{x["instruction"]}\t{x["function_start_rva"]}\t'
                        f'{x["function_end_rva"]}\t{x["unwind_info_rva"]}\n'
                    )
            print(json.dumps(summary,indent=2))
            if not hits:
                raise SystemExit("no MATCH_PLAYER/OOP field references found")
        finally:
            mm.close()

if __name__=="__main__":
    main()
