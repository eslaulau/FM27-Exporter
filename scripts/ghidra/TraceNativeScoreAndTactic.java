// Trace native scoring, movement and tactical-load bridge functions.
// Exports key strings, direct call edges, incoming call references and bounded decompilations.
import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.address.AddressSetView;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.RefType;
import ghidra.program.model.symbol.SourceType;

public class TraceNativeScoreAndTactic extends GhidraScript {
    private static final int MAX_CALLEES = 64;
    private static final int MAX_INCOMING = 200;
    private static final long WINDOW = 0x5000L;
    private static final long MAX_DECOMPILE = 0x20000L;

    private final Map<Long,String> seeds = new LinkedHashMap<>();
    {
        seeds.put(0x11fa50L, "OOP_ATTRIBUTE_CONFIG_TO_VALUE");
        seeds.put(0x11e260L, "PITCH_PROXIMITY_CONFIG_TO_VALUE");
        seeds.put(0x4c2dae0L, "IOOP_SCORE_DYNAMIC_POSITION_SLOT");
        seeds.put(0x4c2daa0L, "IOOP_SCORE_DYNAMIC_SLOT");
        seeds.put(0x4c351e0L, "IOOP_SCORE_INDIRECT_THUNK");
        seeds.put(0x3e6d980L, "MATCH_OOP_SCORING_PROVIDER_SINGLETON");
        seeds.put(0x38254f0L, "MATCH_WEIGHTS_PROVIDER_SINGLETON");
        seeds.put(0x4576270L, "MATCH_PRESSING_FACTORY_VTABLE_SLOT");
        seeds.put(0x45762a0L, "MATCH_PRESSING_FACTORY_SINGLETON");
        seeds.put(0x28d7300L, "PLAYER_POSITIONS_PACKET_SLOT_1");
        seeds.put(0x28d7460L, "PLAYER_POSITIONS_PACKET_SLOT_2");
        seeds.put(0x4bfe840L, "MATCH_BASE_SLOT_0");
        seeds.put(0x28cfcf0L, "MATCH_BASE_SLOT_1");
        seeds.put(0x28d6400L, "MATCH_BASE_SLOT_2");
        seeds.put(0x2b088a0L, "MATCH_PLAYING_DATA_SLOT_0");
        seeds.put(0x4845300L, "MATCH_PLAYING_DATA_SLOT_1");
        seeds.put(0x496bb40L, "MATCH_PLAYING_DATA_SLOT_2");
        seeds.put(0x270bbd0L, "UPDATE_TEAM_OOP_POSITION_RECORD");
        seeds.put(0x103a10L, "COPY_TACTICAL_DATA_TO_MATCH_PLAYER");
        seeds.put(0x72b20L, "REFRESH_MATCH_PLAYER_FROM_TACTIC_POSITION");
        seeds.put(0x1028a40L, "APPLY_TACTIC_ROLE_MAP_TO_MATCH_STATE");
        seeds.put(0x4bf67e0L, "UPDATE_MATCH_PLAYER_TACTIC_SNAPSHOT");
        seeds.put(0x4bf98e3L, "MATCH_PRESSING_FACTORY_RTTI_REFERENCE_CALLSITE");
        seeds.put(0x4c15660L, "MATCH_PRESSING_FACTORY_SINGLETON_REFERENCE_CALLSITE");
        seeds.put(0x4bf9a50L, "MATCH_WEIGHTS_PROVIDER_INITIALIZER");
        seeds.put(0x4bf9c70L, "OOP_ATTRIBUTE_SCORER_INITIALIZER");
        seeds.put(0x4bf9d30L, "PITCH_PROXIMITY_SCORER_INITIALIZER");
        seeds.put(0x104760L, "PLAYER_TACTIC_FLAGS_PRIMARY_STATE_DECODER");
        seeds.put(0x1043b0L, "PLAYER_TACTIC_FLAGS_SECONDARY_STATE_DECODER");
        seeds.put(0x492ed70L, "OOP_SLOT_RECORD_DERIVED_BYTE");
        seeds.put(0x484edb0L, "OOP_PRIMARY_EXTENDED_RECORD_COMBINER");
        seeds.put(0x0c5580L, "MATCH_PLAYER_POST_TACTIC_REFRESH");
        seeds.put(0x104fa0L, "MATCH_PLAYER_EXTENDED_SLOT_VALUE_DERIVER");
        seeds.put(0x2b57ba0L, "TEAM_TACTIC_COLLECTION_APPLIER");
        seeds.put(0x2bbf350L, "APPLY_TWEAK_TACTIC_CHANGE_SLOT_1");
        seeds.put(0x2bbf420L, "APPLY_TWEAK_TACTIC_CHANGE_SLOT_2");
        seeds.put(0x2bbf580L, "APPLY_TWEAK_TACTIC_CHANGE_SLOT_4");
        seeds.put(0x2bbfcc0L, "REMOVE_TWEAK_TACTIC_CHANGE_SLOT_1");
        seeds.put(0x2bbfd90L, "REMOVE_TWEAK_TACTIC_CHANGE_SLOT_2");
        seeds.put(0x42f5b40L, "TACTICS_CREATOR_OOP_POSITION_CHANGE_SLOT_1");
        seeds.put(0x42f5bd0L, "TACTICS_CREATOR_OOP_POSITION_CHANGE_SLOT_2");
        seeds.put(0x42f59f0L, "TACTICS_CREATOR_OOP_POSITION_CHANGE_SLOT_3");
        seeds.put(0x42f8cc0L, "TACTIC_ROLES_CHANGE_SLOT_1");
        seeds.put(0x42f8d40L, "TACTIC_ROLES_CHANGE_SLOT_2");
        seeds.put(0x42f8a40L, "TACTIC_ROLES_CHANGE_SLOT_3");
        seeds.put(0x42f9080L, "TACTICS_CHANGE_OPP_PLAYER_SPECIFIC_SLOT_1");
        seeds.put(0x4c2da40L, "MATCH_OOP_SCORING_PROVIDER_VTABLE_SLOT");
        seeds.put(0x4c2a2f0L, "MATCH_WEIGHTS_PROVIDER_VTABLE_SLOT");

        seeds.put(0x1bc240L, "MATCH_MOVEMENT_DIRECTOR_VTABLE_SLOT_0");
        seeds.put(0x4993230L, "MATCH_MOVEMENT_DIRECTOR_LOOKUP_SLOT");
        seeds.put(0x2f5bba0L, "TACTICS_MANAGER_CORE");
        seeds.put(0x2f5ba70L, "TACTICS_MANAGER_SECONDARY");
        seeds.put(0xe9ac40L, "TACTIC_LOADER_CORE");
        seeds.put(0x1be6060L, "GAME_TACTIC_INFO_LOAD");
        seeds.put(0x27d160L, "GAME_TACTIC_INFO_SLOT_0");
        seeds.put(0x3793740L, "PLAYER_INSTRUCTIONS_MANAGER_CORE");
        seeds.put(0x3795150L, "PLAYER_INSTRUCTIONS_MANAGER_SLOT_0");
        seeds.put(0x323f70L, "TACTICAL_ROLE_SLOT_0");
        seeds.put(0xfa660L, "MATCH_PLAYER_SLOT_11");
        seeds.put(0xfa7d0L, "MATCH_PLAYER_SLOT_12");
    }

    private final Map<Long,Function> functions = new LinkedHashMap<>();

    private String safe(String name) {
        String s = name.replaceAll("[^A-Za-z0-9_$]", "_");
        return s.length() > 100 ? s.substring(0,100) : s;
    }

    private Function ensureFunction(long rva, String name, PrintWriter summary) throws Exception {
        Address entry = currentProgram.getImageBase().add(rva);
        MemoryBlock block = currentProgram.getMemory().getBlock(entry);
        if (block == null || !block.isExecute()) {
            summary.println("SKIP_NON_EXECUTABLE\t" + name + "\t" + entry);
            return null;
        }
        Function existing = currentProgram.getFunctionManager().getFunctionAt(entry);
        if (existing != null && existing.getBody().getNumAddresses() > 1) {
            functions.put(rva, existing);
            return existing;
        }
        if (existing != null) currentProgram.getFunctionManager().removeFunction(entry);

        Address end = entry.add(WINDOW);
        if (end.compareTo(block.getEnd()) > 0) end = block.getEnd();
        DisassembleCommand cmd = new DisassembleCommand(entry, new AddressSet(entry,end), true);
        cmd.applyTo(currentProgram, monitor);
        AddressSetView decoded = cmd.getDisassembledAddressSet();
        AddressSet body = new AddressSet();
        InstructionIterator it = currentProgram.getListing().getInstructions(decoded,true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            body.add(ins.getMinAddress(),ins.getMaxAddress());
        }
        if (!body.contains(entry) || body.getNumAddresses() < 2) {
            summary.println("DECODE_TOO_SMALL\t" + name + "\t" + entry +
                "\tbytes=" + body.getNumAddresses() + "\tstatus=" + cmd.getStatusMsg());
            return null;
        }
        java.util.Iterator<Function> overlapping =
            currentProgram.getFunctionManager().getFunctionsOverlapping(body);
        List<Function> old = new ArrayList<>();
        while (overlapping.hasNext()) {
            Function f = overlapping.next();
            if (!f.getEntryPoint().equals(entry)) old.add(f);
        }
        for (Function f : old) body.delete(f.getBody());
        if (!body.contains(entry)) return null;
        Function f = currentProgram.getFunctionManager().createFunction(
            safe(name),entry,body,SourceType.ANALYSIS);
        if (f != null) functions.put(rva,f);
        return f;
    }

    private String readAscii(long rva, int cap) throws Exception {
        Address a = currentProgram.getImageBase().add(rva);
        Memory mem = currentProgram.getMemory();
        byte[] bytes = new byte[cap];
        int n = mem.getBytes(a,bytes);
        StringBuilder b = new StringBuilder();
        for (int i=0;i<n;i++) {
            int v=bytes[i]&0xff;
            if (v==0) break;
            if (v<0x20 || v>0x7e) return "";
            b.append((char)v);
        }
        return b.length()>=3?b.toString():"";
    }

    private void dumpRefs(Function f, PrintWriter refs,
                          Set<Long> callees) {
        InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(),true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            for (Reference ref : currentProgram.getReferenceManager().getReferencesFrom(ins.getAddress())) {
                Address to=ref.getToAddress();
                long targetRva;
                try { targetRva=to.subtract(currentProgram.getImageBase()); }
                catch(Exception ex) { continue; }
                RefType type=ref.getReferenceType();
                refs.println((type.isCall()?"CALL":"REF")+"\tFROM="+ins.getAddress()+
                    "\tTO="+to+"\tRVA=0x"+Long.toHexString(targetRva)+
                    "\tTYPE="+type);
                if (type.isCall() && targetRva>=0) callees.add(targetRva);
                if (!type.isCall()) {
                    try {
                        String text=readAscii(targetRva,192);
                        if (!text.isEmpty()) refs.println("STRING\tRVA=0x"+
                            Long.toHexString(targetRva)+"\t"+text);
                    } catch(Exception ignored) {}
                }
            }
        }
    }

    private void dumpIncoming(Function f, PrintWriter refs, Set<Function> callers) {
        int count=0;
        ReferenceIterator iterator=currentProgram.getReferenceManager().getReferencesTo(f.getEntryPoint());
        while(iterator.hasNext()) {
            Reference ref=iterator.next();
            if (count++>=MAX_INCOMING) break;
            if (!ref.getReferenceType().isCall()) continue;
            Function caller=currentProgram.getFunctionManager().getFunctionContaining(ref.getFromAddress());
            refs.println("INCOMING_CALL\tTARGET="+f.getEntryPoint()+
                "\tFROM="+ref.getFromAddress()+
                "\tCALLER="+(caller==null?"<unknown>":caller.getEntryPoint()+" "+caller.getName()));
            if (caller!=null) callers.add(caller);
        }
    }
    private void decompile(Function f, DecompInterface decomp, PrintWriter out, String label) {
        out.println("\n// ===== "+f.getEntryPoint()+" "+label+
            " BODY_BYTES="+f.getBody().getNumAddresses()+" =====");
        if (f.getBody().getNumAddresses()>MAX_DECOMPILE) {
            out.println("// SKIPPED_OVERSIZE");
            return;
        }
        DecompileResults r=decomp.decompileFunction(f,12,monitor);
        if (r!=null&&r.decompileCompleted()&&r.getDecompiledFunction()!=null)
            out.println(r.getDecompiledFunction().getC());
        else out.println("// DECOMPILE_FAILED "+(r==null?"no result":r.getErrorMessage()));
    }

    @Override
    protected void run() throws Exception {
        String[] args=getScriptArgs();
        File outDir=new File(args.length>0?args[0]:"analysis/native-score-trace");
        outDir.mkdirs();
        PrintWriter summary=new PrintWriter(new File(outDir,"native-score-tactic-summary.txt"),"UTF-8");
        PrintWriter refs=new PrintWriter(new File(outDir,"native-score-tactic-xrefs.txt"),"UTF-8");
        PrintWriter asm=new PrintWriter(new File(outDir,"native-score-tactic-disassembly.txt"),"UTF-8");
        PrintWriter dec=new PrintWriter(new File(outDir,"native-score-tactic-decompilations.txt"),"UTF-8");

        summary.println("PROGRAM="+currentProgram.getName()+" IMAGE_BASE="+currentProgram.getImageBase());
        // Strings / indirection tables exposed by the already decompiled scoring parsers.
        long[] dataRvas={0x512e1e5L,0x512e1f2L,0x4c745dbL,0x4c745e4L,
                         0x588e408L,0x5079dc8L,0x52ceaa8L};
        Set<Long> indirectDataTargets=new LinkedHashSet<>();
        for(long rva:dataRvas) {
            Address a=currentProgram.getImageBase().add(rva);
            MemoryBlock block=currentProgram.getMemory().getBlock(a);
            refs.println("DATA\tRVA=0x"+Long.toHexString(rva)+"\tVA="+a+
                "\tBLOCK="+(block==null?"<none>":block.getName()));
            try {
                String s=readAscii(rva,192);
                if(!s.isEmpty()) refs.println("ASCII\tRVA=0x"+Long.toHexString(rva)+"\t"+s);
                byte[] raw=new byte[48];
                int n=currentProgram.getMemory().getBytes(a,raw);
                StringBuilder hex=new StringBuilder();
                for(int i=0;i<n;i++) hex.append(String.format("%02X",raw[i]&0xff));
                refs.println("BYTES\tRVA=0x"+Long.toHexString(rva)+"\t"+hex);
                if (rva==0x52ceaa8L && n>=8) {
                    long pointer=currentProgram.getMemory().getLong(a);
                    long imageBase=currentProgram.getImageBase().getOffset();
                    long imageSize=currentProgram.getMaxAddress().subtract(currentProgram.getImageBase())+1;
                    refs.println("INDIRECT_POINTER\tDATA_RVA=0x52ceaa8\tRAW=0x"+
                        Long.toHexString(pointer)+"\tIMAGE_BASE=0x"+
                        Long.toHexString(imageBase)+"\tIMAGE_SIZE=0x"+
                        Long.toHexString(imageSize));
                    long pointerRva=-1;
                    String pointerKind="UNRESOLVED";
                    if (pointer>=0 && pointer<imageSize) {
                        pointerRva=pointer;
                        pointerKind="RVA";
                    } else if (pointer>=imageBase && pointer<imageBase+imageSize) {
                        pointerRva=pointer-imageBase;
                        pointerKind="VA";
                    }
                    refs.println("INDIRECT_POINTER_RESOLVED\tKIND="+pointerKind+
                        "\tRVA=0x"+Long.toHexString(pointerRva));
                    if (pointerRva>=0) {
                        Address target=currentProgram.getImageBase().add(pointerRva);
                        MemoryBlock targetBlock=currentProgram.getMemory().getBlock(target);
                        refs.println("INDIRECT_POINTER_TARGET\tVA="+target+
                            "\tBLOCK="+(targetBlock==null?"<none>":targetBlock.getName())+
                            "\tEXEC="+(targetBlock!=null && targetBlock.isExecute()));
                        if (targetBlock!=null && targetBlock.isExecute())
                            indirectDataTargets.add(pointerRva);
                    }
                }
            } catch(Exception ex) { refs.println("READ_ERROR\t"+ex); }
        }

        DecompInterface decomp=new DecompInterface();
        decomp.openProgram(currentProgram);
        for(long targetRva:indirectDataTargets) {
            seeds.putIfAbsent(targetRva,"IOOP_SCORE_INDIRECT_DATA_TARGET_"+Long.toHexString(targetRva));
        }
        Set<Long> callees=new LinkedHashSet<>();
        Set<Function> callers=new LinkedHashSet<>();
        int count=0;
        for(Map.Entry<Long,String> e:seeds.entrySet()) {
            if(monitor.isCancelled()) break;
            Function f=ensureFunction(e.getKey(),e.getValue(),summary);
            if(f==null) continue;
            count++;
            summary.println("SEED\t"+e.getValue()+"\tVA="+f.getEntryPoint()+
                "\tRVA=0x"+Long.toHexString(e.getKey())+
                "\tBODY_BYTES="+f.getBody().getNumAddresses());
            dumpRefs(f,refs,callees);
            dumpIncoming(f,refs,callers);
            asm.println("\n===== "+f.getEntryPoint()+" "+e.getValue()+" =====");
            InstructionIterator it=currentProgram.getListing().getInstructions(f.getBody(),true);
            int n=0;
            while(it.hasNext()&&n<3000){Instruction ins=it.next();asm.println(ins.getAddress()+"\t"+ins);n++;}
            decompile(f,decomp,dec,e.getValue());
        }

        // One-hop direct-call expansion from the seed set, limited to avoid unrelated code.
        int emitted=0;
        for(long rva:callees) {
            if(monitor.isCancelled()||emitted>=MAX_CALLEES) break;
            if(functions.containsKey(rva)) continue;
            Function f=ensureFunction(rva,"DIRECT_CALLEE_"+Long.toHexString(rva),summary);
            if(f==null) continue;
            emitted++;
            summary.println("CALLEE\t"+f.getName()+"\tVA="+f.getEntryPoint()+
                "\tRVA=0x"+Long.toHexString(rva)+
                "\tBODY_BYTES="+f.getBody().getNumAddresses());
            dumpRefs(f,refs,new LinkedHashSet<Long>());
            asm.println("\n===== "+f.getEntryPoint()+" "+f.getName()+" =====");
            InstructionIterator it=currentProgram.getListing().getInstructions(f.getBody(),true);
            int n=0;
            while(it.hasNext()&&n<1000){Instruction ins=it.next();asm.println(ins.getAddress()+"\t"+ins);n++;}
            decompile(f,decomp,dec,f.getName());
        }
        summary.println("SEED_FUNCTIONS_ANALYZED="+count);
        summary.println("UNIQUE_DIRECT_CALLS_FOUND="+callees.size());
        summary.println("DIRECT_CALLEES_ANALYZED="+emitted);
        summary.println("KNOWN_INCOMING_CALLERS="+callers.size());
        dec.println("\n// DIRECT_CALLEES_ANALYZED="+emitted);
        decomp.dispose();
        summary.close();refs.close();asm.close();dec.close();
    }
}
