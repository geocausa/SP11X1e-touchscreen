#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
set -eu

# Build an isolated initramfs for the Phase 82 Windows-length SET70 experiment.
# Existing Phase 75 through Phase 81 assets and root-filesystem modules are
# never replaced.

release=7.1.3-sp11-baseline1+
expected_vermagic="$release SMP preempt mod_unload modversions aarch64"
script_dir=$(dirname -- "$0")
root=$(CDPATH='' cd -- "$script_dir/.." && pwd)
phase75_assets=/boot/sp11-7.1.3-phase75-identity
dtb_name=x1e80100-microsoft-denali-sp11-phase75.dtb
target_assets=/boot/sp11-7.1.3-phase82-set70
target_grub=/etc/grub.d/69_sp11_713_phase82_set70

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
backup_client=$work/mshw0485_touch.ko.zst.original
had_client=0
modules_swapped=0
deployment_started=0
deployment_complete=0

restore_modules()
{
	status=$?
	trap - EXIT
	set +e
	if [ "$modules_swapped" = 1 ]; then
		[ -f "$backup_legacy" ] && cp -a "$backup_legacy" "$legacy_client"
		cp -a "$backup_controller" "$installed_controller"
		cp -a "$backup_gpi" "$installed_gpi"
		if [ "$had_client" = 1 ]; then
			cp -a "$backup_client" "$installed_client"
		else
			rm -f "$installed_client"
		fi
		depmod -a "$release"
	fi
	if [ "$deployment_started" = 1 ] && [ "$deployment_complete" != 1 ]; then
		rm -rf "$target_assets"
		rm -f "$target_grub"
		update-grub >/dev/null 2>&1
	fi
	rm -rf "$work"
	exit "$status"
}
trap restore_modules EXIT
trap 'exit 1' HUP INT TERM

if [ "$(id -u)" -ne 0 ]; then
	echo "run as root" >&2
	exit 1
fi
if [ "$(uname -r)" != "$release" ]; then
	echo "boot the $release Phase 75/76 baseline before deployment" >&2
	exit 1
fi
if [ -e "$target_assets" ] || [ -e "$target_grub" ]; then
	echo "Phase 82 target already exists; refusing to overwrite it" >&2
	exit 1
fi
if [ -n "$(git -C "$root" status --porcelain --untracked-files=normal)" ]; then
	echo "refusing to deploy from a dirty source tree" >&2
	exit 1
fi
for file in "$built_client" "$built_controller" "$built_gpi" \
	"$legacy_client" "$installed_controller" "$installed_gpi" \
	"$phase75_assets/vmlinuz-$release" "$phase75_assets/$dtb_name" \
	"$root/boot/69_sp11_713_phase82_set70"; do
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
for parameter in behavior_v2 reset_recovery_v2 host_fault_recovery ready_quiesce feature70_one_byte; do
	if ! modinfo -p "$built_client" | grep -q "^$parameter:"; then
		echo "client module does not expose $parameter" >&2
		exit 1
	fi
done

cp -a "$legacy_client" "$backup_legacy"
cp -a "$installed_controller" "$backup_controller"
cp -a "$installed_gpi" "$backup_gpi"
if [ -f "$installed_client" ]; then
	cp -a "$installed_client" "$backup_client"
	had_client=1
fi
modules_swapped=1
rm -f "$legacy_client"
mkdir -p "$(dirname "$installed_client")"
zstd -q -T0 -19 -f "$built_client" -o "$installed_client"
zstd -q -T0 -19 -f "$built_controller" -o "$installed_controller"
zstd -q -T0 -19 -f "$built_gpi" -o "$installed_gpi"
depmod -a "$release"

cp -a /etc/initramfs-tools "$work/initramfs-tools"
rm -f "$work/initramfs-tools/hooks/sp11-g6ts"
install -m 0755 "$root/packaging/initramfs-tools/hooks/sp11-mshw0485-touch" \
	"$work/initramfs-tools/hooks/sp11-mshw0485-touch"
mkinitramfs -d "$work/initramfs-tools" \
	-o "$work/initrd.img-$release-phase82" "$release"
unmkinitramfs "$work/initrd.img-$release-phase82" "$work/extracted"

embedded_client=$(find "$work/extracted" -type f \
	-name mshw0485_touch.ko.zst -print -quit)
if [ -z "$embedded_client" ] ||
	[ "$(modinfo -F srcversion "$embedded_client")" != \
	  "$(modinfo -F srcversion "$built_client")" ]; then
	echo "new initramfs does not contain the exact Phase 82 client" >&2
	exit 1
fi
for parameter in behavior_v2 reset_recovery_v2 host_fault_recovery ready_quiesce feature70_one_byte; do
	if ! modinfo -p "$embedded_client" | grep -q "^$parameter:"; then
		echo "embedded client does not expose $parameter" >&2
		exit 1
	fi
done
if find "$work/extracted" -type f -name 'g6ts_biosref.ko*' | grep -q .; then
	echo "new initramfs unexpectedly contains the legacy FIFO client" >&2
	exit 1
fi
for name in spi-geni-qcom gpi; do
	case "$name" in
	spi-geni-qcom) built=$built_controller ;;
	gpi) built=$built_gpi ;;
	esac
	embedded=$(find "$work/extracted" -type f \
		-name "$name.ko.zst" -print -quit)
	if [ -z "$embedded" ]; then
		echo "new initramfs does not contain $name" >&2
		exit 1
	fi
	if [ "$(modinfo -F srcversion "$embedded")" != \
	     "$(modinfo -F srcversion "$built")" ]; then
		echo "new initramfs does not contain the exact $name build" >&2
		exit 1
	fi
done

deployment_started=1
mkdir -m 0755 "$target_assets"
install -m 0644 "$phase75_assets/vmlinuz-$release" \
	"$target_assets/vmlinuz-$release"
install -m 0644 "$phase75_assets/$dtb_name" \
	"$target_assets/$dtb_name"
install -m 0600 "$work/initrd.img-$release-phase82" \
	"$target_assets/initrd.img-$release-phase82"
install -m 0755 "$root/boot/69_sp11_713_phase82_set70" "$target_grub"

commit=$(git -C "$root" rev-parse HEAD)
{
	echo "Phase 82 source commit: $commit"
	echo "source worktree: clean"
	echo "target kernel: $release"
	echo "transport/mode baseline: Phase 75 unchanged"
	echo "contact profile: mshw0485_touch.behavior_v2=1"
	echo "recovery profile: mshw0485_touch.reset_recovery_v2=1"
	echo "host fault recovery: mshw0485_touch.host_fault_recovery=1"
	echo "ready-line quiesce: mshw0485_touch.ready_quiesce=1"
	echo "SET70 logical content: mshw0485_touch.feature70_one_byte=1"
	echo "client srcversion: $(modinfo -F srcversion "$built_client")"
	echo "controller srcversion: $(modinfo -F srcversion "$built_controller")"
	echo "GPI srcversion: $(modinfo -F srcversion "$built_gpi")"
	echo "legacy FIFO client embedded: no"
	sha256sum \
		"$target_assets/initrd.img-$release-phase82" \
		"$target_assets/$dtb_name" \
		"$target_assets/vmlinuz-$release"
} > "$target_assets/DEPLOYMENT-MANIFEST.txt"

update-grub
grub-script-check /boot/grub/grub.cfg
if ! grep -q -- "--id 'sp11-phase82-set70'" /boot/grub/grub.cfg ||
	! grep -q "sp11_entry=7.1.3-phase82-set70" /boot/grub/grub.cfg ||
	! grep -q "mshw0485_touch.behavior_v2=1" /boot/grub/grub.cfg ||
	! grep -q "mshw0485_touch.reset_recovery_v2=1" /boot/grub/grub.cfg ||
	! grep -q "mshw0485_touch.host_fault_recovery=1" /boot/grub/grub.cfg ||
	! grep -q "mshw0485_touch.ready_quiesce=1" /boot/grub/grub.cfg ||
	! grep -q "mshw0485_touch.feature70_one_byte=1" /boot/grub/grub.cfg; then
	echo "generated GRUB configuration is missing the Phase 82 entry" >&2
	exit 1
fi
grub-reboot sp11-phase82-set70
deployment_complete=1

echo "installed isolated Phase 82 Windows-length SET70 test: sp11-phase82-set70"
echo "the saved GRUB default remains unchanged; next boot only is armed"
