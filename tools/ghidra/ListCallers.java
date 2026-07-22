// SPDX-License-Identifier: GPL-2.0
// List direct code references to each address supplied on the command line.
// @category SP11

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.ReferenceManager;

public class ListCallers extends GhidraScript {
    @Override
    public void run() throws Exception {
        FunctionManager functions = currentProgram.getFunctionManager();
        ReferenceManager references = currentProgram.getReferenceManager();

        for (String argument : getScriptArgs()) {
            Address target = toAddr(Long.decode(argument));
            println("TARGET " + target);
            ReferenceIterator iterator = references.getReferencesTo(target);
            while (iterator.hasNext()) {
                Reference reference = iterator.next();
                if (!reference.getReferenceType().isCall()) {
                    continue;
                }
                Function caller = functions.getFunctionContaining(reference.getFromAddress());
                println("  " + reference.getFromAddress() + " " +
                    (caller == null ? "<no-function>" :
                        caller.getName() + " @" + caller.getEntryPoint()));
            }
        }
    }
}
