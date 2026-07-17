#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
set -eu

release=7.1.1-sp11-gpicmp1+
expected_vermagic="$release SMP preempt mod_unload modversions aarch64"
script_dir=$(dirname -- "$0")
root=$(CDPATH='' cd -- "$script_dir/.." && pwd)
source_assets=/boot/sp11-7.1.1-phase66
target_assets=/boot/sp11-7.1.1-phase70
target_grub=/etc/grub.d/56_sp11_711_phase70_orchestrator
installed_client=/lib/modules/$release/kernel/drivers/input/touchscreen/g6ts_biosref.ko.zst
built_client=$root/phase55/modules/g6ts_biosref.ko
built_controller=$root/phase55/modules/spi-geni-qcom.ko
built_gpi=$root/phase55/modules/gpi.ko
installed_controller=/lib/modules/$release/kernel/drivers/spi/spi-geni-qcom.ko.zst
installed_gpi=/lib/modules/$release/kernel/drivers/dma/qcom/gpi.ko.zst
work=$(mktemp -d)
backup=$work/g6ts_biosref.ko.zst.original
module_swapped=0

restore_root_module()
{
	if [ "$module_swapped" = 1 ]; then
		cp -a "$backup" "$installed_client"
		depmod -a "$release"
	fi
	rm -rf "$work"
}
trap restore_root_module EXIT
trap 'exit 1' HUP INT TERM

if [ "$(id -u)" -ne 0 ]; then
	echo "run as root" >&2
	exit 1
fi
if [ "$(uname -r)" != "$release" ]; then
	echo "boot the matched $release kernel before deployment" >&2
	exit 1
fi
if [ -e "$target_assets" ] || [ -e "$target_grub" ]; then
	echo "Phase 70 target already exists; refusing to overwrite it" >&2
	exit 1
fi
for file in "$built_client" "$built_controller" "$built_gpi" \
	"$installed_client" "$installed_controller" "$installed_gpi" \
	"$source_assets/vmlinuz-$release" \
	"$source_assets/sp11-7.1.1-phase66-hybrid.dtb"; do
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
if [ "$(modinfo -F srcversion "$built_controller")" != \
	"$(modinfo -F srcversion "$installed_controller")" ]; then
	echo "installed GENI controller does not match the Phase 70 build" >&2
	exit 1
fi
if [ "$(modinfo -F srcversion "$built_gpi")" != \
	"$(modinfo -F srcversion "$installed_gpi")" ]; then
	echo "installed GPI module does not match the Phase 70 build" >&2
	exit 1
fi

cp -a "$installed_client" "$backup"
zstd -q -T0 -19 -f "$built_client" -o "$installed_client"
module_swapped=1
depmod -a "$release"
mkinitramfs -o "$work/initrd.img-$release-phase70" "$release"
unmkinitramfs "$work/initrd.img-$release-phase70" "$work/extracted"
embedded_client=$(find "$work/extracted" -type f \
	-name g6ts_biosref.ko.zst -print -quit)
if [ -z "$embedded_client" ] ||
	[ "$(modinfo -F srcversion "$embedded_client")" != \
	  "$(modinfo -F srcversion "$built_client")" ]; then
	echo "new initramfs does not contain the Phase 70 client" >&2
	exit 1
fi

mkdir -m 0755 "$target_assets"
install -m 0644 "$source_assets/vmlinuz-$release" \
	"$target_assets/vmlinuz-$release"
install -m 0644 "$source_assets/sp11-7.1.1-phase66-hybrid.dtb" \
	"$target_assets/sp11-7.1.1-phase70-hybrid.dtb"
install -m 0600 "$work/initrd.img-$release-phase70" \
	"$target_assets/initrd.img-$release-phase70"
install -m 0755 "$root/boot/57_sp11_711_phase70_orchestrator" "$target_grub"

commit=$(git -C "$root" rev-parse HEAD)
client_srcversion=$(modinfo -F srcversion "$built_client")
controller_srcversion=$(modinfo -F srcversion "$built_controller")
gpi_srcversion=$(modinfo -F srcversion "$built_gpi")
{
	echo "Phase 70 source commit: $commit"
	echo "client srcversion: $client_srcversion"
	echo "controller srcversion: $controller_srcversion"
	echo "GPI srcversion: $gpi_srcversion"
	echo "kernel parameter: g6ts_biosref.windows_orchestrator=1"
	sha256sum \
		"$target_assets/initrd.img-$release-phase70" \
		"$target_assets/sp11-7.1.1-phase70-hybrid.dtb" \
		"$target_assets/vmlinuz-$release"
} > "$target_assets/DEPLOYMENT-MANIFEST.txt"

update-grub
grub-script-check /boot/grub/grub.cfg
if ! grep -q -- "--id 'sp11-phase70'" /boot/grub/grub.cfg ||
	! grep -q "g6ts_biosref.windows_orchestrator=1" /boot/grub/grub.cfg; then
	echo "generated GRUB configuration is missing the Phase 70 entry" >&2
	exit 1
fi
grub-reboot sp11-phase70

echo "installed isolated Phase 70 entry: sp11-phase70"
echo "saved GRUB default was not changed; next boot only selects Phase 70"
