#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
set -eu

# Deploy the mechanically renamed Phase 73 DMA client into an isolated Phase
# 75 initramfs. The root filesystem's legacy FIFO client and stock controller
# modules are restored before exit. The saved GRUB default remains Phase 73.

release=7.1.3-sp11-baseline1+
expected_vermagic="$release SMP preempt mod_unload modversions aarch64"
script_dir=$(dirname -- "$0")
root=$(CDPATH='' cd -- "$script_dir/.." && pwd)
baseline_assets=/boot/sp11-7.1.3-baseline1
base_dma_dtb=$root/prebuilt/x1e80100-microsoft-denali-sp11-baseline1-dma.dtb
overlay_src=$root/dts/phase75-mshw0485-production.dtso
target_assets=/boot/sp11-7.1.3-phase75-identity
target_grub=/etc/grub.d/62_sp11_713_phase75_identity
target_dtb=x1e80100-microsoft-denali-sp11-phase75.dtb

built_client=$root/phase55/modules/mshw0485_touch.ko
built_controller=$root/phase55/modules/spi-geni-qcom.ko
built_gpi=$root/phase55/modules/gpi.ko
legacy_client=/lib/modules/$release/kernel/drivers/input/touchscreen/g6ts_biosref.ko.zst
installed_client=/lib/modules/$release/extra/mshw0485_touch.ko.zst
installed_controller=/lib/modules/$release/kernel/drivers/spi/spi-geni-qcom.ko.zst
installed_gpi=/lib/modules/$release/kernel/drivers/dma/qcom/gpi.ko.zst

work=$(mktemp -d)
backup_legacy=$work/g6ts_biosref.ko.zst.original
backup_controller=$work/spi-geni-qcom.ko.zst.original
backup_gpi=$work/gpi.ko.zst.original
backup_new=$work/mshw0485_touch.ko.zst.original
had_new=0
modules_swapped=0

restore_modules()
{
	if [ "$modules_swapped" = 1 ]; then
		[ -f "$backup_legacy" ] && cp -a "$backup_legacy" "$legacy_client"
		[ -f "$backup_controller" ] && cp -a "$backup_controller" "$installed_controller"
		[ -f "$backup_gpi" ] && cp -a "$backup_gpi" "$installed_gpi"
		if [ "$had_new" = 1 ]; then
			cp -a "$backup_new" "$installed_client"
		else
			rm -f "$installed_client"
		fi
		depmod -a "$release"
	fi
	rm -rf "$work"
}
trap restore_modules EXIT
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
	echo "Phase 75 target already exists; refusing to overwrite it" >&2
	exit 1
fi
if [ -n "$(git -C "$root" status --porcelain --untracked-files=normal)" ]; then
	echo "refusing to deploy from a dirty source tree" >&2
	exit 1
fi
for file in "$built_client" "$built_controller" "$built_gpi" \
	"$legacy_client" "$installed_controller" "$installed_gpi" \
	"$baseline_assets/vmlinuz-$release" "$base_dma_dtb" "$overlay_src"; do
	if [ ! -f "$file" ]; then
		echo "missing required file: $file" >&2
		exit 1
	fi
done
for module in "$built_client" "$built_controller" "$built_gpi"; do
	actual=$(modinfo -F vermagic "$module")
	if [ "$actual" != "$expected_vermagic" ]; then
		echo "$module has unexpected vermagic: $actual" >&2
		exit 1
	fi
done
if [ "$(modinfo -F name "$built_client")" != "mshw0485_touch" ]; then
	echo "client module identity is not mshw0485_touch" >&2
	exit 1
fi

# Produce the DMA DTB from the exact Phase 73 base plus a reviewable compatible
# override. Refuse a result that does not retain explicit GPI-DMA selection.
dtc -@ -I dts -O dtb -o "$work/phase75.dtbo" "$overlay_src"
fdtoverlay -i "$base_dma_dtb" -o "$work/$target_dtb" "$work/phase75.dtbo"
compatible=$(fdtget -t s "$work/$target_dtb" \
	/soc@0/geniqup@ac0000/spi@a88000/touchscreen@0 compatible)
if [ "$compatible" != "microsoft,mshw0485" ]; then
	echo "derived DTB has wrong touchscreen compatible: $compatible" >&2
	exit 1
fi
for property in qcom,enable-gsi-dma dmas dma-names; do
	if ! fdtget "$work/$target_dtb" \
		/soc@0/geniqup@ac0000/spi@a88000 "$property" >/dev/null 2>&1; then
		echo "derived DTB is missing $property" >&2
		exit 1
	fi
done

# Temporarily remove the legacy client and stage the uniquely named DMA set.
# This guarantees the isolated initramfs cannot contain both competing clients.
cp -a "$legacy_client" "$backup_legacy"
cp -a "$installed_controller" "$backup_controller"
cp -a "$installed_gpi" "$backup_gpi"
if [ -f "$installed_client" ]; then
	cp -a "$installed_client" "$backup_new"
	had_new=1
fi
modules_swapped=1
rm -f "$legacy_client"
mkdir -p "$(dirname "$installed_client")"
zstd -q -T0 -19 -f "$built_client" -o "$installed_client"
zstd -q -T0 -19 -f "$built_controller" -o "$installed_controller"
zstd -q -T0 -19 -f "$built_gpi" -o "$installed_gpi"
depmod -a "$release"

# Use an isolated initramfs-tools configuration so the machine's historical
# g6ts_biosref hook cannot reintroduce the FIFO client.
cp -a /etc/initramfs-tools "$work/initramfs-tools"
rm -f "$work/initramfs-tools/hooks/sp11-g6ts"
install -m 0755 "$root/packaging/initramfs-tools/hooks/sp11-mshw0485-touch" \
	"$work/initramfs-tools/hooks/sp11-mshw0485-touch"
mkinitramfs -d "$work/initramfs-tools" \
	-o "$work/initrd.img-$release-phase75" "$release"
unmkinitramfs "$work/initrd.img-$release-phase75" "$work/extracted"
embedded_client=$(find "$work/extracted" -type f \
	-name mshw0485_touch.ko.zst -print -quit)
if [ -z "$embedded_client" ] ||
	[ "$(modinfo -F srcversion "$embedded_client")" != \
	  "$(modinfo -F srcversion "$built_client")" ]; then
	echo "new initramfs does not contain the exact Phase 75 client" >&2
	exit 1
fi
if find "$work/extracted" -type f -name 'g6ts_biosref.ko*' | grep -q .; then
	echo "new initramfs unexpectedly contains the legacy FIFO client" >&2
	exit 1
fi
for module in spi-geni-qcom gpi; do
	if ! find "$work/extracted" -type f -name "$module.ko.zst" | grep -q .; then
		echo "new initramfs does not contain $module" >&2
		exit 1
	fi
done

mkdir -m 0755 "$target_assets"
install -m 0644 "$baseline_assets/vmlinuz-$release" \
	"$target_assets/vmlinuz-$release"
install -m 0644 "$work/$target_dtb" "$target_assets/$target_dtb"
install -m 0600 "$work/initrd.img-$release-phase75" \
	"$target_assets/initrd.img-$release-phase75"
install -m 0755 "$root/boot/62_sp11_713_phase75_identity" "$target_grub"

commit=$(git -C "$root" rev-parse HEAD)
{
	echo "Phase 75 source commit: $commit"
	echo "source worktree: clean"
	echo "target kernel: $release"
	echo "client module: mshw0485_touch"
	echo "client srcversion: $(modinfo -F srcversion "$built_client")"
	echo "controller srcversion: $(modinfo -F srcversion "$built_controller")"
	echo "GPI srcversion: $(modinfo -F srcversion "$built_gpi")"
	echo "legacy FIFO client embedded: no"
	echo "base DMA DTB sha256: $(sha256sum "$base_dma_dtb" | cut -d ' ' -f 1)"
	echo "DT overlay sha256: $(sha256sum "$overlay_src" | cut -d ' ' -f 1)"
	sha256sum \
		"$target_assets/initrd.img-$release-phase75" \
		"$target_assets/$target_dtb" \
		"$target_assets/vmlinuz-$release"
} > "$target_assets/DEPLOYMENT-MANIFEST.txt"

update-grub
grub-script-check /boot/grub/grub.cfg
if ! grep -q -- "--id 'sp11-phase75-identity'" /boot/grub/grub.cfg ||
	! grep -q "sp11_entry=7.1.3-phase75-identity" /boot/grub/grub.cfg ||
	! grep -q "mshw0485_touch.mode_config_fix=1" /boot/grub/grub.cfg; then
	echo "generated GRUB configuration is missing the Phase 75 entry" >&2
	exit 1
fi
grub-reboot sp11-phase75-identity

echo "installed isolated Phase 75 identity test: sp11-phase75-identity"
echo "the EXIT trap restores the legacy FIFO and stock controller modules"
echo "on the root filesystem; Phase 73 remains the saved default"
