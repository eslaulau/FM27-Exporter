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
