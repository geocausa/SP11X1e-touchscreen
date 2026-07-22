#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
set -eu

script_dir=$(dirname -- "$0")
root=$(CDPATH='' cd -- "$script_dir/.." && pwd)
name=SP11X1e-touchscreen-dma-baseline-7.1.3-aarch64
output=${1:-"$root/dist/$name.tar.gz"}
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT HUP INT TERM

cd "$root"
dirty=$(git status --porcelain --untracked-files=normal |
	sed '\|^?? docs/SESSION_HANDOFF_2026-07-19_workspace.md$|d')
if [ -n "$dirty" ]; then
	echo "refusing to package an uncommitted tree" >&2
	printf '%s\n' "$dirty" >&2
	exit 1
fi

mkdir -p "$stage/$name/source" "$stage/$name/modules"
git archive --format=tar HEAD | tar -xf - -C "$stage/$name/source"

expected_vermagic="7.1.3-sp11-baseline1+ SMP preempt mod_unload modversions aarch64"
for module in gpi spi-geni-qcom mshw0485_touch; do
	path="phase55/modules/$module.ko"
	if [ ! -f "$path" ]; then
		echo "missing $path; build the matched DMA set first" >&2
		exit 1
	fi
	actual_vermagic=$(modinfo -F vermagic "$path")
	if [ "$actual_vermagic" != "$expected_vermagic" ]; then
		echo "$path has unexpected vermagic: $actual_vermagic" >&2
		exit 1
	fi
	cp "$path" "$stage/$name/modules/"
done

commit=$(git rev-parse HEAD)
timestamp=$(git show -s --format=%ct HEAD)
{
	echo "Surface Pro 11 MSHW0485 Phase 91 DMA touchscreen baseline"
	echo "source commit: $commit"
	echo "target vermagic: $expected_vermagic"
	echo "hardware: Surface Pro 11 OLED / Snapdragon X Elite"
	echo "transport: QSPI protocol 9 / GPI-DMA"
	echo "read cadence: Windows-measured 490-550 us and one response per IRQ"
	echo "hardware validation: 14,950 Heat frames across two cold boots"
	echo
	echo "Install only as a matched three-module set in a separate initramfs."
	echo "Retain the previous DMA and FIFO boot entries."
	echo "See source/docs/BUILD.md and source/docs/BASELINE_DMA_PHASE91.md."
} > "$stage/$name/BUILD-INFO.txt"

(
	cd "$stage/$name"
	find . -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)

mkdir -p "$(dirname -- "$output")"
tar --sort=name --owner=0 --group=0 --numeric-owner \
	--mtime="@$timestamp" -C "$stage" -czf "$output" "$name"
sha256sum "$output" > "$output.sha256"
echo "$output"
echo "$output.sha256"
