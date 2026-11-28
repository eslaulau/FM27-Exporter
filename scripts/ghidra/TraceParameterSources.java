// Focused parameter-source pass: only MATCH_PLAYER parameter-vector and TEAM coefficient writers.
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

public class TraceParameterSources extends GhidraScript {
    private static final long EXCEPTION_RVA=0x18176000L;
    private static final long EXCEPTION_SIZE=0x1A8710L;
    private static final int MAX_DYNAMIC_PER_GROUP=9;
    private static final int MAX_CALLEES=24;
    private static final int MAX_CALLERS=24;
    private final Map<Long,long[]> ranges=new TreeMap<>();
    private final Map<Long,Function> functions=new LinkedHashMap<>();
    private final LinkedHashMap<Long,String> seeds=new LinkedHashMap<>();
    private final Set<Long> callees=new LinkedHashSet<>();
    private final Map<Long,Function> callers=new LinkedHashMap<>();

    private long hex(String s) { return Long.parseLong(s.trim().replace("0x","").replace("0X",""),16); }
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
        Function existing=currentProgram.getFunctionManager().getFunctionAt(entry);
        if(existing!=null && existing.getBody().getNumAddresses()>1) { functions.put(rva,existing); return existing; }
        Function containing=currentProgram.getFunctionManager().getFunctionContaining(entry);
        if(existing==null && containing!=null) { functions.put(rva,containing); return containing; }
        long[] rg=ranges.get(rva);
        if(rg==null) { summary.println("NO_PDATA_RANGE\t"+name+"\t0x"+Long.toHexString(rva)); return null; }
        MemoryBlock block=currentProgram.getMemory().getBlock(entry);
        if(block==null || !block.isExecute()) return null;
        Address end=currentProgram.getImageBase().add(rg[0]-1);
        AddressSet full=new AddressSet(entry,end);
        DisassembleCommand cmd=new DisassembleCommand(entry,full,true); cmd.applyTo(currentProgram,monitor);
        AddressSet body=new AddressSet();
        InstructionIterator it=currentProgram.getListing().getInstructions(full,true);
        while(it.hasNext()) { Instruction ins=it.next(); body.add(ins.getMinAddress(),ins.getMaxAddress()); }
        if(!body.contains(entry) || body.getNumAddresses()<2) return null;
        Iterator<Function> overlaps=currentProgram.getFunctionManager().getFunctionsOverlapping(body);
        List<Function> remove=new ArrayList<>();
        while(overlaps.hasNext()) { Function f=overlaps.next(); if(!f.getEntryPoint().equals(entry)) remove.add(f); }
        for(Function f:remove) currentProgram.getFunctionManager().removeFunction(f.getEntryPoint());
        Function f=existing;
        if(f!=null) {
            try { f.setBody(body); }
            catch(Exception ex) { currentProgram.getFunctionManager().removeFunction(entry); f=null; }
        }
        if(f==null) {
            try { f=currentProgram.getFunctionManager().createFunction(name,entry,body,SourceType.ANALYSIS); }
            catch(Exception ex) { f=currentProgram.getFunctionManager().getFunctionAt(entry); }
        }
        if(f!=null) functions.put(rva,f);
        return f;
    }
    private void loadDynamicSeeds(File outDir,PrintWriter summary) throws Exception {
        File tsv=new File(new File(outDir,"direction-generator-fields"),"match-player-field-xrefs.tsv");
        if(!tsv.isFile()) { summary.println("MISSING_FIELD_TSV="+tsv); return; }
        Map<Long,Map<String,Integer>> vector=new HashMap<>(),coeff=new HashMap<>();
        try(BufferedReader br=new BufferedReader(new FileReader(tsv))) {
            String line; boolean header=true;
            while((line=br.readLine())!=null) {
                if(header) { header=false; continue; }
                String[] c=line.split("\\t",-1); if(c.length<8) continue;
                long off,start; try { off=hex(c[0]); start=hex(c[5]); } catch(Exception ex) { continue; }
                if(!c[2].contains("W")) continue;
                boolean isVector=off>=0x480 && off<=0x4C4;
                boolean isCoeff=off>=0x149E4 && off<=0x14A00 && ((off-0x149E4)%4==0);
                if(!isVector && !isCoeff) continue;
                Map<Long,Map<String,Integer>> group=isVector?vector:coeff;
                Map<String,Integer> fields=group.computeIfAbsent(start,k->new HashMap<>());
                fields.put(c[1],fields.getOrDefault(c[1],0)+1);
            }
        }
        addGroup(vector,"PARAM_VECTOR_WRITER_",summary);
        addGroup(coeff,"TEAM_COEFFICIENT_WRITER_",summary);
    }
    private void addGroup(Map<Long,Map<String,Integer>> group,String prefix,PrintWriter summary) {
        List<Long> starts=new ArrayList<>(group.keySet());
        starts.sort((a,b)->Integer.compare(total(group.get(b)),total(group.get(a))));
        int added=0;
        for(long rva:starts) {
            if(added>=MAX_DYNAMIC_PER_GROUP) break;
            if(seeds.containsKey(rva)) continue;
            String name=prefix+Long.toHexString(rva);
            seeds.put(rva,name);
            summary.println("DYNAMIC_SEED\t"+name+"\tRVA=0x"+Long.toHexString(rva)+
                "\tWRITE_REFS="+total(group.get(rva))+"\tFIELDS="+String.join(",",group.get(rva).keySet()));
            added++;
        }
        summary.println(prefix+"COUNT="+added);
    }
    private int total(Map<String,Integer> m) { return m.values().stream().mapToInt(Integer::intValue).sum(); }
    private void collect(Function f,PrintWriter xrefs) {
        InstructionIterator it=currentProgram.getListing().getInstructions(f.getBody(),true);
        while(it.hasNext()) {
            Instruction ins=it.next();
            for(Reference ref:currentProgram.getReferenceManager().getReferencesFrom(ins.getAddress())) {
                if(!ref.getReferenceType().isCall()) continue;
                long target; try { target=ref.getToAddress().subtract(currentProgram.getImageBase()); } catch(Exception ex) { continue; }
                callees.add(target);
                xrefs.println("CALL\tFROM=0x"+Long.toHexString(ins.getAddress().subtract(currentProgram.getImageBase()))+
                    "\tTO=0x"+Long.toHexString(target));
            }
        }
        ReferenceIterator in=currentProgram.getReferenceManager().getReferencesTo(f.getEntryPoint());
        int n=0;
        while(in.hasNext() && n<MAX_CALLERS) {
            Reference ref=in.next(); if(!ref.getReferenceType().isCall()) continue;
            Function caller=currentProgram.getFunctionManager().getFunctionContaining(ref.getFromAddress());
            if(caller==null) continue;
            long rva=caller.getEntryPoint().subtract(currentProgram.getImageBase());
            callers.put(rva,caller); n++;
            xrefs.println("INCOMING\tTO=0x"+Long.toHexString(f.getEntryPoint().subtract(currentProgram.getImageBase()))+
                "\tCALLER=0x"+Long.toHexString(rva));
        }
    }
    private void decompile(Function f,DecompInterface d,PrintWriter out,String label) {
        out.println("\n// ===== "+f.getEntryPoint()+" "+label+" BYTES="+f.getBody().getNumAddresses()+" =====");
        int timeout=f.getBody().getNumAddresses()>0x7000?45:30;
        DecompileResults r=d.decompileFunction(f,timeout,monitor);
        if(r!=null && r.decompileCompleted() && r.getDecompiledFunction()!=null) out.println(r.getDecompiledFunction().getC());
        else out.println("// DECOMPILE_FAILED "+(r==null?"null":r.getErrorMessage()));
    }
    @Override protected void run() throws Exception {
        String[] args=getScriptArgs();
        File outDir=new File(args.length>0?args[0]:"analysis/parameter-sources"); outDir.mkdirs();
        try(PrintWriter summary=new PrintWriter(new File(outDir,"parameter-source-summary.txt"),"UTF-8");
            PrintWriter xrefs=new PrintWriter(new File(outDir,"parameter-source-xrefs.txt"),"UTF-8");
            PrintWriter dec=new PrintWriter(new File(outDir,"parameter-source-decompilations.txt"),"UTF-8")) {
            loadRanges(); summary.println("RUNTIME_FUNCTION_RANGES="+ranges.size());
            seeds.put(0xF8050L,"MATCH_PLAYER_INSTANCE_INITIALIZATION_CANDIDATE");
            seeds.put(0x185090L,"MATCH_PLAYER_PARAMETER_REFRESH_BULK_COPY");
            seeds.put(0x3C720L,"MATCH_PLAYER_PARAMETER_VECTOR_INITIALIZER");
            seeds.put(0x452FF10L,"MATCH_PLAYER_PARAMETER_VECTOR_BULK_INITIALIZER");
            seeds.put(0x103A10L,"MATCH_PLAYER_TACTICAL_SNAPSHOT_COPIER");
            seeds.put(0x72B20L,"MATCH_PLAYER_SLOT_AND_TACTIC_REFRESH");
            seeds.put(0x2B05590L,"MATCH_PLAYER_TACTICAL_STATE_CLONER");
            seeds.put(0x48334D0L,"MATCH_PLAYER_PARAMETER_GATE_REFRESH");
            loadDynamicSeeds(outDir,summary);
            DecompInterface d=new DecompInterface(); d.openProgram(currentProgram);
            for(Map.Entry<Long,String> e:seeds.entrySet()) {
                if(monitor.isCancelled()) break;
                Function f=ensure(e.getKey(),e.getValue(),summary); if(f==null) continue;
                long[] rg=ranges.get(e.getKey());
                summary.println("SEED\t"+e.getValue()+"\tRVA=0x"+Long.toHexString(e.getKey())+
                    "\tBYTES="+f.getBody().getNumAddresses()+"\tEND=0x"+(rg==null?0:rg[0]));
                collect(f,xrefs); decompile(f,d,dec,e.getValue());
            }
            int n=0;
            for(long rva:callees) {
                if(n>=MAX_CALLEES || monitor.isCancelled()) break;
                if(functions.containsKey(rva)) continue;
                Function f=ensure(rva,"PARAM_SOURCE_CALLEE_"+Long.toHexString(rva),summary); if(f==null) continue;
                summary.println("CALLEE\t0x"+Long.toHexString(rva)+"\tBYTES="+f.getBody().getNumAddresses());
                decompile(f,d,dec,f.getName()); n++;
            }
            n=0;
            for(Map.Entry<Long,Function> e:callers.entrySet()) {
                if(n>=MAX_CALLERS || monitor.isCancelled()) break;
                Function f=e.getValue();
                summary.println("CALLER\t0x"+Long.toHexString(e.getKey())+"\tBYTES="+f.getBody().getNumAddresses());
                decompile(f,d,dec,f.getName()); n++;
            }
            summary.println("SEEDS="+seeds.size()+"\nCALLEES="+n+"\nCALLERS="+callers.size());
            d.dispose();
        }
    }
}
