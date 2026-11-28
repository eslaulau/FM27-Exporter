// Focused native hotspot pass. Uses the verified PE exception directory to
// obtain exact function bounds, avoiding repeated full IL2CPP and field scans.
import java.io.File;
import java.io.PrintWriter;
import java.util.*;

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.RefType;
import ghidra.program.model.symbol.SourceType;

public class TraceNativeHotspots extends GhidraScript {
    private static final long EXCEPTION_RVA = 0x18176000L;
    private static final long EXCEPTION_SIZE = 0x1A8710L;
    private static final int MAX_CALLERS = 80;
    private static final int MAX_CALLEES = 96;

    private final Map<Long,long[]> ranges = new TreeMap<>();
    private final Map<Long,Function> functions = new LinkedHashMap<>();
    private final LinkedHashMap<Long,String> seeds = new LinkedHashMap<>();
    private final Set<Long> callees = new LinkedHashSet<>();
    private final Map<Long,Function> callers = new LinkedHashMap<>();

    {
        seeds.put(0x45AC0L, "MATCH_PLAYER_DIRECTION_SEARCH_FIELDS_WRITER_CORE");
        seeds.put(0x1BB07C0L, "MATCH_PLAYER_DIRECTION_SEARCH_INPUT_B_WRITER_A");
        seeds.put(0x35927D0L, "MATCH_PLAYER_DIRECTION_SEARCH_INPUT_B_WRITER_B");
        seeds.put(0x185090L, "MATCH_PLAYER_DIRECTION_SEARCH_INPUT_A_BULK_COPY");
        seeds.put(0x4865900L, "MATCH_PLAYER_CANDIDATE_STATE_BUILDER");
        seeds.put(0x4873400L, "OOP_CANDIDATE_FILTER_GATE");
        seeds.put(0x4874AC0L, "PHASE_CANDIDATE_STATE_PROCESSOR");
        seeds.put(0x496F840L, "OOP_CANDIDATE_ARBITRATION");
        seeds.put(0x494F820L, "MOVEMENT_CANDIDATE_TEMPORAL_VALIDATOR");
        seeds.put(0x481A6A0L, "ADVANCED_SHOT_ZONE_MAIN_PROCESSOR");
        seeds.put(0x267E910L, "ADVANCED_SHOT_ZONE_BUILDER_A");
        seeds.put(0x2683270L, "ADVANCED_SHOT_ZONE_BUILDER_B");
        seeds.put(0x335C40L, "SHOT_ZONE_DATA_PROCESSOR_A");
        seeds.put(0x268B330L, "SHOT_ZONE_RECORD_CONTAINER_PROCESSOR");
        seeds.put(0x62682B0L, "SHOT_ZONE_RECORD_APPEND_PROCESSOR");
        seeds.put(0x4C01760L, "XG_SHOT_DATA_EVENT_RECORD_WRITER");
        seeds.put(0x568E0L, "SHOT_ZONE_COMMON_INITIALIZER");
        seeds.put(0x63118F0L, "ADVANCED_SHOT_ZONE_BUILDER_C");
        seeds.put(0x11FA50L, "OOP_ATTRIBUTE_CONFIG_TO_VALUE");
        seeds.put(0x11E260L, "PITCH_PROXIMITY_CONFIG_TO_VALUE");
        seeds.put(0x4BF9BA0L, "OOP_SCORING_PROVIDER_INITIALIZER");
        seeds.put(0x4BFAE10L, "OOP_ATTRIBUTE_SCORER_CONFIG_MEMBER");
        seeds.put(0x4BFA570L, "PITCH_PROXIMITY_SCORER_CONFIG_MEMBER");
        seeds.put(0x4C2DA40L, "MATCH_OOP_SCORING_PROVIDER_VTABLE_SLOT");
        // Writers of MATCH_PLAYER fields consumed by the seeded movement distributions.
        seeds.put(0x48334D0L, "DIRECTION_DISTRIBUTION_PROBABILITY_FIELD_WRITER");
        seeds.put(0x46E4740L, "DIRECTION_DISTRIBUTION_CENTRE_FIELDS_WRITER");
        seeds.put(0x47E44C0L, "DIRECTION_DISTRIBUTION_SECONDARY_GATE_WRITER");
        seeds.put(0x3BDB0L, "DIRECTION_DISTRIBUTION_SECONDARY_PROBABILITY_WRITER");
        seeds.put(0x3C720L, "MATCH_PLAYER_DIRECTION_BASE_FIELDS_INITIALIZER");
        seeds.put(0xF8050L, "DIRECTION_BASE_FIELD_SECONDARY_WRITER");
        seeds.put(0x452FF10L, "MATCH_PLAYER_DIRECTION_BASE_FIELDS_BULK_INITIALIZER");
        seeds.put(0x1435D0L, "DIRECTION_SECONDARY_GATE_ALTERNATE_WRITER");
        seeds.put(0x1038C0L, "DIRECTION_BASE_FIELD_TACTIC_REFRESH_WRITER");
        seeds.put(0x42D9FD0L, "DIRECTION_GATE_TACTIC_REFRESH_WRITER_A");
        seeds.put(0x42DA430L, "DIRECTION_GATE_TACTIC_REFRESH_WRITER_B");
        seeds.put(0x42DA770L, "DIRECTION_GATE_TACTIC_REFRESH_WRITER_C");
        seeds.put(0x42DAE40L, "DIRECTION_GATE_TACTIC_REFRESH_WRITER_D");
        seeds.put(0x4969440L, "DIRECTION_DERIVED_FIELD_RANGE_WRITER");
        seeds.put(0x3798830L, "DIRECTION_DERIVED_FIELD_COEFFICIENT_WRITER");
        // XG_SHOT_DATA event path: trace payload helpers and event/state writers.
        seeds.put(0x4D1F0L, "XG_SHOT_EVENT_CONTEXT_BUILDER");
        seeds.put(0x1691C0L, "XG_SHOT_EVENT_PAYLOAD_FINALIZER");
        seeds.put(0x164680L, "XG_SHOT_GOALKEEPER_OR_TARGET_CONTEXT");
        seeds.put(0x166400L, "XG_SHOT_EVENT_TEAM_STAT_UPDATE");
        seeds.put(0x498D400L, "XG_SHOT_MATCH_EVENT_VALUE_PROVIDER");
        seeds.put(0x4C01AC0L, "XG_SHOT_EVENT_PLAYER_LINK_RESOLVER");
        seeds.put(0x3592400L, "XG_SHOT_SECONDARY_EVENT_STATE_WRITER");
        // Fields that feed the seeded direction-parameter distributions.
        seeds.put(0x2170L, "DIRECTION_INPUT_BASE_FIELD_WRITER_SEED_A");
        seeds.put(0x21F0L, "DIRECTION_INPUT_BASE_FIELD_WRITER_SEED_B");
        seeds.put(0x21F8L, "DIRECTION_INPUT_BASE_FIELD_WRITER_SEED_C");
        // MATCH_PLAYER direction-input derivation helpers.
        seeds.put(0x48362D0L, "DIRECTION_INPUT_A_DERIVATION_HELPER");
        seeds.put(0x49A20L, "DIRECTION_INPUT_A_SECONDARY_HELPER");
        seeds.put(0x49ED0L, "DIRECTION_INPUT_B_DERIVATION_HELPER");
        seeds.put(0x49B40L, "DIRECTION_INPUT_A_CONSTRAINT_HELPER");
        // Upstream accessors used by the direction-distribution field initializers.
        seeds.put(0x4704100L, "MATCH_PLAYER_TACTICAL_PARAMETER_ACCESSOR");
        seeds.put(0x4815250L, "DIRECTION_BASE_INITIALIZER_CONTEXT_HELPER_A");
        seeds.put(0x4822D50L, "DIRECTION_BASE_INITIALIZER_CONTEXT_HELPER_B");
        seeds.put(0x4984DD0L, "DIRECTION_PROBABILITY_WRITER_CONTEXT_HELPER");
        seeds.put(0x4844060L, "DIRECTION_PROBABILITY_WRITER_NUMERIC_HELPER");
        seeds.put(0x47F1E70L, "DIRECTION_SECONDARY_GATE_POST_PROCESSOR");
        seeds.put(0x42D23A0L, "DIRECTION_SECONDARY_GATE_STATE_HELPER");
        seeds.put(0x47B9510L, "DIRECTION_SECONDARY_GATE_VALUE_HELPER");
        // Advanced shot-zone high-frequency direct callees.
        seeds.put(0x47BA710L, "SHOT_ZONE_SAMPLE_ITERATOR_CORE");
        seeds.put(0x4C35210L, "SHOT_ZONE_DYNAMIC_SCORE_DISPATCH_A");
        seeds.put(0x4703F10L, "SHOT_ZONE_NUMERIC_HELPER_A");
        seeds.put(0x4800C40L, "SHOT_ZONE_PHASE_STATE_GATE");
        seeds.put(0x4943510L, "SHOT_ZONE_NUMERIC_HELPER_B");
        seeds.put(0x4709800L, "SHOT_ZONE_NUMERIC_HELPER_C");
        seeds.put(0x49534D0L, "SHOT_ZONE_NUMERIC_HELPER_D");
        seeds.put(0x4C35230L, "SHOT_ZONE_DYNAMIC_SCORE_DISPATCH_B");
        seeds.put(0x4820300L, "SHOT_ZONE_NUMERIC_HELPER_E");
        seeds.put(0x48A6E20L, "SHOT_ZONE_NUMERIC_HELPER_F");
        seeds.put(0x48235E0L, "SHOT_ZONE_NUMERIC_HELPER_G");
        seeds.put(0x481FCC0L, "SHOT_ZONE_NUMERIC_HELPER_H");
        seeds.put(0x48210D0L, "SHOT_ZONE_NUMERIC_HELPER_I");
        seeds.put(0x47C82C0L, "SHOT_ZONE_NUMERIC_HELPER_J");
        seeds.put(0x47C8120L, "SHOT_ZONE_NUMERIC_HELPER_K");
        seeds.put(0x482FD50L, "SHOT_ZONE_NUMERIC_HELPER_L");
        seeds.put(0x47BEB40L, "SHOT_ZONE_NUMERIC_HELPER_M");
        seeds.put(0x4764B90L, "SHOT_ZONE_NUMERIC_HELPER_N");
        seeds.put(0x13F820L, "SHOT_ZONE_NUMERIC_HELPER_O");
        seeds.put(0x47D0E10L, "SHOT_ZONE_NUMERIC_HELPER_P");
        seeds.put(0x484CE10L, "SHOT_ZONE_NUMERIC_HELPER_Q");
        seeds.put(0x498C940L, "SHOT_ZONE_NUMERIC_HELPER_R");
        seeds.put(0x4782B90L, "SHOT_ZONE_NUMERIC_HELPER_S");
        seeds.put(0x47A2F20L, "SHOT_ZONE_NUMERIC_HELPER_T");
        seeds.put(0x4C0E300L, "SHOT_ZONE_DYNAMIC_SCORE_DISPATCH_C");
    }

    private String safe(String s) {
        return s.replaceAll("[^A-Za-z0-9_$]", "_");
    }

    private void loadRuntimeFunctionRanges() throws Exception {
        Address base = currentProgram.getImageBase();
        Address table = base.add(EXCEPTION_RVA);
        long count = EXCEPTION_SIZE / 12L;
        for (long i=0; i<count; i++) {
            Address row = table.add(i*12L);
            long begin = Integer.toUnsignedLong(currentProgram.getMemory().getInt(row));
            long end = Integer.toUnsignedLong(currentProgram.getMemory().getInt(row.add(4)));
            long unwind = Integer.toUnsignedLong(currentProgram.getMemory().getInt(row.add(8)));
            if (begin < end && end <= currentProgram.getMaxAddress().subtract(base)+1) {
                ranges.put(begin, new long[]{end,unwind});
            }
        }
    }

    private long[] exactRange(long rva) {
        return ranges.get(rva);
    }

    private Function ensureFunction(long rva, String name, PrintWriter summary) throws Exception {
        Address entry = currentProgram.getImageBase().add(rva);
        Function existing = currentProgram.getFunctionManager().getFunctionAt(entry);
        if (existing != null && existing.getBody().getNumAddresses() > 1) {
            functions.put(rva,existing);
            summary.println("REUSE_ENTRY_FUNCTION\\t"+name+"\\tRVA=0x"+
                Long.toHexString(rva)+"\\tBYTES="+existing.getBody().getNumAddresses()+
                "\\tNAME="+existing.getName());
            return existing;
        }
        Function containing = currentProgram.getFunctionManager().getFunctionContaining(entry);
        if (existing == null && containing != null) {
            functions.put(rva,containing);
            summary.println("REUSE_CONTAINING_FUNCTION\\t"+name+"\\tRVA=0x"+
                Long.toHexString(rva)+"\\tENTRY="+containing.getEntryPoint()+
                "\\tBYTES="+containing.getBody().getNumAddresses());
            return containing;
        }
        long[] range = exactRange(rva);
        if (range == null) {
            summary.println("NO_PDATA_RANGE\\t"+name+"\\tRVA=0x"+Long.toHexString(rva));
            return null;
        }
        MemoryBlock block = currentProgram.getMemory().getBlock(entry);
        if (block == null || !block.isExecute()) {
            summary.println("NOT_EXECUTABLE\t"+name+"\tRVA=0x"+Long.toHexString(rva));
            return null;
        }
        Address end = currentProgram.getImageBase().add(range[0]-1);
        AddressSet fullRange = new AddressSet(entry,end);
        DisassembleCommand cmd = new DisassembleCommand(entry,fullRange,true);
        cmd.applyTo(currentProgram,monitor);
        // Include instructions already created by the PE loader as well as
        // newly disassembled ones; loader-created entry stubs can have 1-byte bodies.
        AddressSet body = new AddressSet();
        InstructionIterator iterator = currentProgram.getListing().getInstructions(fullRange,true);
        while(iterator.hasNext()) {
            Instruction ins = iterator.next();
            body.add(ins.getMinAddress(),ins.getMaxAddress());
        }
        if (!body.contains(entry) || body.getNumAddresses()<2) {
            summary.println("DECODE_TOO_SMALL\\t"+name+"\\tRVA=0x"+
                Long.toHexString(rva)+"\\tstatus="+cmd.getStatusMsg());
            return null;
        }
        // Remove only functions whose bodies overlap this exact pdata range.
        // This resolves Ghidra namespace collisions from loader-created stubs.
        java.util.Iterator<Function> overlaps =
            currentProgram.getFunctionManager().getFunctionsOverlapping(body);
        List<Function> remove = new ArrayList<>();
        while (overlaps.hasNext()) {
            Function oldFunction = overlaps.next();
            if (!oldFunction.getEntryPoint().equals(entry)) remove.add(oldFunction);
        }
        for (Function oldFunction : remove) {
            summary.println("REMOVE_OVERLAPPING_FUNCTION\\t"+oldFunction.getEntryPoint()+
                "\\t"+oldFunction.getName());
            currentProgram.getFunctionManager().removeFunction(oldFunction.getEntryPoint());
        }
        Function f = existing;
        if (f != null) {
            try {
                f.setBody(body);
                summary.println("EXTEND_ENTRY_FUNCTION\\t"+name+"\\tRVA=0x"+
                    Long.toHexString(rva)+"\\tBYTES="+f.getBody().getNumAddresses());
                functions.put(rva,f);
                return f;
            } catch (Exception ex) {
                summary.println("SET_BODY_FAILED\\t"+name+"\\tRVA=0x"+
                    Long.toHexString(rva)+"\\t"+ex);
                currentProgram.getFunctionManager().removeFunction(entry);
            }
        }
        try {
            f = currentProgram.getFunctionManager().createFunction(
                safe(name),entry,body,SourceType.ANALYSIS);
        } catch (Exception ex) {
            summary.println("CREATE_FUNCTION_FAILED\\t"+name+"\\tRVA=0x"+
                Long.toHexString(rva)+"\\t"+ex);
            f = currentProgram.getFunctionManager().getFunctionAt(entry);
            if (f == null) f=currentProgram.getFunctionManager().getFunctionContaining(entry);
        }
        if (f != null) functions.put(rva,f);
        return f;
    }

    private void decompile(Function f, DecompInterface decomp, PrintWriter out, String label) {
        out.println("\n// ===== "+f.getEntryPoint()+" "+label+
            " BODY_BYTES="+f.getBody().getNumAddresses()+" =====");
        long n=f.getBody().getNumAddresses();
        int timeout=n>0x7000?60:(n>0x2500?45:(n>0x800?25:15));
        DecompileResults r=decomp.decompileFunction(f,timeout,monitor);
        if (r!=null && r.decompileCompleted() && r.getDecompiledFunction()!=null)
            out.println(r.getDecompiledFunction().getC());
        else out.println("// DECOMPILE_FAILED "+(r==null?"no result":r.getErrorMessage()));
    }

    private void collectRefs(Function f, PrintWriter refs) {
        InstructionIterator it=currentProgram.getListing().getInstructions(f.getBody(),true);
        while(it.hasNext()) {
            Instruction ins=it.next();
            for(Reference ref:currentProgram.getReferenceManager().getReferencesFrom(ins.getAddress())) {
                Address to=ref.getToAddress();
                long target;
                try { target=to.subtract(currentProgram.getImageBase()); }
                catch(Exception ex) { continue; }
                if(ref.getReferenceType().isCall() && target>=0) {
                    callees.add(target);
                    Function caller=currentProgram.getFunctionManager().getFunctionContaining(ins.getAddress());
                    refs.println("CALL\tFROM_RVA=0x"+Long.toHexString(ins.getAddress().subtract(currentProgram.getImageBase()))+
                        "\tTO_RVA=0x"+Long.toHexString(target)+"\tTYPE="+ref.getReferenceType());
                }
            }
        }
        ReferenceIterator incoming=currentProgram.getReferenceManager().getReferencesTo(f.getEntryPoint());
        int n=0;
        while(incoming.hasNext() && n<MAX_CALLERS) {
            Reference ref=incoming.next();
            if(!ref.getReferenceType().isCall()) continue;
            Function caller=currentProgram.getFunctionManager().getFunctionContaining(ref.getFromAddress());
            if(caller!=null && !caller.getEntryPoint().equals(f.getEntryPoint())) {
                long rva=caller.getEntryPoint().subtract(currentProgram.getImageBase());
                callers.put(rva,caller);
                refs.println("INCOMING\tTARGET_RVA=0x"+
                    Long.toHexString(f.getEntryPoint().subtract(currentProgram.getImageBase()))+
                    "\tCALLER_RVA=0x"+Long.toHexString(rva));
                n++;
            }
        }
    }

    @Override
    protected void run() throws Exception {
        String[] args=getScriptArgs();
        File outDir=new File(args.length>0?args[0]:"analysis/native-hotspots");
        outDir.mkdirs();
        try(PrintWriter summary=new PrintWriter(new File(outDir,"native-hotspot-summary.txt"),"UTF-8");
            PrintWriter refs=new PrintWriter(new File(outDir,"native-hotspot-xrefs.txt"),"UTF-8");
            PrintWriter dec=new PrintWriter(new File(outDir,"native-hotspot-decompilations.txt"),"UTF-8")) {
            summary.println("PROGRAM="+currentProgram.getName()+" IMAGE_BASE="+currentProgram.getImageBase());
            summary.println("EXCEPTION_RVA=0x"+Long.toHexString(EXCEPTION_RVA)+
                " EXCEPTION_SIZE=0x"+Long.toHexString(EXCEPTION_SIZE));
            loadRuntimeFunctionRanges();
            summary.println("RUNTIME_FUNCTION_RANGES="+ranges.size());
            DecompInterface decomp=new DecompInterface();
            decomp.openProgram(currentProgram);

            for(Map.Entry<Long,String> e:seeds.entrySet()) {
                if(monitor.isCancelled()) break;
                Function f;
                try {
                    f=ensureFunction(e.getKey(),e.getValue(),summary);
                } catch (Exception ex) {
                    summary.println("SEED_ERROR\\t"+e.getValue()+"\\tRVA=0x"+
                        Long.toHexString(e.getKey())+"\\t"+ex);
                    continue;
                }
                if(f==null) continue;
                long[] range=exactRange(e.getKey());
                summary.println("SEED\t"+e.getValue()+"\tRVA=0x"+
                    Long.toHexString(e.getKey())+"\tEND_RVA=0x"+
                    Long.toHexString(range[0])+"\tBYTES="+f.getBody().getNumAddresses());
                collectRefs(f,refs);
                decompile(f,decomp,dec,e.getValue());
            }

            int calleeCount=0;
            for(long rva:callees) {
                if(monitor.isCancelled() || calleeCount>=MAX_CALLEES) break;
                if(functions.containsKey(rva)) continue;
                Function f=ensureFunction(rva,"HOTSPOT_CALLEE_"+Long.toHexString(rva),summary);
                if(f==null) continue;
                calleeCount++;
                summary.println("CALLEE\tRVA=0x"+Long.toHexString(rva)+
                    "\tBYTES="+f.getBody().getNumAddresses());
                decompile(f,decomp,dec,f.getName());
            }

            int callerCount=0;
            for(Map.Entry<Long,Function> e:callers.entrySet()) {
                if(monitor.isCancelled() || callerCount>=MAX_CALLERS) break;
                Function f=e.getValue();
                summary.println("CALLER\tRVA=0x"+Long.toHexString(e.getKey())+
                    "\tBYTES="+f.getBody().getNumAddresses());
                decompile(f,decomp,dec,f.getName());
                callerCount++;
            }
            summary.println("ANALYZED_SEEDS="+functions.size());
            summary.println("DIRECT_CALLEES_ANALYZED="+calleeCount);
            summary.println("INCOMING_CALLERS_ANALYZED="+callerCount);
            decomp.dispose();
        }
    }
}
