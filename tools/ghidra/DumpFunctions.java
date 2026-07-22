// SPDX-License-Identifier: GPL-2.0
// Decompile the functions containing requested addresses.
// @category SP11

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class DumpFunctions extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length == 0) {
            throw new IllegalArgumentException("expected one or more addresses");
        }

        DecompInterface decompiler = new DecompInterface();
        decompiler.toggleCCode(true);
        decompiler.toggleSyntaxTree(false);
        if (!decompiler.openProgram(currentProgram)) {
            throw new IllegalStateException("decompiler could not open program");
        }
        try {
            for (String arg : args) {
                Address address = toAddr(Long.decode(arg));
                Function function = getFunctionContaining(address);
                if (function == null) {
                    println("NO FUNCTION " + address);
                    continue;
                }
                println("===== " + function.getName(true) + " @ " +
                    function.getEntryPoint() + " (query " + address + ") =====");
                DecompileResults result = decompiler.decompileFunction(
                    function, 15, monitor
                );
                if (result.decompileCompleted() &&
                    result.getDecompiledFunction() != null) {
                    println(result.getDecompiledFunction().getC());
                } else {
                    println("DECOMPILE FAILED: " + result.getErrorMessage());
                }
            }
        } finally {
            decompiler.dispose();
        }
    }
}
