// SPDX-License-Identifier: GPL-2.0
// List computed/indirect calls and jumps with their containing functions.
// @category SP11

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.symbol.FlowType;

public class ListComputedFlows extends GhidraScript {
    @Override
    protected void run() throws Exception {
        int calls = 0;
        int jumps = 0;
        InstructionIterator it = currentProgram.getListing().getInstructions(true);
        while (it.hasNext() && !monitor.isCancelled()) {
            Instruction ins = it.next();
            FlowType flow = ins.getFlowType();
            if (!flow.isComputed() || (!flow.isCall() && !flow.isJump())) {
                continue;
            }
            Function fn = getFunctionContaining(ins.getAddress());
            String owner = fn == null ? "<no function>" : fn.getName(true) + " @ " + fn.getEntryPoint();
            String kind = flow.isCall() ? "CALL" : "JUMP";
            println(kind + " " + ins.getAddress() + " " + ins + " | " + owner + " | " + flow);
            if (flow.isCall()) {
                calls++;
            }
            else {
                jumps++;
            }
        }
        println("Computed calls: " + calls);
        println("Computed jumps: " + jumps);
    }
}
