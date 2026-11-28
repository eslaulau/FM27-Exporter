// Decompile containing functions for x64 code references to native RTTI objects.
import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.Comparator;
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
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.SourceType;

public class DecompileNativeRttiXrefFunctions extends GhidraScript {
    private static final int MAX_FUNCTIONS = 96;
    private static final long MAX_BODY_BYTES = 0x30000L;

    private static class Caller {
        long start;
        long end;
        Set<String> targets = new LinkedHashSet<>();
        Set<String> kinds = new LinkedHashSet<>();
    }

    private int priority(String name) {
        String s=name.toUpperCase();
        if(s.contains("MATCH_DECISION_PROVIDER")) return 0;
        if(s.contains("MATCH_MANAGER_TACTICAL_INPUT") ||
           s.contains("MATCH_MANAGER_ADDITIONAL_TACTICAL_INPUT") ||
           s.contains("MATCH_PLAYER_INPUT") || s.contains("MATCH_INPUT_BASIC")) return 1;
        if(s.contains("MATCH_PLAYING_DATA") || s.endsWith("::MATCH")) return 2;
        if(s.contains("MATCH_PRESSING_FACTORY") || s.contains("MATCH_PRESSING_MANAGER")) return 3;
        if(s.contains("MATCH_OOP_SCORING_PROVIDER") || s.contains("OOP_ATTRIBUTE") ||
           s.contains("PITCH_PROXIMITY_SCORE") || s.contains("DYNAMIC_POSITION_SCORES")) return 4;
        if(s.contains("MATCH_WEIGHTS_PROVIDER")) return 5;
        if(s.contains("TACTICS_MANAGER") || s.contains("TACTIC_INFO") ||
           s.contains("TACTIC_LOADER") || s.contains("TACTICAL_ROLE") ||
           s.contains("PLAYER_INSTRUCTIONS_MANAGER")) return 6;
        if(s.contains("TACTIC_CHANGE") || s.contains("POSITION_PACKET")) return 7;
        return 9;
    }

    private String safe(String s) {
        String x=s.replaceAll("[^A-Za-z0-9_$]","_");
        return x.length()>100?x.substring(0,100):x;
    }

    private Function analyze(Caller caller, PrintWriter summary, PrintWriter asm,
                             DecompInterface decomp, PrintWriter dec) throws Exception {
        Address entry=currentProgram.getImageBase().add(caller.start);
        Address end=currentProgram.getImageBase().add(caller.end-1);
        MemoryBlock block=currentProgram.getMemory().getBlock(entry);
        if(block==null || !block.isExecute() || !entry.getAddressSpace().equals(end.getAddressSpace())) {
            summary.println("SKIP_RANGE\t"+entry+"\t"+end);
            return null;
        }
        if(end.compareTo(block.getEnd())>0) end=block.getEnd();
        if(caller.end-caller.start>MAX_BODY_BYTES) {
            summary.println("SKIP_OVERSIZE\t"+entry+"\tbytes="+(caller.end-caller.start));
            return null;
        }

        Function f=currentProgram.getFunctionManager().getFunctionAt(entry);
        if(f!=null && f.getBody().getNumAddresses()>1) {
            summary.println("REUSE\t"+entry+"\t"+f.getName()+
                "\tbytes="+f.getBody().getNumAddresses());
        } else {
            if(f!=null) currentProgram.getFunctionManager().removeFunction(entry);
            DisassembleCommand cmd=new DisassembleCommand(entry,new AddressSet(entry,end),true);
            boolean ok=cmd.applyTo(currentProgram,monitor);
            AddressSetView decoded=cmd.getDisassembledAddressSet();
            AddressSet body=new AddressSet();
            InstructionIterator it=currentProgram.getListing().getInstructions(decoded,true);
            int insCount=0;
            while(it.hasNext()) {
                Instruction ins=it.next();
                body.add(ins.getMinAddress(),ins.getMaxAddress());
                insCount++;
            }
            if(!body.contains(entry) || body.getNumAddresses()<5) {
                summary.println("DECODE_FAILED\t"+entry+"\tok="+ok+
                    "\tbytes="+body.getNumAddresses()+"\t"+cmd.getStatusMsg());
                return null;
            }
            java.util.Iterator<Function> overlaps =
                currentProgram.getFunctionManager().getFunctionsOverlapping(body);
            List<Function> other=new ArrayList<>();
            while(overlaps.hasNext()) {
                Function overlap=overlaps.next();
                if(!overlap.getEntryPoint().equals(entry)) other.add(overlap);
            }
            for(Function overlap:other) body.delete(overlap.getBody());
            if(!body.contains(entry)) return null;
            f=currentProgram.getFunctionManager().createFunction(
                "RTTI_CALLER_"+Long.toHexString(caller.start),entry,body,SourceType.ANALYSIS);
            if(f==null) return null;
            summary.println("CREATED\t"+entry+"\tbytes="+body.getNumAddresses()+
                "\tinstructions="+insCount);
        }

        summary.println("TARGETS\t"+entry+"\t"+String.join(" | ",caller.targets));
        asm.println("\n===== "+entry+" "+f.getName()+" TARGETS="+
            String.join(" | ",caller.targets)+" =====");
        InstructionIterator it=currentProgram.getListing().getInstructions(f.getBody(),true);
        int n=0;
        while(it.hasNext()&&n<2500) {
            Instruction ins=it.next();
            asm.println(ins.getAddress()+"\t"+ins);
            n++;
        }

        dec.println("\n// ===== "+entry+" "+f.getName()+
            " TARGETS="+String.join(" | ",caller.targets)+" =====");
        if(f.getBody().getNumAddresses()>MAX_BODY_BYTES) {
            dec.println("// SKIPPED_OVERSIZE");
        } else {
            DecompileResults result=decomp.decompileFunction(f,12,monitor);
            if(result!=null&&result.decompileCompleted()&&result.getDecompiledFunction()!=null)
                dec.println(result.getDecompiledFunction().getC());
            else dec.println("// DECOMPILE_FAILED "+(result==null?"no result":result.getErrorMessage()));
        }
        return f;
    }

    @Override
    protected void run() throws Exception {
        String[] args=getScriptArgs();
        if(args.length<2) {
            println("Usage: DecompileNativeRttiXrefFunctions.java <code-xrefs.tsv> <output-dir>");
            return;
        }
        File input=new File(args[0]);
        File out=new File(args[1]);
        out.mkdirs();

        Map<Long,Caller> callers=new LinkedHashMap<>();
        try(BufferedReader reader=new BufferedReader(new FileReader(input))) {
            String line=reader.readLine();
            while((line=reader.readLine())!=null) {
                String[] p=line.split("\t",-1);
                if(p.length<8 || p[5].isEmpty() || p[6].isEmpty()) continue;
                if(priority(p[3])>7) continue;
                try {
                    String s=p[5].replaceFirst("^(0x|0X)","");
                    String e=p[6].replaceFirst("^(0x|0X)","");
                    long start=Long.parseUnsignedLong(s,16);
                    long end=Long.parseUnsignedLong(e,16);
                    if(end<=start) continue;
                    Caller caller=callers.computeIfAbsent(start,k->new Caller());
                    caller.start=start;
                    caller.end=end;
                    caller.targets.add(p[3]);
                    caller.kinds.add(p[2]);
                } catch(Exception ignored) {}
            }
        }

        List<Caller> ordered=new ArrayList<>(callers.values());
        ordered.sort(Comparator.comparingInt((Caller c)->c.targets.stream()
            .mapToInt(this::priority).min().orElse(9)).thenComparingLong(c->c.start));
        PrintWriter summary=new PrintWriter(new File(out,"native-rtti-caller-summary.txt"),"UTF-8");
        PrintWriter asm=new PrintWriter(new File(out,"native-rtti-caller-disassembly.txt"),"UTF-8");
        PrintWriter dec=new PrintWriter(new File(out,"native-rtti-caller-decompilations.txt"),"UTF-8");
        summary.println("PROGRAM="+currentProgram.getName());
        summary.println("INPUT_XREF_FILE="+input.getAbsolutePath());
        summary.println("UNIQUE_CALLER_FUNCTIONS="+ordered.size());
        DecompInterface decomp=new DecompInterface();
        decomp.openProgram(currentProgram);
        int analyzed=0;
        for(Caller caller:ordered) {
            if(monitor.isCancelled()||analyzed>=MAX_FUNCTIONS) break;
            Function f=analyze(caller,summary,asm,decomp,dec);
            if(f!=null) analyzed++;
        }
        summary.println("ANALYZED_CALLER_FUNCTIONS="+analyzed);
        dec.println("\n// ANALYZED_CALLER_FUNCTIONS="+analyzed);
        decomp.dispose();
        summary.close();asm.close();dec.close();
    }
}
