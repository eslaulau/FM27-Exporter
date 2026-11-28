// Bounded RTTI-seeded native match-engine disassembly without expensive global auto-analysis.
import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.RefType;

public class ExportMatchEngineFast extends GhidraScript {
    private final long[] seeds = {
        0x1bc240L,0x4c2fd10L,0x42d64e0L,0x42d64f0L,0x42d6500L,0x42d6510L,0x42d6520L,0x4993230L,
        0x42d6530L,0x42d6540L,0x42d6550L,0x42d6560L,0x42d6570L,0x42d6580L,0x42d6590L,
        0x4c2a2f0L,0x4c2da40L,0x4576270L,
        0x1c0160L,0x47fa990L,0x1c0190L,0x4996d50L,0x1c01c0L,0x4997910L,
        0x27d3f0L,0x27d420L,0x27d430L,
        0x323f70L,0x323fa0L,0x121f990L,0x121f9a0L,0x121f980L,0x226590L,0x2265a0L,0x2265b0L,0x121f9b0L,0x121f970L,
        0x153ce0L,0x4c70L,0x26f9700L,0x16b030L,0xe4f800L,0xe4f810L,0x11d0L,0xe4f820L,0xd7be0L,0xd7c80L,
        0x1511a0L,0x1327f0L,0x132800L,0x270c1d0L,
        0x2b087a0L,0x1b6640L,0x2b02030L,0x183820L,0x19d0L,0x2b08890L,0x4956e00L,0x2b08450L,0xfa660L,0xfa7d0L
    };

    private Function ensureFunction(Address entry,String label,PrintWriter log) throws Exception {
        MemoryBlock block=currentProgram.getMemory().getBlock(entry);
        if(block==null||!block.isExecute()){log.println("SKIP_NON_EXECUTABLE\t"+label+"\t"+entry);return null;}
        Function f=currentProgram.getFunctionManager().getFunctionAt(entry);
        if(f==null){
            try{disassemble(entry);f=createFunction(entry,label);}
            catch(Exception ex){log.println("CREATE_FAILED\t"+label+"\t"+entry+"\t"+ex);}
        }
        if(f!=null)log.println("FUNCTION\t"+label+"\t"+entry+"\tbytes="+f.getBody().getNumAddresses()+"\tname="+f.getName());
        else log.println("UNRESOLVED\t"+label+"\t"+entry);
        return f;
    }

    @Override protected void run() throws Exception {
        String[] args=getScriptArgs();
        File outDir=new File(args.length>0?args[0]:"analysis/ghidra");outDir.mkdirs();
        PrintWriter log=new PrintWriter(new File(outDir,"seed-functions.txt"),"UTF-8");
        PrintWriter asm=new PrintWriter(new File(outDir,"seed-disassembly.txt"),"UTF-8");
        PrintWriter dec=new PrintWriter(new File(outDir,"seed-decompilations.txt"),"UTF-8");
        log.println("PROGRAM="+currentProgram.getName()+" IMAGE_BASE="+currentProgram.getImageBase());
        log.println("MODE=manual_rtti_seed_no_global_auto_analysis");
        Set<Function> selected=new LinkedHashSet<>();
        for(int i=0;i<seeds.length&&!monitor.isCancelled();i++){
            Address a=currentProgram.getImageBase().add(seeds[i]);
            Function f=ensureFunction(a,"RTTI_"+Long.toHexString(seeds[i]),log);
            if(f!=null)selected.add(f);
        }
        List<Function> wave=new ArrayList<>(selected);int added=0;
        for(Function src:wave){
            if(monitor.isCancelled()||selected.size()>=180)break;
            InstructionIterator it=currentProgram.getListing().getInstructions(src.getBody(),true);
            while(it.hasNext()&&selected.size()<180){
                Instruction ins=it.next();
                for(Reference ref:currentProgram.getReferenceManager().getReferencesFrom(ins.getAddress())){
                    RefType t=ref.getReferenceType();if(!t.isCall())continue;
                    Address target=ref.getToAddress();
                    if(currentProgram.getFunctionManager().getFunctionAt(target)!=null)continue;
                    Function f=ensureFunction(target,"CALL_"+target,log);
                    if(f!=null&&selected.add(f))added++;
                }
            }
        }
        log.println("SEED_COUNT="+seeds.length+" SELECTED_FUNCTIONS="+selected.size()+" CALL_TARGETS_ADDED="+added);
        for(Function f:selected){
            asm.println("\n===== "+f.getEntryPoint()+" "+f.getName()+" =====");
            InstructionIterator it=currentProgram.getListing().getInstructions(f.getBody(),true);int n=0;
            while(it.hasNext()&&n<500){Instruction ins=it.next();asm.println(ins.getAddress()+"\t"+ins);n++;}
        }
        DecompInterface decomp=new DecompInterface();decomp.openProgram(currentProgram);int emitted=0;
        for(Function f:selected){
            if(monitor.isCancelled()||emitted>=120)break;
            long size=f.getBody().getNumAddresses();
            if(size>0x8000){dec.println("\n// SKIPPED LARGE "+f.getEntryPoint()+" bytes="+size);continue;}
            DecompileResults r=decomp.decompileFunction(f,15,monitor);
            dec.println("\n// ===== "+f.getEntryPoint()+" "+f.getName()+" =====");
            if(r!=null&&r.decompileCompleted()&&r.getDecompiledFunction()!=null)dec.println(r.getDecompiledFunction().getC());
            else dec.println("// DECOMPILATION FAILED: "+(r==null?"no result":r.getErrorMessage()));
            emitted++;
        }
        dec.println("\n// emitted functions: "+emitted);
        decomp.dispose();log.close();asm.close();dec.close();
    }
}
