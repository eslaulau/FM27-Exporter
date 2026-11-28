// RTTI-discovered native match-engine class vtables -> bounded function bodies.
import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
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
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.SourceType;

public class ExportNativeRttiTargets extends GhidraScript {
    private static final int MAX_TYPES = 160;
    private static final int MAX_SLOTS_PER_TABLE = 48;
    private static final long WINDOW = 0x6000L;
    private static final long MAX_DECOMPILE_BYTES = 0x18000L;

    private static final String TARGET =
        "(?i)((^|::)(MATCH_MOVEMENT_DIRECTOR|MATCH_PRESSING_MANAGER_(ATTACKER|DEFENDER|MIDFIELDER)|" +
        "MATCH_WEIGHTS_PROVIDER|MATCH_OOP_SCORING_PROVIDER|GAME_MATCH_MANAGER|MATCH_MANAGER|" +
        "MATCH_PLAYER|MATCH_PLAYER_RATINGS_MANAGER|GAME_TACTIC_INFO|TACTIC_INFO|" +
        "TACTICAL_ROLE|PLAYER_INSTRUCTIONS_MANAGER|TACTICS_MANAGER|TACTIC_LOADER|" +
        "MATCH_SYSTEM|MATCH_ANALYST|MATCH_MOMENTUM_MANAGER|VIEWABLE_MATCH_CLIENT|" +
        "SHOT_ZONE_AREA_INFO|ADVANCED_SHOT_ZONE_AREA_INFO|TACTICS_CREATOR_ARRAY|" +
        "PREPARED_TACTICS_CREATOR_ARRAY|MATCH_TEAM_SELECTOR|PRE_MATCH_TEAM_SELECTOR)$|" +
        "MATCH_OOP_SCORING_PROVIDER::(OOP_ATTRIBUTE|PITCH_PROXIMITY_SCORE)$|" +
        "DYNAMIC_POSITION_SCORES|DYNAMIC_SCORES)";

    private static class Table {
        String type;
        long vtableRva;
        String slots;
    }

    private String safe(String value) {
        String s = value.replaceAll("[^A-Za-z0-9_$]", "_");
        if (s.length() > 90) s = s.substring(0, 90);
        return s;
    }

    private AddressSet decodedBody(Address entry, AddressSetView decoded) {
        AddressSet body = new AddressSet();
        InstructionIterator it = currentProgram.getListing().getInstructions(decoded, true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            body.add(ins.getMinAddress(), ins.getMaxAddress());
        }
        return body;
    }

    private Function analyzeEntry(long rva, String label, PrintWriter summary,
                                   PrintWriter asm, DecompInterface decomp) throws Exception {
        Address entry = currentProgram.getImageBase().add(rva);
        MemoryBlock block = currentProgram.getMemory().getBlock(entry);
        if (block == null || !block.isExecute()) {
            summary.println("SKIP_NON_EXECUTABLE\t" + label + "\t" + entry);
            return null;
        }

        Function existing = currentProgram.getFunctionManager().getFunctionAt(entry);
        if (existing != null && existing.getBody().getNumAddresses() > 1) {
            summary.println("REUSE_EXISTING\t" + label + "\t" + entry +
                "\tbytes=" + existing.getBody().getNumAddresses());
            return existing;
        }
        if (existing != null) {
            currentProgram.getFunctionManager().removeFunction(entry);
        }

        Address end = entry.add(WINDOW);
        if (end.compareTo(block.getEnd()) > 0) end = block.getEnd();
        AddressSetView bounded = new AddressSet(entry, end);
        DisassembleCommand command = new DisassembleCommand(entry, bounded, true);
        boolean ok = command.applyTo(currentProgram, monitor);
        AddressSetView decoded = command.getDisassembledAddressSet();
        AddressSet body = decodedBody(entry, decoded);
        long bodyBytes = body.getNumAddresses();
        if (!body.contains(entry) || bodyBytes < 5) {
            summary.println("DECODE_TOO_SMALL\t" + label + "\t" + entry +
                "\tok=" + ok + "\tbytes=" + bodyBytes +
                "\tstatus=" + command.getStatusMsg());
            return null;
        }

        // Preserve pre-existing functions that overlap a decoded window.
        java.util.Iterator<Function> overlapIt =
            currentProgram.getFunctionManager().getFunctionsOverlapping(body);
        List<Function> overlaps = new ArrayList<>();
        while (overlapIt.hasNext()) {
            Function f = overlapIt.next();
            if (!f.getEntryPoint().equals(entry)) overlaps.add(f);
        }
        for (Function f : overlaps) {
            body.delete(f.getBody());
        }
        if (!body.contains(entry)) {
            summary.println("ENTRY_REMOVED_BY_OVERLAP\t" + label + "\t" + entry);
            return null;
        }

        Function function = currentProgram.getFunctionManager().createFunction(
            label, entry, body, SourceType.ANALYSIS);
        if (function == null) {
            summary.println("CREATE_FUNCTION_NULL\t" + label + "\t" + entry);
            return null;
        }

        int n = 0;
        asm.println("\n===== " + entry + " " + label +
            " BODY_BYTES=" + body.getNumAddresses() + " =====");
        InstructionIterator it = currentProgram.getListing().getInstructions(function.getBody(), true);
        while (it.hasNext() && n < 4000) {
            Instruction ins = it.next();
            asm.println(ins.getAddress() + "\t" + ins);
            n++;
        }
        asm.println("// instructions=" + n);

        summary.println("FUNCTION\t" + label + "\t" + entry +
            "\tRVA=0x" + Long.toHexString(rva) +
            "\tbytes=" + body.getNumAddresses() + "\tinstructions=" + n);

        if (body.getNumAddresses() <= MAX_DECOMPILE_BYTES) {
            DecompileResults result = decomp.decompileFunction(function, 25, monitor);
            decLine(result, function, label);
        }
        return function;
    }

    private PrintWriter dec;
    private void decLine(DecompileResults result, Function f, String label) {
        dec.println("\n// ===== " + f.getEntryPoint() + " " + label + " =====");
        if (result != null && result.decompileCompleted() && result.getDecompiledFunction() != null) {
            dec.println(result.getDecompiledFunction().getC());
        } else {
            dec.println("// DECOMPILE_FAILED: " +
                (result == null ? "no result" : result.getErrorMessage()));
        }
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("Usage: ExportNativeRttiTargets.java <native-rtti-vtables.tsv> <output-dir>");
            return;
        }
        File tableFile = new File(args[0]);
        File outDir = new File(args[1]);
        outDir.mkdirs();

        PrintWriter summary = new PrintWriter(new File(outDir, "native-rtti-target-summary.txt"), "UTF-8");
        PrintWriter asm = new PrintWriter(new File(outDir, "native-rtti-target-disassembly.txt"), "UTF-8");
        dec = new PrintWriter(new File(outDir, "native-rtti-target-decompilations.txt"), "UTF-8");
        summary.println("PROGRAM=" + currentProgram.getName());
        summary.println("IMAGE_BASE=" + currentProgram.getImageBase());
        summary.println("RTTI_TABLE_FILE=" + tableFile.getAbsolutePath());

        Map<Long, String> targets = new LinkedHashMap<>();
        int matchedTables = 0;
        try (BufferedReader reader = new BufferedReader(new FileReader(tableFile))) {
            String line = reader.readLine(); // header
            while ((line = reader.readLine()) != null && matchedTables < MAX_TYPES) {
                String[] p = line.split("\t", 6);
                if (p.length < 6 || !java.util.regex.Pattern.compile(TARGET).matcher(p[0]).find()) continue;
                matchedTables++;
                String type = p[0];
                String vtable = p[3];
                String[] slots = p[5].split(",");
                for (int i = 0; i < slots.length && i < MAX_SLOTS_PER_TABLE; i++) {
                    String raw = slots[i].trim();
                    if (raw.isEmpty()) continue;
                    long rva;
                    try {
                        if (raw.startsWith("0x") || raw.startsWith("0X")) raw = raw.substring(2);
                        rva = Long.parseUnsignedLong(raw, 16);
                    } catch (Exception ex) { continue; }
                    targets.putIfAbsent(rva, type + "_VT_" + vtable + "_SLOT_" + i);
                }
            }
        }

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        int analyzed = 0;
        for (Map.Entry<Long, String> e : targets.entrySet()) {
            if (monitor.isCancelled()) break;
            Function f = analyzeEntry(e.getKey(), e.getValue(), summary, asm, decomp);
            if (f != null) analyzed++;
        }
        summary.println("MATCHED_RTTI_TABLES=" + matchedTables);
        summary.println("UNIQUE_SLOT_TARGETS=" + targets.size());
        summary.println("ANALYZED_FUNCTIONS=" + analyzed);
        dec.println("\n// ANALYZED_FUNCTIONS=" + analyzed);
        decomp.dispose();
        summary.close();
        asm.close();
        dec.close();
    }
}
