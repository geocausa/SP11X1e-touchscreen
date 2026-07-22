#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
set -eu

script_dir=$(dirname -- "$0")
root=$(CDPATH='' cd -- "$script_dir/.." && pwd)
name=SP11X1e-touchscreen-phase91-upstream-7.1.3-portable-aarch64
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

mkdir -p "$stage/$name"
git archive --format=tar HEAD | tar -xf - -C "$stage/$name"

for required in \
	scripts/install_upstream_713_phase91.sh \
	dts/upstream-7.1.3-mshw0485-phase91.dtso \
	docs/PORTABLE_UPSTREAM_713.md \
	phase55/modules/gpi.c \
	phase55/modules/spi-geni-qcom.c \
	phase55/modules/mshw0485_touch.c; do
	[ -f "$stage/$name/$required" ] || {
		echo "release archive is missing $required" >&2
		exit 1
	}
done

cat >"$stage/$name/install.sh" <<'EOF'
#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
exec "$root/scripts/install_upstream_713_phase91.sh" "$@"
EOF
chmod 0755 "$stage/$name/install.sh"

commit=$(git rev-parse HEAD)
timestamp=$(git show -s --format=%ct HEAD)
{
	echo "Surface Pro 11 OLED Phase 91 portable upstream installer"
	echo "source commit: $commit"
	echo "target: clean upstream Linux 7.1.3 on ARM64"
	echo "module policy: build all three matched modules on the target"
	echo "prebuilt modules included: no"
	echo "Microsoft binaries or firmware included: no"
	echo "boot policy: isolated one-shot GRUB test; saved default unchanged"
	echo "hardware caveat: clean-upstream deployment path awaits second-machine validation"
	echo
	echo "Read docs/PORTABLE_UPSTREAM_713.md, then run:"
	echo "  sudo ./install.sh --preflight-only"
	echo "  sudo ./install.sh"
} >"$stage/$name/BUILD-INFO.txt"

if find "$stage/$name" -type f \( -name '*.ko' -o -name '*.o' \) | grep -q .; then
	echo "portable source bundle unexpectedly contains compiled kernel objects" >&2
	exit 1
fi

manifest=$stage/SHA256SUMS
(
	cd "$stage/$name"
	find . -type f ! -name SHA256SUMS -print0 | sort -z |
		xargs -0 sha256sum >"$manifest"
)
mv "$manifest" "$stage/$name/SHA256SUMS"

mkdir -p "$(dirname -- "$output")"
tar --sort=name --owner=0 --group=0 --numeric-owner \
	--mtime="@$timestamp" -C "$stage" -czf "$output" "$name"
output_dir=$(dirname -- "$output")
output_name=$(basename -- "$output")
(
	cd "$output_dir"
	sha256sum "$output_name"
) >"$output.sha256"
echo "$output"
echo "$output.sha256"
