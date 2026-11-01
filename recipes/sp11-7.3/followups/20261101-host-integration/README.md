# 7.3 host-integration follow-up: optional Surface HID descriptors

The full unified12 kernel now passed two owner-confirmed sound/touch boots.
Use the complete versioned `../../../sp11-7.3-host-integration/` recipe for
installation; this source follow-up alone is not an installer.
The accepted parent recipe/lock remains unchanged. This is the Surface sensor/
pen-storage HID transport, separate from the SPI touchscreen client.

Read-only descriptor requests returned a complete, zero-data, end=0xff response
for unavailable functions, while the keyboard supplied a valid descriptor. The
patch declines an empty first descriptor with -ENODEV, checks actual response
length before copying, and rejects zero progress. Malformed/later empty replies
remain protocol errors; supported keyboard and multi-chunk descriptors work.

```sh
SP11_KERNEL_SOURCE=/path/to/pre-fix/linux python3 -m unittest discover -s recipes/sp11-7.3/followups/20261101-host-integration -p 'test_*.py' -v
```

Ten cases execute the real C function, including the old truncated-copy and
empty-descriptor failures. Compile and boot-qualify the candidate; do not restart
the parent controller as a test. No firmware, unit identity or calibration is
included here. Use the shared audio recipe for the complete accepted composition.
