// Bounded disassembly/decompilation of tactic-data and match-interface bridge methods.
import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.PrintWriter;
import java.util.LinkedHashMap;
import java.util.Map;

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

public class DecompileTacticBridgeMethods extends GhidraScript {
    private static final long WINDOW = 0x1800L;
    private static final long MAX_BODY = 0x18000L;

    private static class Method {
        long rva;
        String name;
        String signature;
    }

    private String safeName(String name) {
        String s = name.replaceAll("[^A-Za-z0-9_$]", "_");
        if (s.length() > 160) s = s.substring(0, 160);
        return "IL2CPP_" + s;
    }

    private Function ensureFunction(Method method, PrintWriter summary,
                                    PrintWriter asm, PrintWriter dec,
                                    DecompInterface decomp) throws Exception {
        Address entry = currentProgram.getImageBase().add(method.rva);
        MemoryBlock block = currentProgram.getMemory().getBlock(entry);
        if (block == null || !block.isExecute()) {
            summary.println("SKIP_NON_EXECUTABLE\t" + method.name + "\t" + entry);
            return null;
        }

        String label = safeName(method.name.replace("$$", "__"));
        createLabel(entry, label, true, SourceType.IMPORTED);
        Function f = currentProgram.getFunctionManager().getFunctionAt(entry);

        if (f == null || f.getBody().getNumAddresses() <= 1) {
            if (f != null) currentProgram.getFunctionManager().removeFunction(entry);
            Address end = entry.add(WINDOW);
            if (end.compareTo(block.getEnd()) > 0) end = block.getEnd();
            AddressSetView bounded = new AddressSet(entry, end);
            DisassembleCommand command = new DisassembleCommand(entry, bounded, true);
            command.applyTo(currentProgram, monitor);
            AddressSetView decoded = command.getDisassembledAddressSet();
            AddressSet body = new AddressSet();
            InstructionIterator it = currentProgram.getListing().getInstructions(decoded, true);
            int instructionCount = 0;
            while (it.hasNext()) {
                Instruction ins = it.next();
                body.add(ins.getMinAddress(), ins.getMaxAddress());
                instructionCount++;
            }
            if (!body.contains(entry) || body.getNumAddresses() < 5) {
                summary.println("DECODE_TOO_SMALL\t" + method.name +
                    "\t" + entry + "\tbytes=" + body.getNumAddresses());
                return null;
            }
            java.util.Iterator<Function> overlapIt =
                currentProgram.getFunctionManager().getFunctionsOverlapping(body);
            java.util.List<Function> overlaps = new java.util.ArrayList<>();
            while (overlapIt.hasNext()) {
                Function overlap = overlapIt.next();
                if (!overlap.getEntryPoint().equals(entry)) overlaps.add(overlap);
            }
            for (Function overlap : overlaps) body.delete(overlap.getBody());
            if (!body.contains(entry)) return null;
            f = currentProgram.getFunctionManager().createFunction(
                label, entry, body, SourceType.ANALYSIS);
            if (f == null) return null;
        }

        summary.println("FUNCTION\t" + method.name +
            "\t" + entry +
            "\tRVA=0x" + Long.toHexString(method.rva) +
            "\tbytes=" + f.getBody().getNumAddresses());
        summary.println("SIGNATURE\t" + method.signature);

        if (f.getBody().getNumAddresses() > MAX_BODY) {
            dec.println("\n// SKIPPED_OVERSIZE " + entry + " " + method.name);
            return f;
        }

        asm.println("\n===== " + entry + " " + method.name +
            " BODY_BYTES=" + f.getBody().getNumAddresses() + " =====");
        InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
        int n = 0;
        while (it.hasNext() && n < 2500) {
            Instruction ins = it.next();
            asm.println(ins.getAddress() + "\t" + ins);
            n++;
        }

        DecompileResults result = decomp.decompileFunction(f, 20, monitor);
        dec.println("\n// ===== " + entry + " " + method.name + " =====");
        dec.println("// " + method.signature);
        if (result != null && result.decompileCompleted() && result.getDecompiledFunction() != null) {
            dec.println(result.getDecompiledFunction().getC());
        } else {
            dec.println("// DECOMPILE_FAILED: " +
                (result == null ? "no result" : result.getErrorMessage()));
        }
        return f;
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("Usage: DecompileTacticBridgeMethods.java <methods.tsv> <output-dir>");
            return;
        }
        File mapFile = new File(args[0]);
        File outDir = new File(args[1]);
        outDir.mkdirs();
        PrintWriter summary = new PrintWriter(new File(outDir, "tactic-bridge-summary.txt"), "UTF-8");
        PrintWriter asm = new PrintWriter(new File(outDir, "tactic-bridge-disassembly.txt"), "UTF-8");
        PrintWriter dec = new PrintWriter(new File(outDir, "tactic-bridge-decompilations.txt"), "UTF-8");

        summary.println("PROGRAM=" + currentProgram.getName());
        summary.println("IMAGE_BASE=" + currentProgram.getImageBase());

        Map<Long, Method> methods = new LinkedHashMap<>();
        try (BufferedReader reader = new BufferedReader(new FileReader(mapFile))) {
            String line;
            while ((line = reader.readLine()) != null) {
                String[] p = line.split("\t", 4);
                if (p.length < 3) continue;
                String raw = p[0].trim();
                if (raw.startsWith("0x") || raw.startsWith("0X")) raw = raw.substring(2);
                long rva;
                try { rva = Long.parseUnsignedLong(raw, 16); }
                catch (Exception ex) { continue; }
                if (!methods.containsKey(rva)) {
                    Method m = new Method();
                    m.rva = rva;
                    m.name = p[1];
                    m.signature = p[2];
                    methods.put(rva, m);
                }
            }
        }

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        int analyzed = 0;
        for (Method method : methods.values()) {
            if (monitor.isCancelled()) break;
            if (ensureFunction(method, summary, asm, dec, decomp) != null) analyzed++;
        }
        summary.println("METHOD_ENTRIES=" + methods.size());
        summary.println("ANALYZED_FUNCTIONS=" + analyzed);
        dec.println("\n// ANALYZED_FUNCTIONS=" + analyzed);
        decomp.dispose();
        summary.close();
        asm.close();
        dec.close();
    }
}
