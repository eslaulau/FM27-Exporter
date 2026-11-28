// Focused handoff analysis for the final candidate -> player movement-state path.
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

public class TraceMovementHandoff extends GhidraScript {
    private static final long EXCEPTION_RVA=0x18176000L;
    private static final long EXCEPTION_SIZE=0x1A8710L;
    private static final int MAX_CALLERS_PER_SEED=60;
    private final NavigableMap<Long,long[]> ranges=new TreeMap<>();
    private final Map<Long,Function> functions=new LinkedHashMap<>();
    private final LinkedHashMap<Long,String> seeds=new LinkedHashMap<>();
    private final Map<Long,Function> callers=new LinkedHashMap<>();
    private final Map<Long,Set<Long>> outgoing=new LinkedHashMap<>();

    private void loadRanges() throws Exception {
        Address base=currentProgram.getImageBase(), table=base.add(EXCEPTION_RVA);
        for(long i=0;i<EXCEPTION_SIZE/12;i++) {
            Address row=table.add(i*12);
            long b=Integer.toUnsignedLong(currentProgram.getMemory().getInt(row));
            long e=Integer.toUnsignedLong(currentProgram.getMemory().getInt(row.add(4)));
            long u=Integer.toUnsignedLong(currentProgram.getMemory().getInt(row.add(8)));
            if(b<e && e<=currentProgram.getMaxAddress().subtract(base)+1) ranges.put(b,new long[]{e,u});
        }
    }
    private Function ensure(long rva,String name,PrintWriter summary) throws Exception {
        Address entry=currentProgram.getImageBase().add(rva);
        Function f=currentProgram.getFunctionManager().getFunctionAt(entry);
        if(f!=null && f.getBody().getNumAddresses()>1) { functions.put(rva,f); return f; }
        Function containing=currentProgram.getFunctionManager().getFunctionContaining(entry);
        if(f==null && containing!=null) { functions.put(rva,containing); return containing; }
        long[] rg=ranges.get(rva);
        if(rg==null) { summary.println("NO_PDATA_RANGE\t"+name+"\tRVA=0x"+Long.toHexString(rva)); return null; }
        MemoryBlock block=currentProgram.getMemory().getBlock(entry);
        if(block==null || !block.isExecute()) return null;
        Address end=currentProgram.getImageBase().add(rg[0]-1);
        AddressSet full=new AddressSet(entry,end);
        DisassembleCommand cmd=new DisassembleCommand(entry,full,true); cmd.applyTo(currentProgram,monitor);
        AddressSet body=new AddressSet();
        InstructionIterator it=currentProgram.getListing().getInstructions(full,true);
        while(it.hasNext()) { Instruction ins=it.next(); body.add(ins.getMinAddress(),ins.getMaxAddress()); }
        if(!body.contains(entry)||body.getNumAddresses()<2) return null;
        Iterator<Function> overlaps=currentProgram.getFunctionManager().getFunctionsOverlapping(body);
        List<Function> remove=new ArrayList<>();
        while(overlaps.hasNext()) { Function old=overlaps.next(); if(!old.getEntryPoint().equals(entry)) remove.add(old); }
        for(Function old:remove) currentProgram.getFunctionManager().removeFunction(old.getEntryPoint());
        if(f!=null) {
            try { f.setBody(body); } catch(Exception ex) { currentProgram.getFunctionManager().removeFunction(entry); f=null; }
        }
        if(f==null) {
            try { f=currentProgram.getFunctionManager().createFunction(name,entry,body,SourceType.ANALYSIS); }
            catch(Exception ex) { f=currentProgram.getFunctionManager().getFunctionAt(entry); }
        }
        if(f!=null) functions.put(rva,f);
        return f;
    }
    private boolean isRbpFrame(long rva) {
        long[] rg=ranges.get(rva);
        if(rg!=null && rg[1]!=0) {
            try {
                int frame=currentProgram.getMemory().getByte(currentProgram.getImageBase().add(rg[1]).add(3)) & 0x0f;
                if(frame==5) return true;
            } catch(Exception ignored) {}
        }
        return false;
    }
    private void addContainingSeed(long rva,String label,PrintWriter summary) {
        Map.Entry<Long,long[]> e=ranges.floorEntry(rva);
        if(e!=null && rva<e.getValue()[0]) {
            seeds.putIfAbsent(e.getKey(),label+"_CONTAINING_"+Long.toHexString(rva));
            summary.println("CONTAINED_SEED\\tTARGET=0x"+Long.toHexString(rva)+
                "\\tFUNCTION=0x"+Long.toHexString(e.getKey())+
                "\\tEND=0x"+Long.toHexString(e.getValue()[0]));
        } else {
            summary.println("NO_CONTAINING_PDATA\\tTARGET=0x"+Long.toHexString(rva));
        }
    }
    private void loadMovementRecordConsumers(File tsv,PrintWriter summary) throws Exception {
        if(!tsv.isFile()) { summary.println("MOVEMENT_FIELD_TSV_MISSING="+tsv); return; }
        Map<Long,Map<Long,Integer>> counts=new HashMap<>();
        Map<Long,Set<String>> bases=new HashMap<>();
        try(BufferedReader br=new BufferedReader(new FileReader(tsv))) {
            String line; boolean header=true;
            while((line=br.readLine())!=null) {
                if(header) { header=false; continue; }
                String[] c=line.split("\\t",-1);
                if(c.length<9) continue;
                long off,start;
                try { off=Long.parseLong(c[0].replace("0x",""),16); start=Long.parseLong(c[5].replace("0x",""),16); }
                catch(Exception ex) { continue; }
                if(c[3].equalsIgnoreCase("rsp")) continue;
                if(c[3].equalsIgnoreCase("rbp") && isRbpFrame(start)) continue;
                int weight=(off==0x1C64?8:(off==0x1C44?6:(off==0x1BB0?6:
                    ((off==0x1C34 || off==0x1C3C || off==0x1C60)?4:2))));
                if(c[2].contains("R")) weight+=2;
                if(c[2].contains("W")) weight+=2;
                Map<Long,Integer> fields=counts.computeIfAbsent(start,k->new HashMap<>());
                fields.put(off,fields.getOrDefault(off,0)+weight);
                bases.computeIfAbsent(start,k->new LinkedHashSet<>()).add(c[3]);
            }
        }
        List<Long> ranked=new ArrayList<>();
        for(Map.Entry<Long,Map<Long,Integer>> e:counts.entrySet()) {
            Set<Long> fields=e.getValue().keySet();
            if(fields.size()>=2 || fields.contains(0x1C64L)) ranked.add(e.getKey());
        }
        ranked.sort((a,b)->{
            int wa=counts.get(a).values().stream().mapToInt(Integer::intValue).sum();
            int wb=counts.get(b).values().stream().mapToInt(Integer::intValue).sum();
            return Integer.compare(wb,wa);
        });
        int added=0;
        for(long rva:ranked) {
            if(added>=32) break;
            if(seeds.containsKey(rva)) continue;
            String label="MOVEMENT_RECORD_CONSUMER_"+Long.toHexString(rva);
            seeds.put(rva,label);
            summary.println("MOVEMENT_RECORD_DYNAMIC_SEED\\t"+label+"\\tRVA=0x"+
                Long.toHexString(rva)+"\\tFIELDS="+counts.get(rva).keySet()+
                "\\tBASES="+bases.get(rva));
            added++;
        }
        summary.println("MOVEMENT_RECORD_DYNAMIC_SEEDS_ADDED="+added+
            " CANDIDATE_FUNCTIONS="+ranked.size());
    }

    private void collect(Function f,PrintWriter refs,PrintWriter summary) {
        long start=f.getEntryPoint().subtract(currentProgram.getImageBase());
        Set<Long> calls=new LinkedHashSet<>();
        InstructionIterator it=currentProgram.getListing().getInstructions(f.getBody(),true);
        while(it.hasNext()) {
            Instruction ins=it.next();
            for(Reference ref:currentProgram.getReferenceManager().getReferencesFrom(ins.getAddress())) {
                if(!ref.getReferenceType().isCall()) continue;
                try {
                    long rva=ref.getToAddress().subtract(currentProgram.getImageBase());
                    if(rva>=0) {
                        calls.add(rva);
                        refs.println("CALL\tFROM=0x"+Long.toHexString(ins.getAddress().subtract(currentProgram.getImageBase()))+
                            "\tTO=0x"+Long.toHexString(rva));
                    }
                } catch(Exception ignored) {}
            }
        }
        outgoing.put(start,calls);
        ReferenceIterator incoming=currentProgram.getReferenceManager().getReferencesTo(f.getEntryPoint());
        int n=0;
        while(incoming.hasNext() && n<MAX_CALLERS_PER_SEED) {
            Reference ref=incoming.next(); if(!ref.getReferenceType().isCall()) continue;
            Function parent=currentProgram.getFunctionManager().getFunctionContaining(ref.getFromAddress());
            if(parent==null || parent.getEntryPoint().equals(f.getEntryPoint())) continue;
            long rva=parent.getEntryPoint().subtract(currentProgram.getImageBase());
            callers.put(rva,parent);
            refs.println("INCOMING\tTARGET=0x"+Long.toHexString(start)+
                "\tSITE=0x"+Long.toHexString(ref.getFromAddress().subtract(currentProgram.getImageBase()))+
                "\tCALLER=0x"+Long.toHexString(rva));
            n++;
        }
        summary.println("XREF_COUNTS\tRVA=0x"+Long.toHexString(start)+
            "\tCALLEES="+calls.size()+"\tCALLERS="+n);
    }
    private void dec(Function f,DecompInterface d,PrintWriter out,String label) {
        long bytes=f.getBody().getNumAddresses();
        out.println("\n// ===== "+f.getEntryPoint()+" "+label+" BODY_BYTES="+bytes+" =====");
        int timeout=bytes>0x7000?90:(bytes>0x2500?60:30);
        DecompileResults result=d.decompileFunction(f,timeout,monitor);
        if(result!=null && result.decompileCompleted() && result.getDecompiledFunction()!=null)
            out.println(result.getDecompiledFunction().getC());
        else out.println("// DECOMPILE_FAILED "+(result==null?"no result":result.getErrorMessage()));
    }
    @Override protected void run() throws Exception {
        String[] args=getScriptArgs();
        File out=new File(args.length>0?args[0]:"analysis/movement-handoff"); out.mkdirs();
        try(PrintWriter summary=new PrintWriter(new File(out,"movement-handoff-summary.txt"),"UTF-8");
            PrintWriter refs=new PrintWriter(new File(out,"movement-handoff-xrefs.txt"),"UTF-8");
            PrintWriter dec=new PrintWriter(new File(out,"movement-handoff-decompilations.txt"),"UTF-8")) {
            loadRanges();
            summary.println("RUNTIME_FUNCTION_RANGES="+ranges.size());
            seeds.put(0x61660L,"CANDIDATE_TO_PLAYER_STATE_HANDOFF");
            seeds.put(0x48ACFD0L,"CANDIDATE_ACCEPTANCE_OUTPUT_DRIVER");
            seeds.put(0x48ADC70L,"CANDIDATE_ACCEPTANCE_RETRY_WRAPPER");
            seeds.put(0x4936080L,"MULTI_SAMPLE_CANDIDATE_RANKER");
            seeds.put(0x644B0L,"PLAYER_CANDIDATE_ENTITY_RESOLVER");
            addContainingSeed(0x7F2120L,"CANDIDATE_HANDOFF_POSTPROCESSOR_A",summary);
            addContainingSeed(0x707AA0L,"CANDIDATE_HANDOFF_VECTOR_POSTPROCESSOR_B",summary);
            File movementFields=new File(args.length>1?args[1]:"analysis/movement-record/field-xrefs/match-player-field-xrefs.tsv");
            loadMovementRecordConsumers(movementFields,summary);
            DecompInterface d=new DecompInterface(); d.openProgram(currentProgram);

            for(Map.Entry<Long,String> e:seeds.entrySet()) {
                if(monitor.isCancelled()) break;
                Function f=ensure(e.getKey(),e.getValue(),summary);
                if(f==null) continue;
                long[] rg=ranges.get(e.getKey());
                summary.println("SEED\t"+e.getValue()+"\tRVA=0x"+Long.toHexString(e.getKey())+
                    "\tBYTES="+f.getBody().getNumAddresses()+"\tEND=0x"+(rg==null?0:rg[0]));
                collect(f,refs,summary);
                dec(f,d,dec,e.getValue());
            }
            summary.println("UNIQUE_SEED_CALLERS="+callers.size());
            for(Map.Entry<Long,Function> e:callers.entrySet()) {
                if(monitor.isCancelled()) break;
                Function f=e.getValue();
                summary.println("CALLER\tRVA=0x"+Long.toHexString(e.getKey())+
                    "\tBYTES="+f.getBody().getNumAddresses()+"\tNAME="+f.getName());
                collect(f,refs,summary);
                dec(f,d,dec,"HANDOFF_CALLER_"+Long.toHexString(e.getKey()));
            }
            d.dispose();
        }
    }
}
