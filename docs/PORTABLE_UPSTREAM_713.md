# Phase 91 portable installer for upstream Linux 7.1.3

## Purpose

The portable release bundle can build and deploy the Phase 91 DMA touchscreen
stack on another Surface Pro 11 OLED that is already running a clean upstream
Linux 7.1.3 Ubuntu installation. It does not reuse the prebuilt modules from
the development machine: all three modules are compiled locally against the
recipient kernel's exact build directory and `Module.symvers`.

The installer supplies the pieces absent from pristine v7.1.3:

- the QSPI/protocol-9 extensions to Qualcomm GPI-DMA;
- the matching Qualcomm GENI SPI controller;
- the Phase 91 `MSHW0485` touchscreen client;
- a derived DTB that enables GPI DMA1 and SPI10, adds QSPI IO2/IO3, and creates
  the touchscreen node; and
- the Windows-measured Phase 91 initialization and response-cadence options.

The source and overlay compile against pristine v7.1.3, and the generated DTB
has been applied to and inspected against the upstream Denali OLED DTB. This is
static portability validation. The clean-upstream installation path still
needs its first hardware test on a second machine, so it is intentionally
labelled a portable test rather than a universal installer.

## Hard requirements

The installer stops without changing boot files unless all of these are true:

- ARM64 Surface Pro 11 OLED (`microsoft,denali-oled`);
- the running release begins with `7.1.3`;
- `/lib/modules/$(uname -r)/build` is the exact prepared build tree and has a
  non-empty `Module.symvers`;
- `CONFIG_QCOM_GPI_DMA=m` and `CONFIG_SPI_QCOM_GENI=m`;
- the installed GPI and GENI SPI modules are the clean, replaceable versions;
- a pristine `x1e80100-microsoft-denali-oled.dtb` with symbols is installed;
- Ubuntu `initramfs-tools` and GRUB are in use; and
- Secure Boot and forced module-signature enforcement are disabled.

The same numeric kernel version is not sufficient by itself. Compiler flags,
configuration, symbol versions, and Ubuntu ABI suffixes can differ. The local
build and exact vermagic comparison are mandatory.

Useful Ubuntu build/deployment packages include:

```bash
sudo apt install build-essential device-tree-compiler initramfs-tools \
  kmod grub-common linux-headers-$(uname -r)
```

The exact package names can vary with the kernel source used by the target
installation. A complete `Module.symvers` is required; `modules_prepare` alone
does not create it when symbol versioning is enabled.

## Install

Extract the release archive, enter its directory, and first run the read-only
preflight:

```bash
sudo ./install.sh --preflight-only
```

If the installed kernel package keeps its DTB in a nonstandard location:

```bash
sudo ./install.sh --preflight-only \
  --base-dtb /path/to/x1e80100-microsoft-denali-oled.dtb
```

Run the complete installer with the same optional `--base-dtb` argument:

```bash
sudo ./install.sh
```

The installer builds from source, verifies the module identity and exact
vermagic, derives and audits a Phase 91 DTB, constructs an isolated initramfs,
restores the stock module index, and adds a separate GRUB entry. It then arms
that entry for the next boot only.

It does **not** overwrite the stock kernel, stock modules, base DTB, or saved
GRUB default. On an installation error it removes the incomplete entry and
assets. Use `--no-arm-next-boot` to install without selecting the test entry.

## First boot and rollback

Reboot after a successful install. The one-time entry is named approximately:

```text
Ubuntu SP11 7.1.3... Phase 91 DMA (portable upstream test)
```

If it fails, the firmware or GRUB recovery menu still contains the unchanged
upstream entry, and GRUB automatically returns to its saved default on the
following boot. Do not promote the portable entry until touch, typing,
multi-touch, cold boot, and the driver fault counters have been checked.

## Supported boundary

This package is deliberately limited to Linux 7.1.3 and the OLED SP11. It does
not claim support for the LCD model, Linux 7.2+, Secure Boot, built-in GPI/GENI
drivers, UKI/systemd-boot, dracut-only systems, or an already modified kernel.
Those are separate ports, not installer overrides.
