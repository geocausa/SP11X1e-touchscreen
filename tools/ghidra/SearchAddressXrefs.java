// SPDX-License-Identifier: GPL-2.0
// Print references to requested addresses and the containing source functions.
// @category SP11

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class SearchAddressXrefs extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length == 0) {
            throw new IllegalArgumentException("expected one or more addresses");
        }

        for (String arg : args) {
            Address target = toAddr(Long.decode(arg));
            int count = 0;
            println("TARGET " + target);
            for (Reference reference : getReferencesTo(target)) {
                Function function = getFunctionContaining(reference.getFromAddress());
                println("  XREF " + reference.getFromAddress() + " " +
                    reference.getReferenceType() + " " +
                    (function == null ? "<no function>" :
                     function.getName(true) + " @ " + function.getEntryPoint()));
                count++;
            }
            println("  References: " + count);
        }
    }
}
