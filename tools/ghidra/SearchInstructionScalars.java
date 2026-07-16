// SPDX-License-Identifier: GPL-2.0
// Find functions whose instructions contain all requested scalar operands.
// @category SP11

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.scalar.Scalar;

public class SearchInstructionScalars extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length == 0) {
            throw new IllegalArgumentException("expected one or more integer scalars");
        }
        Set<Long> requested = new HashSet<>();
        for (String arg : args) {
            requested.add(Long.decode(arg));
        }

        for (Function function : currentProgram.getFunctionManager().getFunctions(true)) {
            if (monitor.isCancelled() || function.isExternal()) {
                continue;
            }
            Set<Long> found = new HashSet<>();
            List<String> matching = new ArrayList<>();
            InstructionIterator instructions = currentProgram.getListing()
                .getInstructions(function.getBody(), true);
            while (instructions.hasNext()) {
                Instruction instruction = instructions.next();
                boolean instructionMatches = false;
                for (int operand = 0; operand < instruction.getNumOperands(); operand++) {
                    for (Object object : instruction.getOpObjects(operand)) {
                        if (object instanceof Scalar) {
                            long value = ((Scalar)object).getUnsignedValue();
                            if (requested.contains(value)) {
                                found.add(value);
                                instructionMatches = true;
                            }
                        }
                    }
                }
                if (instructionMatches) {
                    matching.add(instruction.getAddress() + ": " + instruction);
                }
            }
            if (found.containsAll(requested)) {
                println("===== " + function.getName(true) + " @ "
                    + function.getEntryPoint() + " =====");
                for (String line : matching) {
                    println(line);
                }
            }
        }
    }
}
