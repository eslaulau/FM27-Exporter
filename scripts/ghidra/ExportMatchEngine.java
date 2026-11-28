// Export native FM27 match-engine symbols, RTTI cross-references and selected decompilations.
import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Set;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.DataType;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;

public class ExportMatchEngine extends GhidraScript {
    private boolean interesting(String value) {
        String s = value.toLowerCase(Locale.ROOT);
        String[] terms = {
            "match_decision_provider", "match_movement_director",
            "match_weights_provider", "match_oop_scoring_provider",
            "match_pressing_factory", "match_pressing_manager",
            "tactic_info", "tactical_role", "tactic_loader",
            "match_manager", "match_player", "match::play",
            "setup_basic_tactical_positions", "oop_attributes_scoring",
            "oop_pitch_proximity_scores", "game_match",
            "pressing", "movement", "decision", "scoring"
        };
        for (String term : terms) if (s.contains(term)) return true;
        return false;
    }

    @Override
    protected void run() throws Exception {
        File outDir = new File(getScriptArgs()[0]);
        outDir.mkdirs();
        PrintWriter symbols = new PrintWriter(new File(outDir, "ghidra-symbols.txt"), "UTF-8");
        PrintWriter xrefs = new PrintWriter(new File(outDir, "ghidra-engine-xrefs.txt"), "UTF-8");
        PrintWriter decompOut = new PrintWriter(new File(outDir, "ghidra-engine-decompilations.txt"), "UTF-8");

        symbols.println("Program: " + currentProgram.getName());
        symbols.println("Image base: " + currentProgram.getImageBase());
        symbols.println("Pointer size: " + currentProgram.getDefaultPointerSize());

        Set<Function> selected = new LinkedHashSet<>();

        // RTTI-derived virtual method entry RVAs from the matched
        // game_plugin.dll build 27.1.1+2511875. These are independent of
        // symbol names and seed direct decompilation of the simulation core.
        long[] vtableRvas = {
            // MATCH_MOVEMENT_DIRECTOR (15 slots)
            0x1bc240L, 0x4c2fd10L, 0x42d64e0L, 0x42d64f0L, 0x42d6500L,
            0x42d6510L, 0x42d6520L, 0x4993230L, 0x42d6530L, 0x42d6540L,
            0x42d6550L, 0x42d6560L, 0x42d6570L, 0x42d6580L, 0x42d6590L,
            // MATCH_WEIGHTS_PROVIDER
            0x4c2a2f0L,
            // MATCH_OOP_SCORING_PROVIDER
            0x4c2da40L,
            // MATCH_PRESSING_FACTORY
            0x4576270L,
            // MATCH_PRESSING_MANAGER_DEFENDER / MIDFIELDER / ATTACKER
            0x1c0160L, 0x47fa990L, 0x1c0190L, 0x4996d50L, 0x1c01c0L, 0x4997910L,
            // TACTIC_INFO
            0x27d3f0L, 0x27d420L, 0x27d430L,
            // TACTICAL_ROLE
            0x323f70L, 0x323fa0L, 0x121f990L, 0x121f9a0L, 0x121f980L,
            0x226590L, 0x2265a0L, 0x2265b0L, 0x121f9b0L, 0x121f970L,
            // MATCH_MANAGER
            0x153ce0L, 0x4c70L, 0x26f9700L, 0x16b030L, 0xe4f800L,
            0xe4f810L, 0x11d0L, 0xe4f820L, 0xd7be0L, 0xd7c80L,
            0x1511a0L, 0x1327f0L, 0x132800L, 0x270c1d0L,
            // MATCH_PLAYER
            0x2b087a0L, 0x1b6640L, 0x2b02030L, 0x183820L, 0x19d0L,
            0x2b08890L, 0x4956e00L, 0x2b08450L, 0xd7be0L, 0xd7c80L,
            0x1511a0L, 0xfa660L, 0xfa7d0L
        };
        for (long rva : vtableRvas) {
            var entry = currentProgram.getImageBase().add(rva);
            Function f = currentProgram.getFunctionManager().getFunctionAt(entry);
            if (f == null) f = currentProgram.getFunctionManager().getFunctionContaining(entry);
            symbols.println("RTTI_VTABLE_ENTRY\\tRVA=0x" + Long.toHexString(rva) +
                "\\tADDRESS=" + entry + "\\tFUNCTION=" + (f == null ? "<unresolved>" : f.getName()));
            if (f != null) selected.add(f);
        }
        SymbolIterator si = currentProgram.getSymbolTable().getAllSymbols(true);
        while (si.hasNext() && !monitor.isCancelled()) {
            Symbol sym = si.next();
            String n = sym.getName();
            if (interesting(n)) {
                symbols.println(sym.getAddress() + "\t" + sym.getSymbolType() + "\t" + n);
                Function f = currentProgram.getFunctionManager().getFunctionAt(sym.getAddress());
                if (f == null) f = currentProgram.getFunctionManager().getFunctionContaining(sym.getAddress());
                if (f != null) selected.add(f);
            }
        }

        int matchedStrings = 0;
        Data data = null;
        for (var it = currentProgram.getListing().getDefinedData(true); it.hasNext() && !monitor.isCancelled();) {
            data = it.next();
            Object value = data.getValue();
            if (value == null) continue;
            String str = value.toString();
            if (!interesting(str)) continue;
            matchedStrings++;
            xrefs.println("STRING\t" + data.getAddress() + "\t" + str.replace("\n", " "));
            ReferenceIterator refs = currentProgram.getReferenceManager().getReferencesTo(data.getAddress());
            int refCount = 0;
            while (refs.hasNext() && refCount < 100) {
                Reference ref = refs.next();
                Function f = currentProgram.getFunctionManager().getFunctionContaining(ref.getFromAddress());
                xrefs.println("  REF\t" + ref.getFromAddress() + "\t" +
                    (f == null ? "<no-function>" : f.getEntryPoint() + "\t" + f.getName()));
                if (f != null) selected.add(f);
                refCount++;
            }
        }
        symbols.println("Matched interesting strings: " + matchedStrings);
        symbols.println("Selected functions: " + selected.size());

        // If useful names are available (for example from a matching PDB), collect named functions too.
        FunctionIterator fi = currentProgram.getFunctionManager().getFunctions(true);
        int named = 0;
        while (fi.hasNext() && named < 5000 && !monitor.isCancelled()) {
            Function f = fi.next();
            String n = f.getName();
            if (interesting(n)) {
                selected.add(f);
                symbols.println("FUNCTION\t" + f.getEntryPoint() + "\t" + n +
                    "\t" + f.getBody().getNumAddresses() + " bytes");
                named++;
            }
        }

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        int emitted = 0;
        for (Function f : selected) {
            if (monitor.isCancelled() || emitted >= 250) break;
            DecompileResults result = decomp.decompileFunction(f, 45, monitor);
            decompOut.println("\n// ===== " + f.getEntryPoint() + " " + f.getName() + " =====");
            if (result != null && result.decompileCompleted() && result.getDecompiledFunction() != null) {
                decompOut.println(result.getDecompiledFunction().getC());
            } else {
                decompOut.println("// DECOMPILATION FAILED: " +
                    (result == null ? "no result" : result.getErrorMessage()));
            }
            emitted++;
        }
        decompOut.println("\n// emitted functions: " + emitted);
        decomp.dispose();
        symbols.close();
        xrefs.close();
        decompOut.close();
    }
}
