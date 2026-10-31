# SP11 OLED: shared 7.3 sound/touch recipe

The owner confirmed normal tapping, dragging and scrolling and clear first
sound after quiet periods on two fresh boots, including startup tracing off.
This is the current **tested-unit sound/touch baseline**. The historical Phase
91 installation instructions elsewhere in this repository target 7.1.3.
Do not install their transport modules over 7.3.

The accepted client alone was insufficient: 7.3 also needed matching GENI/GPI
transport, device tree, boot arguments, audio power behavior and userspace.
We therefore use one shared release, `sp11-denali-oled-7.3-20261031-wifi`, owned by
the [audio repository](https://github.com/geocausa/SP11X1e-audio).
`shared-release.json` pins the audio commit and recipe files by hash. The
wrapper refuses a mismatched recipe before running any install action.

## Use the pinned release

Check out the audio commit named in `shared-release.json` and read its
`recipes/sp11-7.3/README.md`. Its exporter produces an owner-private bundle of
the accepted kernel, all 8,711 modules, firmware/topology/UCM, audio helpers,
private calibration, complete kernel source and ordered integration patches.
The bundle is kept outside both repositories. A clone alone does not supply
the private payloads.

From this repository:

```sh
python3 recipes/sp11-7.3/sp11_73.py --audio-repo /path/to/SP11X1e-audio -- \
  verify /path/to/private-release/bundle

# Offline only: render into an empty directory with a different owner/root.
python3 recipes/sp11-7.3/sp11_73.py --audio-repo /path/to/SP11X1e-audio -- \
  stage /path/to/private-release/bundle --root /path/to/empty-root \
  --home /home/NEWOWNER --uid 2000 \
  --root-uuid 11111111-2222-3333-4444-555555555555
```

The canonical recipe documents guarded installation and postboot verification.
Installation is scoped to the same tested OLED unit, Ubuntu 26.10 ARM64 and the
pinned package versions, with ext4 root and `/boot` on that root. It relocates
the username/UID/root UUID and private pack path; per-device touch identity
remains private and hardware-bound. It preserves the existing boot default
and does not compile a kernel, restart services or reboot.

## Source repair and qualification

The full image base is `e8ceea84ec1d914c3fc813f0b0f4c9e8c95b9a7f`;
the accepted repaired-GPI integration is
`cedc5a624a1869df3b313dd4ac0985d2f130ed61`. The ABI release remains
`7.3.0-sp11-unified10`; verify the actual GPI srcversion
`2EEC5D286A1E1770FF353C5`, not just that release string.

`gpi-7.3-ordering-lifetime.patch` is the exact delta between those commits:

- Ordered reads of the hardware event-ring progress pointer serialize subsequent
  coherent DMA event loads.
- Termination quiesces both channels and clears the deferred QSPI completion
  under the same lock, then synchronously cancels the timer. Freeing channel
  resources also clears the matching deferred pointer.
- Optional event/submit tracepoints retain diagnosis capability; the accepted
  normal boot does not enable them.

This patch is **relative to that integrated base**, not a standalone patch for
stock 7.3 or a replacement for the entire shared kernel integration. The
private bundle's complete source archive reconstructs the pinned integration
tree; its 39-patch series records the changes after the pristine 7.3 snapshot.
No new kernel was compiled to package this release.

Offline tests and a new initrd rehearsal passed. Physical acceptance comes
from the two recorded boots, not from the packaging tests. A clean OS reinstall
has not been physically performed. After installation, verify actual modules,
contacts and zero transport/kernel faults; test both speakers after two
separate 20-second quiet pauses, then repeat a fresh boot. Do not use a live
parent-controller restart to force touch initialization.

Camera, microphone and system suspend remain separately unqualified. Newer
kernels/package versions or another hardware unit require a reviewed port and
the same physical gates; copying the recipe does not establish compatibility.

## Accepted Wi-Fi follow-up

The current shared release adds ath12k core integration
`e9e5dd622ee88f33fdc7e275963d0cb9e42aa40a` on top of the GPI integration above.
Only the Wi-Fi core was rebuilt; touch, GPI, audio and the main image retain
their accepted bytes. Two completed live router channel switches were captured
with zero statistics timeouts and 387.6 seconds of responsive follow-up. The
owner confirmed normal touch, clear cold audio twice and responsive Resources.
The router's original settings were restored.

The canonical audio recipe pins the full four-file WCN7850 firmware closure,
loads the core early using `rd.driver.pre=ath12k`, and verifies actual loaded
identities. A first initrd-only attempt had loaded the old core after switching
to the root disk; this loading requirement is part of the recipe. The matching
small source delta is `wifi-vdev-count.patch` in the audio recipe. Its complete
source archive and ordered 39 changes remain in the owner-private bundle.
