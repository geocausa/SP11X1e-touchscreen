# Transport portability audit — 2026-08-04

This document separates the generic G6 touchscreen protocol work from the
Snapdragon/Qualcomm transport changes that currently make Phase 91 an
out-of-tree, matched-kernel solution.

The important conclusion is that the touchscreen protocol client itself mostly
uses ordinary Linux SPI APIs. The portability boundary is lower: protocol-9
QSPI support, paired bidirectional DMA submission, GPI transfer/event-ring
semantics, and completion ordering in the matched Qualcomm controller stack.

## Production boundary

Phase 91 is validated only on:

```text
7.1.3-sp11-baseline1+
```

`phase55/modules/Makefile` deliberately refuses a different configured kernel
release unless `ALLOW_UNTESTED_KERNEL=1` is supplied. That guard is justified:
a matching module version string is not sufficient because this tree carries
source-level controller and GPI behavior required by the tested QSPI path.

## Generic touchscreen layer

`phase55/modules/mshw0485_touch.c` builds the HID-SPI/QSPI protocol framing,
Windows-derived initialization, response cadence, Heat parsing and input
reporting. Its transport calls are standard SPI messages, including
`spi_sync()`, with quad-lane transfer flags such as `SPI_NBITS_QUAD`.

This means the protocol state machine is conceptually separable from the
platform transport implementation. The current blocker to wider kernels is not
the existence of a private touch-specific bus API inside the client.

## Matched `spi-geni-qcom.c` dependencies

The matched controller source contains explicit SP11/protocol-9 QSPI work that
is outside a normal generic SPI-client assumption.

### Protocol-9 / device-specific controller path

The source:

- includes the project-specific `linux/spi/spi-geni-qcom-biosref.h` interface;
- defines GENI QSPI protocol `9` support;
- recognizes the SP11 QSPI instance at `a88000.spi`;
- contains SP11-specific setup, live, and resting interrupt-mask handling;
- contains both Linux-integrated and captured-Windows controller preparation
  paths used by the transport investigation phases.

The Windows-parity 13-write initialization remains a laboratory option, while
Phase 91 uses the proven Linux-integrated lower transport. Even so, the
controller has SP11-specific runtime handling in the production matched source.

### Paired bidirectional DMA path

The normal SPI-core sequencing was not sufficient for the SP11 QSPI response
read pattern. The matched controller therefore contains a dedicated paired
TX/RX path (`spi_geni_sp11_qspi_submit_read_pair`) which:

- configures both GPI DMA directions;
- prepares RX and TX descriptors as one logical QSPI operation;
- installs result callbacks for both descriptors;
- submits RX before TX and issues both channels;
- waits for both results;
- restores controller interrupt state on completion and on every error path;
- performs explicit DMA synchronization around the paired operation.

The source comments explicitly note that this paired path replaces the normal
SPI core `transfer_one_message()` behavior for these transactions, so it must
preserve the DMA API synchronization contract itself.

### DMA mapping-device requirement

The matched code records and uses the SPI core's TX/RX DMA mapping devices for
synchronization. On this SP11 path the QUP wrapper, rather than the GENI child
or GPI control device, is the payload DMA master. This is a platform-specific
IOMMU/DMA ownership detail that must be revalidated on any controller rebase.

## Matched `gpi.c` dependencies

The GPI layer carries the other half of the production transport behavior.

### QSPI TRE support

The source contains QSPI-specific TRE definitions and processing, including
CONFIG/GO records and the Linux-required coupling of the bidirectional command.
Experimental controls for captured Windows ring geometry and the Linux `LINK`
adaptation remain in the source because Phases 84--89 demonstrated that these
properties cannot be changed independently without affecting first-RX
completion.

### Completion ordering is correctness-critical

The most important non-generic behavior is TX completion ordering.

For this QSPI path, a TX data EOT event can arrive before the matching QUP
command-completion notification. If the DMA cookie is completed at that first
EOT, the SPI client can ring the following command while the previous GENI/QUP
command is still retiring. The observed result is a wedged TX/RX pair.

The matched GPI code therefore:

- accepts terminal completion only for the final relevant TRE;
- defers the QSPI TX DMA-cookie completion after data EOT;
- retains one deferred descriptor;
- completes it when the matching QUP notification arrives;
- has a bounded timer fallback;
- rejects duplicate TX EOT while a completion is already deferred.

This behavior is a substantive transport requirement, not diagnostics.

### Ring/coupling experiments are not production portability claims

The source still exposes laboratory controls such as:

- `sp11_windows_ring_layout`;
- `sp11_qspi_linux_link`;
- high-volume SP11 QSPI diagnostics.

Those controls document what was tested during the Windows-parity transport
work. They do not imply that captured Windows ring sizes should be upstreamed
or enabled by default. Phase 89 restored normal Linux GPI ring geometry, and
Phase 91's success depends on the complete proven lower transport rather than
blind Windows register/ring replication.

## What a kernel rebase must review

A source-level port to another kernel must review, not merely compile, at least:

1. GENI protocol-9 QSPI support and lane/word programming;
2. the SP11 paired TX/RX submission path;
3. SPI-core DMA mapping-device semantics and explicit sync placement;
4. GPI QSPI TRE generation, including the Linux-required bidirectional
   coupling;
5. GPI event parsing and final-TRE completion tests;
6. deferred TX EOT versus QUP-notification ordering;
7. controller interrupt-mask transitions before, during and after a live
   paired transfer;
8. runtime PM/resource sequencing around the controller and DMA channels;
9. error/timeout termination of both DMA directions;
10. hardware validation of reset response, upper init, sustained 3636-byte
    Heat streaming and Phase-91 cadence under the rebased sources.

## Refactor direction

A cleaner long-term architecture is:

```text
G6 HID/Heat protocol + input policy
        |
        v
standard SPI message interface
        |
        v
Qualcomm GENI QSPI transport support
        |
        v
GPI DMA / QUP completion semantics
```

The first layer can be made increasingly generic without pretending the lower
three layers are already upstream-ready. A sensible upstream sequence is:

1. isolate and document the protocol-9 QSPI requirements in the Qualcomm SPI
   controller;
2. express the paired operation through the smallest maintainable controller
   extension or generic SPI mechanism available in the target kernel;
3. fix/justify QSPI completion ordering in the GPI layer independently of the
   touchscreen client;
4. remove SP11-only debug/laboratory knobs from the production transport once
   the generic behavior is represented cleanly;
5. only then reshape the G6 client for normal upstream review.

## Current claim

Phase 91 is a validated SP11 solution for the exact matched kernel and matched
GENI/GPI sources. It is **not** a claim that another kernel can safely use the
same touch module by recompiling it. The key portability work is lower-level
transport engineering, and the matched sources now make those dependencies
concrete enough to review one by one.
