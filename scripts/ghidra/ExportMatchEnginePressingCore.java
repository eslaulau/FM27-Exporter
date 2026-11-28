// Bounded flow disassembly for the three MATCH_PRESSING_MANAGER implementations.
// This pass is separate from the no-analysis seed inventory. It creates real
// instruction bodies in bounded executable windows, then follows direct calls.
import java.io.File;
import java.io.PrintWriter;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.address.AddressSetView;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.RefType;

public class ExportMatchEnginePressingCore extends GhidraScript {
    private static final long WINDOW = 0x20000L;
    private static final int MAX_CALL_TARGETS = 32;
    private static final long MAX_DECOMPILE_BYTES = 0x20000L;

    private final Map<Long, String> seeds = new LinkedHashMap<>();
    {
        seeds.put(0x47fa990L, "MATCH_PRESSING_MANAGER_IMPL_A");
        seeds.put(0x4996d50L, "MATCH_PRESSING_MANAGER_IMPL_B");
        seeds.put(0x4997910L, "MATCH_PRESSING_MANAGER_IMPL_C");
        // Direct call targets recovered from the first decompilation pass.
        seeds.put(0x4996a50L, "PRESSING_HELPER_FROM_IMPL_B_1");
        seeds.put(0x4998130L, "PRESSING_HELPER_FROM_IMPL_B_2");
    }

    private Function flowDisassemble(long rva, String label, PrintWriter log) throws Exception {
        Address entry = currentProgram.getImageBase().add(rva);
        MemoryBlock block = currentProgram.getMemory().getBlock(entry);
        if (block == null || !block.isExecute()) {
            log.println("SKIP_NON_EXECUTABLE\t" + label + "\t" + entry);
            return null;
        }
        Address end = entry.add(WINDOW);
        AddressSetView bounded = new AddressSet(entry, end);
        DisassembleCommand command = new DisassembleCommand(entry, bounded, true);
        boolean ok = command.applyTo(currentProgram, monitor);
        AddressSetView decoded = command.getDisassembledAddressSet();
        log.println("DISASSEMBLY\t" + label + "\t" + entry +
            "\tok=" + ok + "\tdecoded_bytes=" + decoded.getNumAddresses() +
            "\tstatus=" + command.getStatusMsg());

        Function f = currentProgram.getFunctionManager().getFunctionAt(entry);
        if (f == null) {
            try {
                f = createFunction(entry, label);
            } catch (Exception ex) {
                log.println("CREATE_FUNCTION_FAILED\t" + label + "\t" + ex);
                return null;
            }
        }
        if (f != null) {
            log.println("FUNCTION\t" + label + "\t" + f.getEntryPoint() +
                "\tbody_bytes=" + f.getBody().getNumAddresses() +
                "\tname=" + f.getName());
        }
        return f;
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File outDir = new File(args.length > 0 ? args[0] : "analysis/pressing-core");
        outDir.mkdirs();
        PrintWriter summary = new PrintWriter(new File(outDir, "pressing-core-summary.txt"), "UTF-8");
        PrintWriter asm = new PrintWriter(new File(outDir, "pressing-core-disassembly.txt"), "UTF-8");
        PrintWriter dec = new PrintWriter(new File(outDir, "pressing-core-decompilations.txt"), "UTF-8");

        summary.println("PROGRAM=" + currentProgram.getName() +
            "\tIMAGE_BASE=" + currentProgram.getImageBase());
        summary.println("MODE=bounded_flow_disassembly_then_direct_call_expansion");
        Map<Long, Function> selected = new LinkedHashMap<>();
        for (Map.Entry<Long, String> e : seeds.entrySet()) {
            if (monitor.isCancelled()) break;
            Function f = flowDisassemble(e.getKey(), e.getValue(), summary);
            if (f != null) selected.put(e.getKey(), f);
        }

        Set<Long> discovered = new LinkedHashSet<>();
        for (Map.Entry<Long, Function> e : selected.entrySet()) {
            Function f = e.getValue();
            InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
            while (it.hasNext() && discovered.size() < MAX_CALL_TARGETS) {
                Instruction ins = it.next();
                for (Reference ref : currentProgram.getReferenceManager().getReferencesFrom(ins.getAddress())) {
                    RefType type = ref.getReferenceType();
                    if (!type.isCall()) continue;
                    Address target = ref.getToAddress();
                    long rva;
                    try {
                        rva = target.subtract(currentProgram.getImageBase());
                    } catch (Exception ex) {
                        continue;
                    }
                    if (rva < 0 || selected.containsKey(rva) || discovered.contains(rva)) continue;
                    MemoryBlock targetBlock = currentProgram.getMemory().getBlock(target);
                    if (targetBlock == null || !targetBlock.isExecute()) continue;
                    discovered.add(rva);
                }
            }
        }

        int index = 0;
        for (long rva : discovered) {
            if (monitor.isCancelled() || index >= MAX_CALL_TARGETS) break;
            Function f = flowDisassemble(rva, "PRESSING_DIRECT_CALL_" + Long.toHexString(rva), summary);
            if (f != null) selected.put(rva, f);
            index++;
        }

        summary.println("PRIMARY_SEEDS=" + seeds.size());
        summary.println("SELECTED_FUNCTIONS=" + selected.size());
        summary.println("DIRECT_CALL_TARGETS_DISCOVERED=" + discovered.size());

        for (Function f : selected.values()) {
            long bodySize = f.getBody().getNumAddresses();
            asm.println("\n===== " + f.getEntryPoint() + " " + f.getName() +
                " BODY_BYTES=" + bodySize + " =====");
            InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
            int count = 0;
            while (it.hasNext() && count < 6000) {
                Instruction ins = it.next();
                asm.println(ins.getAddress() + "\t" + ins);
                count++;
            }
            asm.println("// instruction_count=" + count);
        }

        ghidra.app.decompiler.DecompInterface decomp =
            new ghidra.app.decompiler.DecompInterface();
        decomp.openProgram(currentProgram);
        int emitted = 0;
        for (Function f : selected.values()) {
            if (monitor.isCancelled()) break;
            if (f.getBody().getNumAddresses() > MAX_DECOMPILE_BYTES) {
                dec.println("\n// SKIPPED_OVERSIZE " + f.getEntryPoint() +
                    " bytes=" + f.getBody().getNumAddresses());
                continue;
            }
            ghidra.app.decompiler.DecompileResults result =
                decomp.decompileFunction(f, 30, monitor);
            dec.println("\n// ===== " + f.getEntryPoint() + " " + f.getName() + " =====");
            if (result != null && result.decompileCompleted() &&
                result.getDecompiledFunction() != null) {
                dec.println(result.getDecompiledFunction().getC());
            } else {
                dec.println("// DECOMPILATION_FAILED: " +
                    (result == null ? "no result" : result.getErrorMessage()));
            }
            emitted++;
        }
        dec.println("\n// emitted functions: " + emitted);
        summary.println("DECOMPILED_FUNCTIONS=" + emitted);
        decomp.dispose();
        summary.close();
        asm.close();
        dec.close();
    }
}
