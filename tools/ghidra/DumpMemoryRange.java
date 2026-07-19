// SPDX-License-Identifier: GPL-2.0
// Print a bounded memory range from the current program as hexadecimal bytes.
// @category SP11

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;

public class DumpMemoryRange extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 2) {
            throw new IllegalArgumentException("expected start address and length");
        }

        Address start = toAddr(Long.decode(args[0]));
        int length = Integer.decode(args[1]);
        if (length < 0 || length > 0x10000) {
            throw new IllegalArgumentException("length must be between 0 and 65536");
        }

        byte[] bytes = new byte[length];
        int read = currentProgram.getMemory().getBytes(start, bytes);
        for (int offset = 0; offset < read; offset += 16) {
            StringBuilder line = new StringBuilder();
            line.append(start.add(offset)).append(":");
            int count = Math.min(16, read - offset);
            for (int i = 0; i < count; i++) {
                line.append(String.format(" %02x", bytes[offset + i] & 0xff));
            }
            println(line.toString());
        }
        println("Bytes: " + read);
    }
}
