// SPDX-License-Identifier: GPL-2.0
// Print matching defined strings and the functions that reference them.
// @category SP11

import java.util.Locale;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class SearchStringXrefs extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] needles = getScriptArgs();
        if (needles.length == 0) {
            throw new IllegalArgumentException("expected one or more string fragments");
        }

        int strings = 0;
        int references = 0;
        DataIterator dataItems = currentProgram.getListing().getDefinedData(true);
        while (dataItems.hasNext() && !monitor.isCancelled()) {
            Data data = dataItems.next();
            if (!data.hasStringValue()) {
                continue;
            }
            String value = String.valueOf(data.getValue());
            String folded = value.toLowerCase(Locale.ROOT);
            boolean match = false;
            for (String needle : needles) {
                if (folded.contains(needle.toLowerCase(Locale.ROOT))) {
                    match = true;
                    break;
                }
            }
            if (!match) {
                continue;
            }

            strings++;
            println("STRING " + data.getAddress() + " " + value);
            for (Reference reference : getReferencesTo(data.getAddress())) {
                references++;
                Function function = getFunctionContaining(reference.getFromAddress());
                println("  XREF " + reference.getFromAddress() + " " +
                    (function == null ? "<no function>" :
                     function.getName(true) + " @ " + function.getEntryPoint()));
            }
        }
        println("Matching strings: " + strings);
        println("References: " + references);
    }
}
