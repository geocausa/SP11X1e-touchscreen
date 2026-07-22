// SPDX-License-Identifier: GPL-2.0
// Export a bounded initialized-memory range from the current program.
// @category SP11

import java.io.BufferedOutputStream;
import java.io.FileOutputStream;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;

public class ExportMemoryRange extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 3) {
            throw new IllegalArgumentException(
                "expected start address, length, and output path"
            );
        }

        Address start = toAddr(Long.decode(args[0]));
        long requested = Long.decode(args[1]);
        if (requested < 0 || requested > Integer.MAX_VALUE) {
            throw new IllegalArgumentException("invalid export length");
        }

        int remaining = (int)requested;
        Address cursor = start;
        byte[] chunk = new byte[Math.min(0x10000, Math.max(1, remaining))];
        try (BufferedOutputStream output = new BufferedOutputStream(
                new FileOutputStream(args[2]))) {
            while (remaining > 0) {
                int count = Math.min(remaining, chunk.length);
                int read = currentProgram.getMemory().getBytes(cursor, chunk, 0, count);
                if (read != count) {
                    throw new IllegalStateException(
                        "short read at " + cursor + ": " + read + "/" + count
                    );
                }
                output.write(chunk, 0, read);
                cursor = cursor.add(read);
                remaining -= read;
            }
        }
        println("Exported " + requested + " bytes from " + start +
            " to " + args[2]);
    }
}
