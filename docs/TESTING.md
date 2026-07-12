# Hardware testing

Always retain a known-good Ubuntu kernel and test through a separate GRUB
entry. Do not overwrite the normal kernel image or its only initramfs.

## Expected boot messages

```text
readiness OK on attempt 2
started BIOS-reference polled path: active-low GPIO51 descriptor, 40MHz, 5.3ms timer
```

The per-device `state` attribute should report:

```text
running=1
ready=1
gpio51_pending=0
transport_errors=0
protocol_errors=0
ready_gpio_timeouts=0
gpio_errors=0
```

## Coordinate check

Tap the corners in this order:

1. Top-left
2. Top-right
3. Bottom-right
4. Bottom-left

Expected normalized coordinates are approximately:

```text
top-left       0,0
top-right      1023,0
bottom-right   1023,1023
bottom-left    0,1023
```

The tested device produced values within roughly 1–25 units of those bounds.

## Stop conditions

Stop testing and return to the fallback entry if the GENI controller reports
timeouts, command aborts, FIFO errors or repeated transport failures. Never
repeatedly reload the controller after a hardware timeout.
