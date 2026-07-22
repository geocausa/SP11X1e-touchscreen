#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
set -eu

# Promote a successfully booted Phase 91 image to the saved DMA baseline and
# reduce the active SP11 GRUB menu to baseline, previous-DMA, and FIFO entries.
# Historical menu scripts and all /boot experiment assets are preserved.

release=7.1.3-sp11-baseline1+
script_dir=$(dirname -- "$0")
root=$(CDPATH='' cd -- "$script_dir/.." && pwd)
phase91_assets=/boot/sp11-7.1.3-phase91-windows-cadence
phase75_assets=/boot/sp11-7.1.3-phase75-identity
fifo_assets=/boot/sp11-7.1.3-baseline1
baseline_source=$root/boot/60_sp11_713_dma_baseline
previous_source=$root/boot/61_sp11_713_dma_previous
fifo_source=$root/boot/47_sp11_713_fifo_fallback
baseline_target=/etc/grub.d/60_sp11_713_dma_baseline
previous_target=/etc/grub.d/61_sp11_713_dma_previous
fifo_target=/etc/grub.d/47_sp11_713_fifo_fallback
state_root=/var/lib/sp11-touchscreen
stamp=$(date -u +%Y%m%dT%H%M%SZ)
archive=$state_root/grub-archive/$stamp
record=$state_root/BASELINE-PROMOTION.txt
work=$(mktemp -d)
original=$work/original
entries_changed=0
promotion_complete=0

restore_on_failure()
{
	status=$?
	trap - EXIT
	set +e
	if [ "$entries_changed" = 1 ] && [ "$promotion_complete" != 1 ]; then
		find /etc/grub.d -maxdepth 1 -type f -name '[0-9][0-9]_sp11_*' \
			-delete
		find "$original" -maxdepth 1 -type f -exec cp -a {} /etc/grub.d/ \;
		update-grub >/dev/null 2>&1
	fi
	rm -rf "$work"
	exit "$status"
}
trap restore_on_failure EXIT
trap 'exit 1' HUP INT TERM

if [ "$(id -u)" -ne 0 ]; then
	echo "run as root" >&2
	exit 1
fi
if [ "$(uname -r)" != "$release" ]; then
	echo "boot the $release Phase 91 image before promotion" >&2
	exit 1
fi
if ! grep -q 'sp11_entry=7.1.3-phase91-windows-cadence' /proc/cmdline ||
	! grep -q 'mshw0485_touch.windows_read_cadence=1' /proc/cmdline; then
	echo "the running system is not the validated Phase 91 image" >&2
	exit 1
fi

dirty=$(git -C "$root" status --porcelain --untracked-files=normal |
	sed '\|^?? docs/SESSION_HANDOFF_2026-07-19_workspace.md$|d')
if [ -n "$dirty" ]; then
	echo "refusing to promote from a dirty source tree" >&2
	printf '%s\n' "$dirty" >&2
	exit 1
fi

stats=$(find /sys/devices -type f -name behavior_stats -print -quit)
if [ -z "$stats" ]; then
	echo "live touchscreen statistics were not found" >&2
	exit 1
fi
stat_value()
{
	sed -n "s/^$1=//p" "$stats"
}
if [ "$(stat_value windows_read_cadence)" != 1 ] ||
	[ "$(stat_value awaiting_ready_heat)" != 0 ] ||
	[ "$(stat_value ready_heat_frames)" -lt 1 ] ||
	[ "$(stat_value heat_frames)" -lt 1 ]; then
	echo "Phase 91 has not reached validated Heat input" >&2
	exit 1
fi
for field in heat_errors panel_resets recovery_failures \
	host_fault_recoveries irq_transport_errors irq_protocol_errors \
	irq_drain_overflows ready_verification_failures; do
	if [ "$(stat_value "$field")" != 0 ]; then
		echo "refusing promotion: $field is not zero" >&2
		exit 1
	fi
done

for file in \
	"$phase91_assets/vmlinuz-$release" \
	"$phase91_assets/initrd.img-$release-phase91" \
	"$phase91_assets/x1e80100-microsoft-denali-sp11-phase75.dtb" \
	"$phase91_assets/DEPLOYMENT-MANIFEST.txt" \
	"$phase75_assets/vmlinuz-$release" \
	"$phase75_assets/initrd.img-$release-phase75" \
	"$phase75_assets/x1e80100-microsoft-denali-sp11-phase75.dtb" \
	"$fifo_assets/vmlinuz-$release" \
	"$fifo_assets/initrd.img-$release" \
	"$fifo_assets/x1e80100-microsoft-denali-sp11-baseline1.dtb" \
	"$baseline_source" "$previous_source" "$fifo_source"; do
	if [ ! -f "$file" ]; then
		echo "missing required baseline or fallback file: $file" >&2
		exit 1
	fi
done
for token in \
	"mshw0485_touch.windows_init_parity=1" \
	"mshw0485_touch.parity_linux_power=1" \
	"mshw0485_touch.windows_read_cadence=1" \
	"mshw0485_touch.parity_cfu_inventory=1" \
	"mshw0485_touch.parity_heat_input=1" \
	"mshw0485_touch.behavior_v2=1"; do
	if ! grep -q "$token" "$baseline_source"; then
		echo "baseline entry is missing $token" >&2
		exit 1
	fi
done

mkdir -p "$original" "$archive"
find /etc/grub.d -maxdepth 1 -type f -name '[0-9][0-9]_sp11_*' \
	-exec cp -a {} "$original/" \;
find "$original" -maxdepth 1 -type f -exec cp -a {} "$archive/" \;
(
	cd "$archive"
	find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 |
		sort -z | xargs -0 sha256sum
) > "$archive/SHA256SUMS"

entries_changed=1
find /etc/grub.d -maxdepth 1 -type f -name '[0-9][0-9]_sp11_*' -delete
install -m 0755 "$fifo_source" "$fifo_target"
install -m 0755 "$baseline_source" "$baseline_target"
install -m 0755 "$previous_source" "$previous_target"

update-grub
grub-script-check /boot/grub/grub.cfg
for id in sp11-baseline-fifo sp11-dma-baseline sp11-dma-previous; do
	if ! grep -q -- "--id '$id'" /boot/grub/grub.cfg; then
		echo "generated GRUB configuration is missing $id" >&2
		exit 1
	fi
done
if grep -Eq -- "--id 'sp11-(phase|claude)" /boot/grub/grub.cfg; then
	echo "an experimental SP11 entry remains active" >&2
	exit 1
fi

grub-set-default sp11-dma-baseline
grub-editenv /boot/grub/grubenv unset next_entry
if ! grub-editenv /boot/grub/grubenv list |
	grep -q '^saved_entry=sp11-dma-baseline$'; then
	echo "saved GRUB baseline was not updated" >&2
	exit 1
fi

mkdir -p "$state_root"
commit=$(git -C "$root" rev-parse HEAD)
{
	echo "SP11 DMA baseline promotion"
	echo "UTC: $stamp"
	echo "source commit: $commit"
	echo "baseline image: Phase 91 Windows response cadence"
	echo "saved GRUB entry: sp11-dma-baseline"
	echo "previous DMA fallback: sp11-dma-previous"
	echo "FIFO fallback: sp11-baseline-fifo"
	echo "archived menu scripts: $archive"
	echo
	cat "$stats"
	echo
	sha256sum "$baseline_target" "$previous_target" "$fifo_target"
} > "$record"

promotion_complete=1
sync
echo "Phase 91 is now the saved SP11 DMA baseline"
echo "active custom entries: DMA baseline, previous DMA fallback, FIFO fallback"
echo "retired menu scripts archived at: $archive"
echo "promotion record: $record"
