// SPDX-License-Identifier: GPL-2.0
// Seed ARC firmware analysis from a table of absolute function pointers.
// @category SP11

import java.util.HashSet;
import java.util.Set;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class SeedArcFirmware extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2 || args.length > 3) {
            throw new IllegalArgumentException(
                "expected scan start, inclusive end, and optional stride"
            );
        }

        Address cursor = toAddr(Long.decode(args[0]));
        Address end = toAddr(Long.decode(args[1]));
        int stride = args.length == 3 ? Integer.decode(args[2]) : 4;
        if (stride < 1) {
            throw new IllegalArgumentException("stride must be positive");
        }
        Set<Address> seeded = new HashSet<>();
        int pointers = 0;

        while (cursor.compareTo(end) <= 0 && !monitor.isCancelled()) {
            long value = Integer.toUnsignedLong(getInt(cursor));
            Address target = toAddr(value);
            if (currentProgram.getMemory().contains(target)) {
                pointers++;
                if (seeded.add(target)) {
                    disassemble(target);
                    Function function = getFunctionAt(target);
                    if (function == null) {
                        createFunction(target, String.format("arc_entry_%08x", value));
                    }
                }
            }
            cursor = cursor.add(stride);
        }

        println("ARC pointer entries: " + pointers);
        println("Unique ARC entry points seeded: " + seeded.size());
    }
}
