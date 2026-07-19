# Phase 81 guarded GPIO51 quiescence

Phase 80's first cold boot validated its host-fault recovery but recorded five
`-EPROTO` header failures, all followed by successful hardware recovery. Two
failures arrived within milliseconds of a valid first Heat frame. The same
module also saw two genuine class-3 panel reset notifications, which remained
separately counted and recovered through Phase 77.

That timing exposes a narrower host bug: after a complete body transaction,
GPIO51 can remain logically ready briefly while the panel retires the read.
The edge-triggered IRQ drain may begin another header transaction during that
tail. Phase 80 interpreted any invalid header as a persistent protocol fault
and performed a full reset.

Phase 81 adds a read-only `ready_quiesce=1` switch. After an invalid header it:

1. waits 100-200 microseconds once;
2. samples GPIO51 again;
3. returns an empty-read result only if GPIO51 has deasserted; and
4. retains Phase 80's full protocol-fault recovery if GPIO51 is still active.

This is not a blind retry, a header whitelist, or a suppression counter. The
guard is the hardware ready line itself. `quiesced_empty_reads` records every
event accepted by that narrow rule, while invalid persistent headers still log
their four raw bytes and enter bounded recovery.

## Warm live trial

The Phase 81 client was live-loaded over the first Phase 80 boot. It completed
cold hardware initialization and processed 3,978 Heat frames during active
touch use with:

```text
panel_resets=0
host_fault_recoveries=0
irq_protocol_errors=0
irq_drain_overflows=0
quiesced_empty_reads=0
heat_errors=0
```

Because the questionable event did not recur after a warm reload, this trial
validates ordinary touch but not the quiesce branch. The isolated cold-boot
entry exists specifically to reproduce the early-boot timing without changing
the Phase 75 saved baseline.

## Cold-boot result

The isolated Phase 81 entry subsequently exercised the branch 17 times during
3,127 valid Heat frames. Every suspect trailing read was accepted only after
GPIO51 deasserted. The driver recorded zero IRQ protocol errors, zero host-fault
recoveries, zero drain overflows, and zero Heat errors. This confirms that the
five Phase 80 `-EPROTO` events were harmless post-read tails rather than
persistent bus faults.

The same boot independently received 24 class-3 panel reset notifications.
All 24 software recoveries succeeded, but the reset clusters continued. Phase
81 therefore fixes host-side fault classification; it does not explain or hide
the panel's separate reset storm.

Offline validation completed with all 141 tests passing, an exact-tree GCC
`W=1` build, clean Sparse analysis for all three modules, clean strict kernel
style review, and shell validation of the deployment path. The Phase 81 client
source version is `83731BB4EEA48C08A9F53A3`.
