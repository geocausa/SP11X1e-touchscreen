// SPDX-License-Identifier: GPL-2.0
// Search an analyzed Ghidra program's decompiler output for exact text.
// @category SP11

import java.io.File;
import java.io.PrintWriter;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;

public class SearchDecompiledText extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            throw new IllegalArgumentException(
                "expected output path followed by one or more search strings"
            );
        }

        DecompInterface decompiler = new DecompInterface();
        decompiler.toggleCCode(true);
        decompiler.toggleSyntaxTree(false);
        if (!decompiler.openProgram(currentProgram)) {
            throw new IllegalStateException("decompiler could not open program");
        }

        int searched = 0;
        int matched = 0;
        try (PrintWriter out = new PrintWriter(new File(args[0]), "UTF-8")) {
            for (Function function : currentProgram.getFunctionManager().getFunctions(true)) {
                if (monitor.isCancelled() || function.isExternal()) {
                    continue;
                }
                searched++;
                // Broad provenance scans must not stall for a minute on each
                // pathological runtime/helper function. Five seconds is ample
                // for the processor policy functions and failures are skipped.
                DecompileResults result = decompiler.decompileFunction(
                    function, 5, monitor
                );
                if (!result.decompileCompleted() ||
                    result.getDecompiledFunction() == null) {
                    continue;
                }
                String code = result.getDecompiledFunction().getC();
                boolean found = false;
                for (int index = 1; index < args.length; index++) {
                    if (code.contains(args[index])) {
                        found = true;
                        break;
                    }
                }
                if (found) {
                    matched++;
                    out.printf("===== %s @ %s =====%n", function.getName(true),
                               function.getEntryPoint());
                    out.println(code);
                    out.println();
                }
            }
            out.printf("Functions searched: %d%nFunctions matched: %d%n",
                       searched, matched);
        } finally {
            decompiler.dispose();
        }
    }
}
