#!/usr/bin/env python3
"""Find all native call/jump sites targeting selected FM27 engine decision functions."""
from __future__ import annotations
import argparse, bisect, json, mmap, struct, re
from collections import defaultdict
from pathlib import Path

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
        raise ValueError("expected PE32+")
    image_base=struct.unpack_from("<Q",mm,opt+24)[0]
    image_size=struct.unpack_from("<I",mm,opt+56)[0]
    headers_size=struct.unpack_from("<I",mm,opt+60)[0]
    dirs=opt+112
    ex_rva,ex_size=struct.unpack_from("<II",mm,dirs+3*8)
    sections=[]
    sh=opt+opt_size
    for i in range(nsects):
        off=sh+i*40
        name=mm[off:off+8].split(b"\0",1)[0].decode("ascii","replace")
        vs,va,rs,rp=struct.unpack_from("<IIII",mm,off+8)
        flags=struct.unpack_from("<I",mm,off+36)[0]
        sections.append({
            "name":name,"va":va,"virtual_size":vs,"raw_size":rs,
            "raw_ptr":rp,"executable":bool(flags&0x20000000)
        })
    return image_base,image_size,headers_size,ex_rva,ex_size,sections

def rva_to_raw(rva,headers_size,sections):
    if rva<headers_size:
        return rva
    for s in sections:
        if s["va"]<=rva<s["va"]+s["raw_size"]:
            return s["raw_ptr"]+(rva-s["va"])
    return None

def is_exec(rva,sections):
    return any(s["executable"] and s["va"]<=rva<s["va"]+max(s["virtual_size"],s["raw_size"])
               for s in sections)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--binary",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--target",action="append",required=True,help="RVA:LABEL, e.g. 0xA8F70:PI_AGGREGATOR")
    ap.add_argument("--max-function-size",type=lambda x:int(x,0),default=0x30000)
    args=ap.parse_args()
    targets={}
    for value in args.target:
        raw,label=value.split(":",1)
        targets[int(raw,0)]=label

    try:
        from capstone import Cs,CS_ARCH_X86,CS_MODE_64,CS_OP_IMM,CS_GRP_CALL,CS_GRP_JUMP
    except ImportError as exc:
        raise SystemExit("capstone is required: pip install capstone==5.0.6") from exc

    args.out.mkdir(parents=True,exist_ok=True)
    with args.binary.open("rb") as f:
        mm=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
        try:
            image_base,image_size,headers_size,ex_rva,ex_size,sections=parse_pe(mm)
            ex_off=rva_to_raw(ex_rva,headers_size,sections)
            if not ex_rva or not ex_size or ex_off is None:
                raise SystemExit("PE Exception Directory unavailable")
            runtime=[]
            for off in range(ex_off,min(ex_off+ex_size,len(mm))-11,12):
                begin,end,unwind=struct.unpack_from("<III",mm,off)
                if begin<end<=image_size and unwind<image_size and is_exec(begin,sections):
                    runtime.append((begin,end,unwind))
            runtime.sort()
            starts=[x[0] for x in runtime]
            runtime_by_start={a:(b,u) for a,b,u in runtime}

            # Fast raw prefilter: only x64 near call/jump and long Jcc opcodes.
            candidate_by_target=defaultdict(set)
            raw_hits=[]
            for sec in sections:
                if not sec["executable"] or sec["raw_size"]<6:
                    continue
                lo=sec["raw_ptr"]
                hi=min(lo+sec["raw_size"],len(mm))
                blob=mm[lo:hi]
                def record(pos, size, disp, kind):
                    site_rva=sec["va"]+pos
                    target_rva=site_rva+size+disp
                    if target_rva not in targets:
                        return
                    idx=bisect.bisect_right(starts,site_rva)-1
                    if idx<0:
                        return
                    begin,finish,unwind=runtime[idx]
                    if not begin<=site_rva<finish or finish-begin>args.max_function_size:
                        return
                    candidate_by_target[target_rva].add(begin)
                    raw_hits.append((site_rva,target_rva,kind,begin,finish,unwind))

                # C-level byte searches are substantially faster than a Python
                # per-byte loop over the 300+ MB executable image.
                for opcode,kind in ((b"\xE8","CALL_REL32"),(b"\xE9","JMP_REL32")):
                    pos=blob.find(opcode)
                    while pos!=-1:
                        if pos+5<=len(blob):
                            disp=struct.unpack_from("<i",blob,pos+1)[0]
                            record(pos,5,disp,kind)
                        pos=blob.find(opcode,pos+1)

                for match in re.finditer(rb"\x0F[\x80-\x8F]",blob):
                    pos=match.start()
                    if pos+6<=len(blob):
                        disp=struct.unpack_from("<i",blob,pos+2)[0]
                        record(pos,6,disp,"JCC_REL32")

            # Decode only candidate functions and confirm target operands with Capstone.
            md=Cs(CS_ARCH_X86,CS_MODE_64)
            md.detail=True
            confirmed=[]
            decode_functions=0
            for target_rva,funcs in candidate_by_target.items():
                for begin in sorted(funcs):
                    end,unwind=runtime_by_start[begin]
                    size=end-begin
                    raw=rva_to_raw(begin,headers_size,sections)
                    if raw is None or raw+size>len(mm):
                        continue
                    decode_functions+=1
                    code=mm[raw:raw+size]
                    for ins in md.disasm(code,image_base+begin):
                        if not (ins.group(CS_GRP_CALL) or ins.group(CS_GRP_JUMP)):
                            continue
                        dests=[]
                        for op in ins.operands:
                            if op.type==CS_OP_IMM:
                                dests.append(op.imm-image_base)
                        if target_rva not in dests:
                            continue
                        confirmed.append({
                            "from_rva":f"0x{ins.address-image_base:X}",
                            "to_rva":f"0x{target_rva:X}",
                            "reference_kind":ins.mnemonic.upper(),
                            "target_name":targets[target_rva],
                            "instruction_pattern":ins.mnemonic+" "+ins.op_str,
                            "caller_function_rva":f"0x{begin:X}",
                            "caller_function_end_rva":f"0x{end:X}",
                            "unwind_info_rva":f"0x{unwind:X}",
                        })

            # Scan static/data sections for absolute VA or module-relative function pointers.
            data_pointer_hits=[]
            for sec in sections:
                if sec["executable"] or sec["raw_size"]<8:
                    continue
                lo=sec["raw_ptr"]
                hi=min(lo+sec["raw_size"],len(mm))
                for target_rva,label in targets.items():
                    for encoded,kind in ((struct.pack("<Q",image_base+target_rva),"ABSOLUTE_VA"),
                                         (struct.pack("<I",target_rva),"MODULE_RVA32")):
                        pos=mm.find(encoded,lo,hi)
                        while pos!=-1:
                            data_pointer_hits.append({
                                "section":sec["name"],
                                "file_offset":f"0x{pos:X}",
                                "section_rva":f"0x{sec['va']+pos-lo:X}",
                                "target_rva":f"0x{target_rva:X}",
                                "target_name":label,
                                "encoding":kind
                            })
                            pos=mm.find(encoded,pos+1,hi)

            confirmed.sort(key=lambda x:(int(x["to_rva"],16),int(x["caller_function_rva"],16),int(x["from_rva"],16)))
            (args.out/"native-target-call-xrefs.json").write_text(
                json.dumps({
                    "targets":{f"0x{k:X}":v for k,v in targets.items()},
                    "runtime_function_count":len(runtime),
                    "raw_candidate_function_count":sum(len(v) for v in candidate_by_target.values()),
                    "candidate_functions_decoded":decode_functions,
                    "confirmed_call_jump_sites":len(confirmed),
                    "static_pointer_hits":len(data_pointer_hits),
                    "call_xrefs":confirmed,
                    "static_pointer_xrefs":data_pointer_hits
                },indent=2),encoding="utf-8")
            with (args.out/"native-target-call-xrefs.tsv").open("w",encoding="utf-8") as out:
                out.write("from_rva\tto_rva\treference_kind\ttarget_name\tinstruction_pattern\tcaller_function_rva\tcaller_function_end_rva\tunwind_info_rva\n")
                for x in confirmed:
                    out.write("\t".join(x[k] for k in (
                        "from_rva","to_rva","reference_kind","target_name","instruction_pattern",
                        "caller_function_rva","caller_function_end_rva","unwind_info_rva"))+"\n")
            with (args.out/"native-target-static-pointer-xrefs.tsv").open("w",encoding="utf-8") as out:
                out.write("section\tfile_offset\tsection_rva\ttarget_rva\ttarget_name\tencoding\n")
                for x in data_pointer_hits:
                    out.write("\t".join(x[k] for k in (
                        "section","file_offset","section_rva","target_rva","target_name","encoding"))+"\n")
            summary={
                "runtime_function_count":len(runtime),
                "target_count":len(targets),
                "raw_candidate_functions":sum(len(v) for v in candidate_by_target.values()),
                "candidate_functions_decoded":decode_functions,
                "confirmed_call_jump_sites":len(confirmed),
                "static_pointer_hits":len(data_pointer_hits),
                "targets":{f"0x{k:X}":v for k,v in targets.items()}
            }
            (args.out/"native-target-call-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
            print(json.dumps(summary,indent=2))
            if not confirmed and not data_pointer_hits:
                raise SystemExit("no direct or static pointer references found")
        finally:
            mm.close()

if __name__=="__main__":
    main()
