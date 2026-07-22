// SPDX-License-Identifier: GPL-2.0
// Search initialized memory for common 32-bit encodings of target addresses.
// @category SP11

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSetView;
import ghidra.program.model.mem.Memory;

public class SearchPointerEncodings extends GhidraScript {
    private static byte[] littleEndian(long value) {
        return new byte[] {
            (byte)value, (byte)(value >>> 8), (byte)(value >>> 16),
            (byte)(value >>> 24)
        };
    }

    private void search(String label, byte[] pattern) throws Exception {
        Memory memory = currentProgram.getMemory();
        AddressSetView initialized = memory.getLoadedAndInitializedAddressSet();
        Address cursor = initialized.getMinAddress();
        int count = 0;

        while (cursor != null) {
            Address found = memory.findBytes(cursor, pattern, null, true, monitor);
            if (found == null || !initialized.contains(found)) {
                break;
            }
            println("  " + label + " " + found);
            count++;
            cursor = found.next();
        }
        println("  " + label + " matches: " + count);
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length == 0) {
            throw new IllegalArgumentException("expected one or more addresses");
        }

        for (String arg : args) {
            long value = Long.decode(arg);
            byte[] le = littleEndian(value);
            byte[] be = new byte[] { le[3], le[2], le[1], le[0] };
            byte[] halfwordSwapped = new byte[] { le[2], le[3], le[0], le[1] };
            println("TARGET " + arg);
            search("little-endian", le);
            search("big-endian", be);
            search("halfword-swapped", halfwordSwapped);
        }
    }
}
