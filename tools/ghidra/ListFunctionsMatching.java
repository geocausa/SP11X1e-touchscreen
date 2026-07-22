// SPDX-License-Identifier: GPL-2.0
// List analyzed functions whose symbol names contain any requested fragment.
// @category SP11

import java.util.Locale;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;

public class ListFunctionsMatching extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] needles = getScriptArgs();
        if (needles.length == 0) {
            throw new IllegalArgumentException("expected name fragments");
        }

        int matches = 0;
        for (Function function :
             currentProgram.getFunctionManager().getFunctions(true)) {
            String name = function.getName(true);
            String folded = name.toLowerCase(Locale.ROOT);
            for (String needle : needles) {
                if (!folded.contains(needle.toLowerCase(Locale.ROOT))) {
                    continue;
                }
                println(function.getEntryPoint() + " " + name);
                matches++;
                break;
            }
        }
        println("Functions matched: " + matches);
    }
}
