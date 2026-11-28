// Focused FM27 shot / ball-kick outcome analysis.
// Resolves exact PDATA functions and enclosing functions for interior/thunk targets,
// then exports target callers, callees, and bounded Ghidra decompilations.
import java.io.*;
import java.util.*;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.*;

public class TraceShotOutcomeMechanics extends GhidraScript {
    private static final long EXCEPTION_RVA=0x18176000L;
    private static final long EXCEPTION_SIZE=0x1A8710L;
    private static final long MAX_BODY=0x30000L;
    private static final int MAX_CALLERS=80;
    private static final int MAX_CALLEES=96;

    private final NavigableMap<Long,long[]> ranges=new TreeMap<>();
    private final LinkedHashMap<Long,String> targets=new LinkedHashMap<>();
    private final Map<Long,Function> functions=new LinkedHashMap<>();
    private final LinkedHashMap<Long,Function> callers=new LinkedHashMap<>();
    private final LinkedHashSet<Long> callees=new LinkedHashSet<>();

    {
        targets.put(0x4c01760L,"XG_SHOT_DATA_EVENT_RECORD_WRITER");
        targets.put(0x498d400L,"XG_SHOT_EVENT_VALUE_PROVIDER_UNRESOLVED");
        targets.put(0x4d1f0L,"XG_SHOT_EVENT_CONTEXT_BUILDER");
        targets.put(0x1691c0L,"XG_SHOT_EVENT_PAYLOAD_FINALIZER");
        targets.put(0x164680L,"SHOT_TARGET_REGION_CLASSIFIER");
        targets.put(0x166400L,"TEAM_STAT_QUEUE_WRITER");
        targets.put(0x42d2440L,"BALL_KICK_SAMPLE_EVENT_HANDLER");
        targets.put(0x3e4e0L,"BALL_KICK_SAMPLE_CREATOR_A");
        targets.put(0x19edd0L,"BALL_KICK_SAMPLE_CREATOR_B");
        targets.put(0x5dbd0L,"MATCH_BALL_KICK_SAMPLE_CREATOR_C");
        targets.put(0x42ddc80L,"SET_PIECE_ATTEMPT_EVENT");
        targets.put(0x28d6e30L,"SET_PIECE_OUTCOME_EVENT");
        targets.put(0x1b6490L,"XG_SHOT_DATA_SLOT_A");
        targets.put(0x28d6f60L,"XG_SHOT_DATA_SLOT_B");
        targets.put(0x28d6fb0L,"XG_SHOT_DATA_SLOT_C");
        targets.put(0x481a6a0L,"ADVANCED_SHOT_ZONE_SPATIAL_PROCESSOR");
        targets.put(0x47e44c0L,"DIRECTION_SPATIAL_CALCULATOR");
        targets.put(0x48a6e20L,"OPPONENT_PREDICTED_POSITION_HELPER");
        targets.put(0x47f1e70L,"PLAYER_TIME_POSITION_SAMPLE_HELPER");
        targets.put(0x47c5350L,"MATCH_STATE_MACHINE_DISPATCHER");
        targets.put(0x42d3910L,"MATCH_PLAYER_MOVEMENT_TICK_DRIVER");
    }

    private void loadRanges() throws Exception {
        Address base=currentProgram.getImageBase();
        Address table=base.add(EXCEPTION_RVA);
        for(long i=0;i<EXCEPTION_SIZE/12;i++) {
            Address row=table.add(i*12);
            long b=Integer.toUnsignedLong(currentProgram.getMemory().getInt(row));
            long e=Integer.toUnsignedLong(currentProgram.getMemory().getInt(row.add(4)));
            long u=Integer.toUnsignedLong(currentProgram.getMemory().getInt(row.add(8)));
            if(b<e && e<=currentProgram.getMaxAddress().subtract(base)+1)
                ranges.put(b,new long[]{e,u});
        }
    }

    private long[] rangeContaining(long rva) {
        Map.Entry<Long,long[]> e=ranges.floorEntry(rva);
        if(e!=null && rva<e.getValue()[0]) return new long[]{e.getKey(),e.getValue()[0],e.getValue()[1]};
        return null;
    }

    private Function ensureFunction(long start,String name,PrintWriter summary) throws Exception {
        Address entry=currentProgram.getImageBase().add(start);
        Function f=currentProgram.getFunctionManager().getFunctionAt(entry);
        if(f!=null && f.getBody().getNumAddresses()>1) return f;
        long[] rg=ranges.get(start);
        if(rg==null) {
            summary.println("NO_EXACT_PDATA_RANGE\t"+name+"\tRVA=0x"+Long.toHexString(start));
            return null;
        }
        MemoryBlock block=currentProgram.getMemory().getBlock(entry);
        if(block==null || !block.isExecute()) {
            summary.println("NOT_EXECUTABLE\t"+name+"\tRVA=0x"+Long.toHexString(start));
            return null;
        }
        Address end=currentProgram.getImageBase().add(rg[0]-1);
        AddressSet full=new AddressSet(entry,end);
        DisassembleCommand cmd=new DisassembleCommand(entry,full,true);
        cmd.applyTo(currentProgram,monitor);
        AddressSet body=new AddressSet();
        InstructionIterator it=currentProgram.getListing().getInstructions(full,true);
        while(it.hasNext()) {
            Instruction ins=it.next();
            body.add(ins.getMinAddress(),ins.getMaxAddress());
        }
        if(!body.contains(entry) || body.getNumAddresses()<2) {
            summary.println("DECODE_TOO_SMALL\t"+name+"\tRVA=0x"+Long.toHexString(start)+"\t"+cmd.getStatusMsg());
            return null;
        }
        Iterator<Function> overlaps=currentProgram.getFunctionManager().getFunctionsOverlapping(body);
        List<Function> remove=new ArrayList<>();
        while(overlaps.hasNext()) {
            Function old=overlaps.next();
            if(!old.getEntryPoint().equals(entry)) remove.add(old);
        }
        for(Function old:remove) currentProgram.getFunctionManager().removeFunction(old.getEntryPoint());
        if(f!=null) {
            try { f.setBody(body); }
            catch(Exception ex) {
                currentProgram.getFunctionManager().removeFunction(entry);
                f=null;
            }
        }
        if(f==null) {
            try { f=currentProgram.getFunctionManager().createFunction(name,entry,body,SourceType.ANALYSIS); }
            catch(Exception ex) { f=currentProgram.getFunctionManager().getFunctionAt(entry); }
        }
        return f;
    }

    private int timeout(Function f) {
        long n=f.getBody().getNumAddresses();
        return n>0x8000?90:(n>0x3000?60:(n>0x800?35:20));
    }

    private void decompile(Function f,DecompInterface d,PrintWriter out,String label) {
        long bytes=f.getBody().getNumAddresses();
        out.println("\n// ===== "+f.getEntryPoint()+" "+label+" BODY_BYTES="+bytes+" =====");
        if(bytes>MAX_BODY) { out.println("// SKIPPED_OVERSIZE"); return; }
        DecompileResults r=d.decompileFunction(f,timeout(f),monitor);
        if(r!=null && r.decompileCompleted() && r.getDecompiledFunction()!=null)
            out.println(r.getDecompiledFunction().getC());
        else out.println("// DECOMPILE_FAILED "+(r==null?"no result":r.getErrorMessage()));
    }

    private void collectFunction(Function f,PrintWriter refs) {
        long from=f.getEntryPoint().subtract(currentProgram.getImageBase());
        InstructionIterator it=currentProgram.getListing().getInstructions(f.getBody(),true);
        while(it.hasNext()) {
            Instruction ins=it.next();
            for(Reference ref:currentProgram.getReferenceManager().getReferencesFrom(ins.getAddress())) {
                if(!ref.getReferenceType().isCall()) continue;
                try {
                    long to=ref.getToAddress().subtract(currentProgram.getImageBase());
                    if(to>=0) {
                        callees.add(to);
                        refs.println("OUTGOING_CALL\tFROM=0x"+Long.toHexString(from)+
                            "\tSITE=0x"+Long.toHexString(ins.getAddress().subtract(currentProgram.getImageBase()))+
                            "\tTO=0x"+Long.toHexString(to));
                    }
                } catch(Exception ignored) {}
            }
        }
    }

    private void collectTargetIncoming(long targetRva,String label,PrintWriter refs) {
        Address target=currentProgram.getImageBase().add(targetRva);
        ReferenceIterator incoming=currentProgram.getReferenceManager().getReferencesTo(target);
        int count=0;
        while(incoming.hasNext() && count<MAX_CALLERS) {
            Reference ref=incoming.next();
            Function caller=currentProgram.getFunctionManager().getFunctionContaining(ref.getFromAddress());
            long from=ref.getFromAddress().subtract(currentProgram.getImageBase());
            refs.println("TARGET_INCOMING\tTARGET=0x"+Long.toHexString(targetRva)+
                "\tLABEL="+label+"\tSITE=0x"+Long.toHexString(from)+
                "\tKIND="+ref.getReferenceType()+
                "\tCALLER="+(caller==null?"<unknown>":caller.getEntryPoint()+" "+caller.getName()));
            if(caller!=null && !caller.getEntryPoint().equals(target))
                callers.put(caller.getEntryPoint().subtract(currentProgram.getImageBase()),caller);
            count++;
        }
    }

    @Override protected void run() throws Exception {
        String[] args=getScriptArgs();
        File out=new File(args.length>0?args[0]:"analysis/shot-outcome");
        out.mkdirs();
        try(PrintWriter summary=new PrintWriter(new File(out,"shot-outcome-summary.txt"),"UTF-8");
            PrintWriter refs=new PrintWriter(new File(out,"shot-outcome-xrefs.txt"),"UTF-8");
            PrintWriter dec=new PrintWriter(new File(out,"shot-outcome-decompilations.txt"),"UTF-8");
            PrintWriter asm=new PrintWriter(new File(out,"shot-outcome-address-resolution.txt"),"UTF-8")) {
            loadRanges();
            summary.println("RUNTIME_FUNCTION_RANGES="+ranges.size());
            DecompInterface d=new DecompInterface();
            d.openProgram(currentProgram);
            Map<Long,Function> uniqueFunctions=new LinkedHashMap<>();

            for(Map.Entry<Long,String> e:targets.entrySet()) {
                if(monitor.isCancelled()) break;
                long rva=e.getKey();
                String label=e.getValue();
                long[] containing=rangeContaining(rva);
                Function f=null;
                if(containing!=null) {
                    long start=containing[0];
                    String resolvedLabel=(start==rva?label:label+"_ENCLOSING_FUNCTION");
                    f=ensureFunction(start,resolvedLabel,summary);
                    asm.println("TARGET\tRVA=0x"+Long.toHexString(rva)+
                        "\tLABEL="+label+
                        "\tRANGE_START=0x"+Long.toHexString(start)+
                        "\tRANGE_END=0x"+Long.toHexString(containing[1])+
                        "\tUNWIND=0x"+Long.toHexString(containing[2])+
                        "\tEXACT_ENTRY="+(start==rva));
                    if(start!=rva)
                        summary.println("INTERIOR_TARGET\t"+label+"\tTARGET=0x"+
                            Long.toHexString(rva)+"\tENCLOSING_FUNCTION=0x"+
                            Long.toHexString(start)+"\tEND=0x"+Long.toHexString(containing[1]));
                    if(f!=null) {
                        uniqueFunctions.putIfAbsent(start,f);
                        collectFunction(f,refs);
                    }
                } else {
                    asm.println("NO_PDATA_CONTAINING_RANGE\tRVA=0x"+
                        Long.toHexString(rva)+"\tLABEL="+label);
                    summary.println("NO_PDATA_CONTAINING_RANGE\t"+label+"\tRVA=0x"+Long.toHexString(rva));
                }
                collectTargetIncoming(rva,label,refs);
            }

            int seedCount=0;
            for(Map.Entry<Long,Function> e:uniqueFunctions.entrySet()) {
                if(monitor.isCancelled()) break;
                decompile(e.getValue(),d,dec,"SHOT_SEED_OR_ENCLOSING_"+Long.toHexString(e.getKey()));
                seedCount++;
            }

            int callerCount=0;
            List<Map.Entry<Long,Function>> callerSnapshot=new ArrayList<>(callers.entrySet());
            for(Map.Entry<Long,Function> e:callerSnapshot) {
                if(monitor.isCancelled() || callerCount>=MAX_CALLERS) break;
                decompile(e.getValue(),d,dec,"SHOT_TARGET_CALLER_"+Long.toHexString(e.getKey()));
                callerCount++;
            }

            int calleeCount=0;
            for(Long rva:new ArrayList<Long>(callees)) {
                if(monitor.isCancelled() || calleeCount>=MAX_CALLEES) break;
                long[] range=rangeContaining(rva);
                if(range==null || range[0]!=rva || uniqueFunctions.containsKey(rva)) continue;
                Function f=ensureFunction(rva,"SHOT_DIRECT_CALLEE_"+Long.toHexString(rva),summary);
                if(f==null) continue;
                decompile(f,d,dec,"SHOT_DIRECT_CALLEE_"+Long.toHexString(rva));
                calleeCount++;
            }
            summary.println("UNIQUE_SEED_OR_ENCLOSING_FUNCTIONS="+seedCount);
            summary.println("UNIQUE_TARGET_CALLERS="+callers.size());
            summary.println("CALLERS_DECOMPILED="+callerCount);
            summary.println("DIRECT_CALLEES_DECOMPILED="+calleeCount);
            decompDispose:
            d.dispose();
        }
    }
}
