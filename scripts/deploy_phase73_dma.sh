#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
set -eu

# Phase 73: deploy the QSPI/GPI-DMA multi-touch stack + Phase 72 mode-config fix
# onto the 7.1.3 baseline kernel, in a fully isolated one-shot boot entry. The
# stock baseline modules are backed up and restored on exit; the saved GRUB
# default is never changed. Requires ALLOW_UNTESTED_KERNEL-built modules whose
# vermagic matches the running 7.1.3 baseline kernel.

release=7.1.3-sp11-baseline1+
expected_vermagic="$release SMP preempt mod_unload modversions aarch64"
script_dir=$(dirname -- "$0")
root=$(CDPATH='' cd -- "$script_dir/.." && pwd)
baseline_assets=/boot/sp11-7.1.3-baseline1
baseline_dtb_name=x1e80100-microsoft-denali-sp11-baseline1.dtb
target_assets=/boot/sp11-7.1.3-phase73-dma
target_grub=/etc/grub.d/60_sp11_713_phase73_dma

built_client=$root/phase55/modules/g6ts_biosref.ko
built_controller=$root/phase55/modules/spi-geni-qcom.ko
built_gpi=$root/phase55/modules/gpi.ko
installed_client=/lib/modules/$release/kernel/drivers/input/touchscreen/g6ts_biosref.ko.zst
installed_controller=/lib/modules/$release/kernel/drivers/spi/spi-geni-qcom.ko.zst
installed_gpi=/lib/modules/$release/kernel/drivers/dma/qcom/gpi.ko.zst

work=$(mktemp -d)
backup_client=$work/g6ts_biosref.ko.zst.original
backup_controller=$work/spi-geni-qcom.ko.zst.original
backup_gpi=$work/gpi.ko.zst.original
modules_swapped=0

restore_stock_modules()
{
        if [ "$modules_swapped" = 1 ]; then
                [ -f "$backup_client" ] && cp -a "$backup_client" "$installed_client"
                [ -f "$backup_controller" ] && cp -a "$backup_controller" "$installed_controller"
                [ -f "$backup_gpi" ] && cp -a "$backup_gpi" "$installed_gpi"
                depmod -a "$release"
        fi
        rm -rf "$work"
}
trap restore_stock_modules EXIT
trap 'exit 1' HUP INT TERM

if [ "$(id -u)" -ne 0 ]; then
        echo "run as root" >&2
        exit 1
fi
if [ "$(uname -r)" != "$release" ]; then
        echo "boot the $release baseline kernel before deployment" >&2
        exit 1
fi
if [ -e "$target_assets" ] || [ -e "$target_grub" ]; then
        echo "Phase 73 target already exists; refusing to overwrite it" >&2
        exit 1
fi
for file in "$built_client" "$built_controller" "$built_gpi" \
        "$installed_client" "$installed_controller" "$installed_gpi" \
        "$baseline_assets/vmlinuz-$release" \
        "$baseline_assets/$baseline_dtb_name"; do
        if [ ! -f "$file" ]; then
                echo "missing required file: $file" >&2
                exit 1
        fi
done

# Verify all three built modules target the running baseline kernel exactly.
for module in "$built_client" "$built_controller" "$built_gpi"; do
        actual=$(modinfo -F vermagic "$module")
        if [ "$actual" != "$expected_vermagic" ]; then
                echo "$module has unexpected vermagic: $actual" >&2
                echo "expected: $expected_vermagic" >&2
                exit 1
        fi
done

# Back up the stock baseline modules, then install the DMA-capable set.
# NOTE: unlike Phase 72, the baseline ships STOCK controllers, so we replace
# all three (client + spi-geni-qcom + gpi). srcversion match is intentionally
# NOT required here: the whole point is to swap stock -> DMA.
cp -a "$installed_client" "$backup_client"
cp -a "$installed_controller" "$backup_controller"
cp -a "$installed_gpi" "$backup_gpi"
zstd -q -T0 -19 -f "$built_client" -o "$installed_client"
zstd -q -T0 -19 -f "$built_controller" -o "$installed_controller"
zstd -q -T0 -19 -f "$built_gpi" -o "$installed_gpi"
modules_swapped=1
depmod -a "$release"

# Build an initramfs that embeds the swapped-in DMA modules.
mkinitramfs -o "$work/initrd.img-$release-phase73" "$release"
unmkinitramfs "$work/initrd.img-$release-phase73" "$work/extracted"
embedded_client=$(find "$work/extracted" -type f \
        -name g6ts_biosref.ko.zst -print -quit)
if [ -z "$embedded_client" ] ||
        [ "$(modinfo -F srcversion "$embedded_client")" != \
          "$(modinfo -F srcversion "$built_client")" ]; then
        echo "new initramfs does not contain the Phase 73 DMA client" >&2
        exit 1
fi
embedded_gpi=$(find "$work/extracted" -type f -name gpi.ko.zst -print -quit)
if [ -z "$embedded_gpi" ] ||
        [ "$(modinfo -F srcversion "$embedded_gpi")" != \
          "$(modinfo -F srcversion "$built_gpi")" ]; then
        echo "new initramfs does not contain the Phase 73 DMA GPI module" >&2
        exit 1
fi

# Install isolated boot assets: baseline kernel + baseline DTB (already carries
# the qcom,biosref-qspi touch node) + the DMA initramfs.
mkdir -m 0755 "$target_assets"
install -m 0644 "$baseline_assets/vmlinuz-$release" \
        "$target_assets/vmlinuz-$release"
install -m 0644 "$baseline_assets/$baseline_dtb_name" \
        "$target_assets/$baseline_dtb_name"
install -m 0600 "$work/initrd.img-$release-phase73" \
        "$target_assets/initrd.img-$release-phase73"
install -m 0755 "$root/boot/60_sp11_713_phase73_dma" "$target_grub"

commit=$(git -C "$root" rev-parse HEAD 2>/dev/null || echo unknown)
{
        echo "Phase 73 source commit: $commit"
        echo "target kernel: $release"
        echo "client srcversion: $(modinfo -F srcversion "$built_client")"
        echo "controller srcversion: $(modinfo -F srcversion "$built_controller")"
        echo "GPI srcversion: $(modinfo -F srcversion "$built_gpi")"
        echo "kernel parameter: g6ts_biosref.mode_config_fix=1"
        sha256sum \
                "$target_assets/initrd.img-$release-phase73" \
                "$target_assets/$baseline_dtb_name" \
                "$target_assets/vmlinuz-$release"
} > "$target_assets/DEPLOYMENT-MANIFEST.txt"

update-grub
grub-script-check /boot/grub/grub.cfg
if ! grep -q -- "--id 'sp11-phase73-dma'" /boot/grub/grub.cfg ||
        ! grep -q "sp11_entry=7.1.3-phase73-dma" /boot/grub/grub.cfg ||
        ! grep -q "g6ts_biosref.mode_config_fix=1" /boot/grub/grub.cfg; then
        echo "generated GRUB configuration is missing the Phase 73 entry" >&2
        exit 1
fi
grub-reboot sp11-phase73-dma

# IMPORTANT: the stock baseline modules on disk were swapped for the DMA set so
# the initramfs could embed them. The EXIT trap restores the stock modules on
# disk now, so the default baseline entry stays FIFO/stock. The Phase 73 entry
# boots from its own initramfs which has the DMA modules embedded, so it is
# unaffected by the on-disk restore.
echo "installed isolated Phase 73 DMA entry: sp11-phase73-dma"
echo "stock baseline modules on disk will be restored on exit; only the"
echo "Phase 73 entry (its own initramfs) carries the DMA stack."
echo "saved GRUB default was not changed; next boot only selects Phase 73."
