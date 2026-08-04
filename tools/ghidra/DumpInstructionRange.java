// SPDX-License-Identifier: GPL-2.0
// Dump decoded instructions for an inclusive address range.
// @category SP11

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;

public class DumpInstructionRange extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 2) {
            throw new IllegalArgumentException("expected start and end addresses");
        }
        Address start = toAddr(Long.decode(args[0]));
        Address end = toAddr(Long.decode(args[1]));
        InstructionIterator it = currentProgram.getListing().getInstructions(start, true);
        int count = 0;
        while (it.hasNext() && !monitor.isCancelled()) {
            Instruction ins = it.next();
            if (ins.getAddress().compareTo(end) > 0) break;
            println(ins.getAddress() + "  " + ins + "  [" + ins.getFlowType() + "]");
            count++;
        }
        println("Instructions: " + count);
    }
}
