#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
set -eu

script_dir=$(dirname -- "$0")
root=$(CDPATH='' cd -- "$script_dir/.." && pwd)
name=SP11X1e-touchscreen-phase67-7.1.1-sp11-gpicmp1-aarch64
output=${1:-"$root/dist/$name.tar.gz"}
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT HUP INT TERM

cd "$root"
if ! git diff --quiet || ! git diff --cached --quiet; then
	echo "refusing to package an uncommitted tree" >&2
	exit 1
fi

mkdir -p "$stage/$name/source" "$stage/$name/modules"
git archive --format=tar HEAD | tar -xf - -C "$stage/$name/source"

expected_vermagic="7.1.1-sp11-gpicmp1+ SMP preempt mod_unload modversions aarch64"
for module in gpi spi-geni-qcom g6ts_biosref; do
	path="phase55/modules/$module.ko"
	if [ ! -f "$path" ]; then
		echo "missing $path; build the Phase 55/67 matched set first" >&2
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
	echo "Surface Pro 11 MSHW0485 touchscreen Phase 67"
	echo "source commit: $commit"
	echo "target vermagic: $expected_vermagic"
	echo "hardware: Surface Pro 11 OLED / Snapdragon X Elite"
	echo "firmware: MSHW0485 63.20.137 (0x3f001489)"
	echo "profile: 0x031a"
	echo
	echo "Install only as a matched three-module set in a separate initramfs."
	echo "Retain a known-good boot entry. See source/docs/BUILD.md and TESTING.md."
} > "$stage/$name/BUILD-INFO.txt"

sums="$stage/SHA256SUMS"
(
	cd "$stage/$name"
	find . -type f -print0 | sort -z | xargs -0 sha256sum > "$sums"
)
mv "$sums" "$stage/$name/SHA256SUMS"

mkdir -p "$(dirname -- "$output")"
tar --sort=name --owner=0 --group=0 --numeric-owner \
	--mtime="@$timestamp" -C "$stage" -czf "$output" "$name"
sha256sum "$output" > "$output.sha256"
echo "$output"
echo "$output.sha256"
