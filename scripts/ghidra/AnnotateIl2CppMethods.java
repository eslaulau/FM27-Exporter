// Add IL2CPP method names to GameAssembly.dll in Ghidra without full auto-analysis.
import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.PrintWriter;
import java.util.HashSet;
import java.util.Set;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.listing.Function;

public class AnnotateIl2CppMethods extends GhidraScript {
    private String safeName(String name) {
        String n = name.replaceAll("[^A-Za-z0-9_$@.]", "_");
        if (n.length() > 180) n = n.substring(0, 180);
        return "IL2CPP_" + n;
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            println("Usage: AnnotateIl2CppMethods.java <method-map.tsv> <output-dir>");
            return;
        }
        File mapFile = new File(args[0]);
        File outDir = new File(args[1]);
        outDir.mkdirs();
        PrintWriter report = new PrintWriter(new File(outDir, "gameassembly-il2cpp-annotation.txt"), "UTF-8");
        report.println("PROGRAM=" + currentProgram.getName());
        report.println("IMAGE_BASE=" + currentProgram.getImageBase());
        report.println("MAP_FILE=" + mapFile.getAbsolutePath());

        int rows = 0, executable = 0, labels = 0, existingFunctions = 0, missing = 0;
        Set<String> seen = new HashSet<>();
        try (BufferedReader reader = new BufferedReader(new FileReader(mapFile))) {
            String line;
            while ((line = reader.readLine()) != null && !monitor.isCancelled()) {
                String[] parts = line.split("\t", 4);
                if (parts.length < 2) continue;
                rows++;
                long rva;
                try {
                    String raw = parts[0].trim();
                    if (raw.startsWith("0x") || raw.startsWith("0X")) raw = raw.substring(2);
                    rva = Long.parseUnsignedLong(raw, 16);
                } catch (Exception ex) {
                    report.println("BAD_ADDRESS\t" + parts[0]);
                    continue;
                }
                Address addr = currentProgram.getImageBase().add(rva);
                MemoryBlock block = currentProgram.getMemory().getBlock(addr);
                if (block == null || !block.isExecute()) {
                    missing++;
                    continue;
                }
                executable++;
                String name = safeName(parts[1]);
                String key = addr.toString() + "\t" + name;
                if (!seen.add(key)) continue;
                try {
                    createLabel(addr, name, true, SourceType.IMPORTED);
                    labels++;
                    if (parts.length >= 3 && !parts[2].isEmpty()) {
                        setEOLComment(addr, parts[2]);
                    }
                    Function f = currentProgram.getFunctionManager().getFunctionAt(addr);
                    if (f != null) existingFunctions++;
                } catch (Exception ex) {
                    report.println("LABEL_ERROR\t" + addr + "\t" + name + "\t" + ex.getMessage());
                }
            }
        }
        report.println("MAP_ROWS=" + rows);
        report.println("EXECUTABLE_METHOD_ROWS=" + executable);
        report.println("LABELS_CREATED=" + labels);
        report.println("ROWS_WITH_EXISTING_FUNCTION=" + existingFunctions);
        report.println("SKIPPED_NON_EXECUTABLE_OR_MISSING=" + missing);
        report.close();
    }
}
