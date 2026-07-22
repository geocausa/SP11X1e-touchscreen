#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0
set -Eeuo pipefail

# Build and install an isolated Phase 91 boot from an otherwise unmodified
# upstream Linux 7.1.3 installation.  The running kernel and its stock module
# tree are never overwritten; temporary higher-priority modules are used only
# while constructing the dedicated initramfs.

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH='' cd -- "$script_dir/.." && pwd)
release=$(uname -r)
base_dtb=
kernel_image=
preflight_only=0
arm_next_boot=1

usage()
{
	cat <<'EOF'
Usage: sudo ./scripts/install_upstream_713_phase91.sh [options]

Options:
  --base-dtb PATH       pristine x1e80100-microsoft-denali-oled DTB
  --kernel-image PATH   kernel image to use (default: /boot/vmlinuz-$(uname -r))
  --preflight-only      validate the machine without building or installing
  --no-arm-next-boot    install the entry but do not select it for the next boot
  --help                show this help

The installer accepts only an ARM64 Surface Pro 11 OLED running a 7.1.3
kernel with complete matching build files. Secure Boot must be disabled and
the stock QCOM GPI-DMA and GENI-SPI drivers must both be modules.
EOF
}

die()
{
	echo "Phase 91 installer: $*" >&2
	exit 1
}

need()
{
	command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

config_is()
{
	grep -qx "CONFIG_$1=$2" "$kernel_config"
}

dt_string_has()
{
	local file=$1 node=$2 property=$3 expected=$4 value
	value=$(fdtget "$file" "$node" "$property" 2>/dev/null) || return 1
	case " $value " in
	*" $expected "*) return 0 ;;
	*) return 1 ;;
	esac
}

find_base_dtb()
{
	local candidate found=
	for candidate in \
		"/usr/lib/linux-image-$release/qcom/x1e80100-microsoft-denali-oled.dtb" \
		"/usr/lib/linux-image-$release/x1e80100-microsoft-denali-oled.dtb" \
		"/boot/dtbs/$release/qcom/x1e80100-microsoft-denali-oled.dtb" \
		"/boot/dtb-$release/qcom/x1e80100-microsoft-denali-oled.dtb" \
		"/lib/firmware/$release/device-tree/qcom/x1e80100-microsoft-denali-oled.dtb"; do
		[ -f "$candidate" ] || continue
		if [ -n "$found" ] && [ "$(readlink -f "$candidate")" != "$(readlink -f "$found")" ]; then
			die "multiple upstream DTBs found; select one with --base-dtb"
		fi
		found=$candidate
	done
	[ -n "$found" ] || die "cannot find the upstream Denali OLED DTB; use --base-dtb PATH"
	printf '%s\n' "$found"
}

secure_boot_enabled()
{
	local state variable byte
	if command -v mokutil >/dev/null 2>&1; then
		state=$(mokutil --sb-state 2>/dev/null || true)
		if grep -qi 'SecureBoot enabled' <<<"$state"; then
			return 0
		fi
	fi
	for variable in /sys/firmware/efi/efivars/SecureBoot-*; do
		[ -r "$variable" ] || continue
		byte=$(od -An -t u1 -j 4 -N 1 "$variable" 2>/dev/null | tr -d ' ')
		[ "$byte" = 1 ] && return 0
	done
	return 1
}

forbidden_module_blacklist()
{
	local token list name
	local -a boot_tokens
	read -r -a boot_tokens </proc/cmdline
	for token in "${boot_tokens[@]}"; do
		case "$token" in
		module_blacklist=*|modprobe.blacklist=*)
			list=${token#*=}
			for name in gpi spi-geni-qcom spi_geni_qcom mshw0485_touch; do
				case ",$list," in
				*",$name,"*) return 0 ;;
				esac
			done
			;;
		esac
	done
	return 1
}

while [ "$#" -gt 0 ]; do
	case "$1" in
	--base-dtb)
		[ "$#" -ge 2 ] || die "--base-dtb requires a path"
		base_dtb=$2
		shift 2
		;;
	--kernel-image)
		[ "$#" -ge 2 ] || die "--kernel-image requires a path"
		kernel_image=$2
		shift 2
		;;
	--preflight-only)
		preflight_only=1
		shift
		;;
	--no-arm-next-boot)
		arm_next_boot=0
		shift
		;;
	--help|-h)
		usage
		exit 0
		;;
	*)
		die "unknown option: $1"
		;;
	esac
done

[ "$(id -u)" -eq 0 ] || die "run this installer with sudo"
[ "$(uname -m)" = aarch64 ] || die "this bundle is only for ARM64"
case "$release" in
7.1.3*) ;;
*) die "running kernel is $release; this bundle is limited to Linux 7.1.3" ;;
esac

for command in awk cmp cp depmod dtc fdtoverlay fdtget findmnt grep \
	install make mkinitramfs modinfo nproc readlink sha256sum unmkinitramfs; do
	need "$command"
done

kdir=/lib/modules/$release/build
[ -d "$kdir" ] || die "matching kernel build directory is missing: $kdir"
[ -s "$kdir/Module.symvers" ] || die "matching Module.symvers is missing or empty under $kdir"
[ -r "$kdir/include/config/kernel.release" ] || die "kernel.release is missing under $kdir"
target_release=$(cat "$kdir/include/config/kernel.release")
[ "$target_release" = "$release" ] || die "build tree is for $target_release, not running $release"

if [ -r "$kdir/.config" ]; then
	kernel_config=$kdir/.config
elif [ -r "/boot/config-$release" ]; then
	kernel_config=/boot/config-$release
else
	die "cannot find the exact kernel configuration"
fi

config_is MODULES y || die "CONFIG_MODULES is not enabled"
config_is QCOM_GPI_DMA m || die "CONFIG_QCOM_GPI_DMA must be =m (built-in cannot be replaced safely)"
config_is SPI_QCOM_GENI m || die "CONFIG_SPI_QCOM_GENI must be =m (built-in cannot be replaced safely)"
if config_is MODULE_SIG_FORCE y; then
	die "CONFIG_MODULE_SIG_FORCE is enabled; this unsigned experimental bundle cannot load"
fi
secure_boot_enabled && die "Secure Boot is enabled; disable it before installing unsigned modules"
forbidden_module_blacklist && die "the running command line blacklists a required Phase 91 module"

stock_gpi=$(modinfo -k "$release" -n gpi 2>/dev/null) || die "cannot locate the stock gpi module"
stock_spi=$(modinfo -k "$release" -n spi-geni-qcom 2>/dev/null) || die "cannot locate the stock spi-geni-qcom module"
for module in "$stock_gpi" "$stock_spi"; do
	case "$module" in
	\(builtin\)) die "required controller driver is built into the kernel" ;;
	/lib/modules/"$release"/*) [ -f "$module" ] || die "stock module is missing: $module" ;;
	*) die "unexpected stock module path: $module" ;;
	esac
done
case "$stock_gpi $stock_spi" in
*sp11*|*mshw0485*) die "the running module tree is already SP11-modified; use a clean upstream install" ;;
esac
if modinfo -k "$release" mshw0485_touch >/dev/null 2>&1; then
	die "mshw0485_touch already exists in this module tree; expected clean upstream"
fi

compatible=$(tr '\0' ' ' </proc/device-tree/compatible 2>/dev/null || true)
case " $compatible " in
*" microsoft,denali-oled "*) ;;
*) die "running hardware is not the supported Surface Pro 11 OLED (microsoft,denali-oled)" ;;
esac

[ -n "$base_dtb" ] || base_dtb=$(find_base_dtb)
[ -f "$base_dtb" ] || die "base DTB does not exist: $base_dtb"
base_dtb=$(readlink -f "$base_dtb")
dt_string_has "$base_dtb" / compatible microsoft,denali-oled || \
	die "base DTB is not the Surface Pro 11 OLED tree"
for symbol in spi10 i2c10 gpi_dma1 tlmm qup_spi10_data_clk qup_spi10_cs; do
	fdtget "$base_dtb" /__symbols__ "$symbol" >/dev/null 2>&1 || \
		die "base DTB lacks required symbol: $symbol"
done
touch_path=/soc@0/geniqup@ac0000/spi@a88000/touchscreen@0
if fdtget "$base_dtb" "$touch_path" compatible >/dev/null 2>&1; then
	die "base DTB already contains a touchscreen node; expected pristine upstream 7.1.3"
fi
if fdtget "$base_dtb" /soc@0/geniqup@ac0000/spi@a88000 qcom,biosref-qspi >/dev/null 2>&1; then
	die "base DTB is already QSPI-modified; expected pristine upstream 7.1.3"
fi

[ -n "$kernel_image" ] || kernel_image=/boot/vmlinuz-$release
[ -f "$kernel_image" ] || die "kernel image does not exist: $kernel_image"
kernel_image=$(readlink -f "$kernel_image")

for required in \
	"$root/phase55/modules/Kbuild" \
	"$root/phase55/modules/gpi.c" \
	"$root/phase55/modules/spi-geni-qcom.c" \
	"$root/phase55/modules/mshw0485_touch.c" \
	"$root/dts/upstream-7.1.3-mshw0485-phase91.dtso" \
	"$root/packaging/initramfs-tools/hooks/sp11-mshw0485-touch"; do
	[ -f "$required" ] || die "bundle is incomplete: missing $required"
done

echo "Phase 91 preflight passed"
echo "  hardware: Surface Pro 11 OLED"
echo "  kernel: $release"
echo "  build tree: $kdir"
echo "  base DTB: $base_dtb"
echo "  kernel image: $kernel_image"
echo "  stock GPI: $stock_gpi"
echo "  stock GENI SPI: $stock_spi"

if [ "$preflight_only" = 1 ]; then
	exit 0
fi

for command in grub-script-check grub-reboot update-grub; do
	need "$command"
done
[ -d /etc/initramfs-tools ] || die "initramfs-tools is required (dracut-only systems are unsupported)"
[ -f /boot/grub/grub.cfg ] || die "GRUB configuration not found; UKI/systemd-boot installs are unsupported"

safe_release=$(printf '%s' "$release" | tr -c 'A-Za-z0-9_.+-' '-')
entry_id=sp11-phase91-portable-$safe_release
target_assets=/boot/sp11-$safe_release-phase91-portable
target_grub=/etc/grub.d/78_sp11_phase91_portable_$safe_release
stage_modules=/lib/modules/$release/updates/sp11-phase91-portable
[ ! -e "$target_assets" ] || die "target assets already exist: $target_assets"
[ ! -e "$target_grub" ] || die "target GRUB script already exists: $target_grub"
[ ! -e "$stage_modules" ] || die "temporary module staging path already exists: $stage_modules"

work=$(mktemp -d)
stage_active=0
deployment_started=0
deployment_complete=0

cleanup()
{
	local status=$?
	trap - EXIT
	set +e
	if [ "$stage_active" = 1 ]; then
		rm -rf "$stage_modules"
		depmod -a "$release"
	fi
	if [ "$status" -ne 0 ] && [ "$deployment_started" = 1 ] && [ "$deployment_complete" != 1 ]; then
		rm -rf "$target_assets"
		rm -f "$target_grub"
		update-grub >/dev/null 2>&1
	fi
	rm -rf "$work"
	exit "$status"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

cp -a "$root/phase55/modules" "$work/modules"
find "$work/modules" -maxdepth 1 -type f \
	\( -name '*.o' -o -name '*.ko' -o -name '*.mod' -o -name '*.mod.c' \
	   -o -name '*.cmd' -o -name 'Module.symvers' -o -name 'modules.order' \) \
	-delete
find "$work/modules" -maxdepth 1 -type f -name '.*.cmd' -delete

make -C "$work/modules" KDIR="$kdir" ALLOW_UNTESTED_KERNEL=1 \
	-j"$(nproc)"

for name in gpi spi-geni-qcom mshw0485_touch; do
	built=$work/modules/$name.ko
	[ -s "$built" ] || die "build did not produce $name.ko"
	built_release=$(modinfo -F vermagic "$built" | awk '{print $1}')
	[ "$built_release" = "$release" ] || die "$name.ko was built for $built_release"
done
expected_vermagic=$(modinfo -F vermagic "$stock_spi")
for name in gpi spi-geni-qcom mshw0485_touch; do
	actual_vermagic=$(modinfo -F vermagic "$work/modules/$name.ko")
	[ "$actual_vermagic" = "$expected_vermagic" ] || \
		die "$name.ko vermagic differs from the stock kernel: $actual_vermagic"
done
[ "$(modinfo -F name "$work/modules/mshw0485_touch.ko")" = mshw0485_touch ] || \
	die "touch client module identity is wrong"
for parameter in windows_init_parity parity_linux_power windows_read_cadence \
	parity_cfu_inventory parity_heat_input behavior_v2 host_fault_recovery ready_quiesce; do
	modinfo -p "$work/modules/mshw0485_touch.ko" | grep -q "^$parameter:" || \
		die "built client lacks Phase 91 parameter: $parameter"
done

dtc -@ -I dts -O dtb \
	-o "$work/upstream-7.1.3-mshw0485-phase91.dtbo" \
	"$root/dts/upstream-7.1.3-mshw0485-phase91.dtso"
fdtoverlay -i "$base_dtb" -o "$work/x1e80100-microsoft-denali-oled-phase91.dtb" \
	"$work/upstream-7.1.3-mshw0485-phase91.dtbo"
phase91_dtb=$work/x1e80100-microsoft-denali-oled-phase91.dtb

dt_string_has "$phase91_dtb" /soc@0/dma-controller@a00000 status okay || \
	die "generated DTB does not enable GPI DMA1"
dt_string_has "$phase91_dtb" /soc@0/geniqup@ac0000/spi@a88000 status okay || \
	die "generated DTB does not enable SPI10"
dt_string_has "$phase91_dtb" /soc@0/geniqup@ac0000/i2c@a88000 status disabled || \
	die "generated DTB does not disable the conflicting I2C10 personality"
dt_string_has "$phase91_dtb" "$touch_path" compatible microsoft,mshw0485 || \
	die "generated DTB lacks the production touchscreen identity"
for property in qcom,biosref-qspi qcom,enable-gsi-dma; do
	fdtget "$phase91_dtb" /soc@0/geniqup@ac0000/spi@a88000 "$property" >/dev/null 2>&1 || \
		die "generated DTB lacks required SPI property: $property"
done
dmas=$(fdtget -tx "$phase91_dtb" /soc@0/geniqup@ac0000/spi@a88000 dmas)
read -r -a dma_cells <<<"$dmas"
[ "${#dma_cells[@]}" -eq 8 ] && \
	[ "${dma_cells[1]}" = 0 ] && [ "${dma_cells[2]}" = 2 ] && [ "${dma_cells[3]}" = 4 ] && \
	[ "${dma_cells[5]}" = 1 ] && [ "${dma_cells[6]}" = 2 ] && [ "${dma_cells[7]}" = 4 ] || \
	die "generated DTB has incorrect QSPI DMA specifiers: $dmas"
[ "$(fdtget -tx "$phase91_dtb" "$touch_path" interrupts)" = "33 8" ] || \
	die "generated DTB has the wrong touch IRQ"
[ "$(fdtget "$phase91_dtb" /soc@0/pinctrl@f100000/g6ts-qspi-data23-state pins)" = \
  "gpio49 gpio50" ] || die "generated DTB has the wrong QSPI IO2/IO3 pins"
[ "$(fdtget "$phase91_dtb" /soc@0/pinctrl@f100000/g6ts-qspi-data23-state function)" = \
  "qup1_se2" ] || die "generated DTB has the wrong QSPI IO2/IO3 function"
pinctrl=$(fdtget -tx "$phase91_dtb" /soc@0/geniqup@ac0000/spi@a88000 pinctrl-0)
read -r -a pinctrl_cells <<<"$pinctrl"
[ "${#pinctrl_cells[@]}" -eq 3 ] || die "generated DTB does not select all three QSPI pin groups"
for specification in \
	"interrupt-gpios 33 1" \
	"power-gpios 40 0" \
	"reset-gpios 30 0"; do
	read -r property gpio flag <<<"$specification"
	cells=$(fdtget -tx "$phase91_dtb" "$touch_path" "$property")
	read -r -a gpio_cells <<<"$cells"
	[ "${#gpio_cells[@]}" -eq 3 ] && \
		[ "${gpio_cells[1]}" = "$gpio" ] && [ "${gpio_cells[2]}" = "$flag" ] || \
		die "generated DTB has wrong $property cells: $cells"
done
[ "$(fdtget "$phase91_dtb" "$touch_path" spi-max-frequency)" = 40000000 ] || \
	die "generated DTB has the wrong SPI frequency"

mkdir -m 0755 "$stage_modules"
stage_active=1
install -m 0644 "$work/modules/gpi.ko" "$stage_modules/gpi.ko"
install -m 0644 "$work/modules/spi-geni-qcom.ko" "$stage_modules/spi-geni-qcom.ko"
install -m 0644 "$work/modules/mshw0485_touch.ko" "$stage_modules/mshw0485_touch.ko"
depmod -a "$release"
for name in gpi spi-geni-qcom mshw0485_touch; do
	selected=$(modinfo -k "$release" -n "$name")
	[ "$selected" = "$stage_modules/$name.ko" ] || \
		die "depmod did not select the staged $name module: $selected"
done

cp -a /etc/initramfs-tools "$work/initramfs-tools"
rm -f "$work/initramfs-tools/hooks/sp11-g6ts"
install -m 0755 "$root/packaging/initramfs-tools/hooks/sp11-mshw0485-touch" \
	"$work/initramfs-tools/hooks/sp11-mshw0485-touch"
initrd=$work/initrd.img-$release-phase91-portable
mkinitramfs -d "$work/initramfs-tools" -o "$initrd" "$release"
unmkinitramfs "$initrd" "$work/initramfs-extracted"

for name in gpi spi-geni-qcom mshw0485_touch; do
	embedded=$(find "$work/initramfs-extracted" -type f -name "$name.ko*" -print -quit)
	[ -n "$embedded" ] || die "new initramfs is missing $name"
	[ "$(modinfo -F srcversion "$embedded")" = \
	  "$(modinfo -F srcversion "$work/modules/$name.ko")" ] || \
		die "new initramfs contains the wrong $name build"
	[ "$(modinfo -F vermagic "$embedded")" = "$expected_vermagic" ] || \
		die "embedded $name has mismatched vermagic"
done
if find "$work/initramfs-extracted" -type f -name 'g6ts_biosref.ko*' | grep -q .; then
	die "new initramfs unexpectedly contains the legacy FIFO client"
fi

# Remove the temporary module override before touching persistent boot assets.
rm -rf "$stage_modules"
depmod -a "$release"
stage_active=0
[ "$(modinfo -k "$release" -n gpi)" = "$stock_gpi" ] || \
	die "stock GPI module selection was not restored"
[ "$(modinfo -k "$release" -n spi-geni-qcom)" = "$stock_spi" ] || \
	die "stock GENI SPI module selection was not restored"

boot_mount=$(findmnt -T /boot -n -o TARGET)
boot_uuid=$(findmnt -T /boot -n -o UUID)
[ -n "$boot_mount" ] && [ -n "$boot_uuid" ] || die "cannot determine the /boot filesystem UUID"
asset_relative=${target_assets#"$boot_mount"}
asset_grub_path=/${asset_relative#/}

base_cmdline=()
have_root=0
read -r -a running_cmdline </proc/cmdline
for token in "${running_cmdline[@]}"; do
	case "$token" in
	BOOT_IMAGE=*|initrd=*|sp11_entry=*|mshw0485_touch.*|g6ts_biosref.*|spi_geni_qcom.sp11_*|gpi.sp11_*)
		continue
		;;
	root=*) have_root=1 ;;
	esac
	base_cmdline+=("$token")
done
[ "$have_root" = 1 ] || die "running command line has no root= argument"

phase91_args=(
	"sp11_entry=phase91-portable-upstream-7.1.3"
	"mshw0485_touch.windows_init_parity=1"
	"mshw0485_touch.parity_linux_power=1"
	"mshw0485_touch.windows_read_cadence=1"
	"mshw0485_touch.parity_display_bitmap=1"
	"mshw0485_touch.parity_stitching_flag=0"
	"mshw0485_touch.parity_hinge_angle=400"
	"mshw0485_touch.parity_fast_host_id=400"
	"mshw0485_touch.parity_report56_identity=0xbc,0xe6,0x4a,0x2e,0x86,0x78"
	"mshw0485_touch.parity_report56_flag=0"
	"mshw0485_touch.parity_cfu_inventory=1"
	"mshw0485_touch.parity_cfu_offer=0x00,0x00,0x12,0x00,0x89,0x14,0x00,0x3f,0xff,0xff,0xff,0xff,0x04,0x04,0x75,0x00"
	"mshw0485_touch.parity_heat_input=1"
	"mshw0485_touch.behavior_v2=1"
	"mshw0485_touch.host_fault_recovery=1"
	"mshw0485_touch.ready_quiesce=1"
)
cmdline="${base_cmdline[*]} ${phase91_args[*]}"

grub_source=$work/78_sp11_phase91_portable
cat >"$grub_source" <<EOF
#!/bin/sh
# SPDX-License-Identifier: GPL-2.0
exec tail -n +4 \$0
menuentry 'Ubuntu SP11 $release Phase 91 DMA (portable upstream test)' --id '$entry_id' --class ubuntu --class gnu-linux --class gnu --class os {
        load_video
        set gfxpayload=keep
        insmod gzio
        insmod part_gpt
        insmod ext2
        insmod fdt
        search --no-floppy --fs-uuid --set=root $boot_uuid
        devicetree $asset_grub_path/x1e80100-microsoft-denali-oled-phase91.dtb
        linux $asset_grub_path/vmlinuz-$release $cmdline
        initrd $asset_grub_path/initrd.img-$release-phase91-portable
}
EOF
chmod 0755 "$grub_source"

deployment_started=1
mkdir -m 0755 "$target_assets"
install -m 0644 "$kernel_image" "$target_assets/vmlinuz-$release"
install -m 0644 "$phase91_dtb" "$target_assets/x1e80100-microsoft-denali-oled-phase91.dtb"
install -m 0600 "$initrd" "$target_assets/initrd.img-$release-phase91-portable"
install -m 0755 "$grub_source" "$target_grub"

{
	echo "Surface Pro 11 OLED Phase 91 portable upstream deployment"
	echo "source commit: $(git -C "$root" rev-parse HEAD 2>/dev/null || echo release-archive)"
	echo "target kernel: $release"
	echo "target vermagic: $expected_vermagic"
	echo "base DTB: $base_dtb"
	echo "base DTB sha256: $(sha256sum "$base_dtb" | awk '{print $1}')"
	echo "stock GPI: $stock_gpi"
	echo "stock GENI SPI: $stock_spi"
	echo "installed module tree modified: no"
	echo "saved GRUB default modified: no"
	echo "hardware validation: Phase 91 on 7.1.3-sp11-baseline1+; clean-upstream port requires validation"
	sha256sum \
		"$target_assets/vmlinuz-$release" \
		"$target_assets/x1e80100-microsoft-denali-oled-phase91.dtb" \
		"$target_assets/initrd.img-$release-phase91-portable"
} >"$target_assets/DEPLOYMENT-MANIFEST.txt"

update-grub
grub-script-check /boot/grub/grub.cfg
for token in "$entry_id" \
	"mshw0485_touch.windows_read_cadence=1" \
	"mshw0485_touch.parity_heat_input=1" \
	"$asset_grub_path/x1e80100-microsoft-denali-oled-phase91.dtb"; do
	grep -q -- "$token" /boot/grub/grub.cfg || die "generated GRUB configuration is missing: $token"
done
if [ "$arm_next_boot" = 1 ]; then
	grub-reboot "$entry_id"
fi
deployment_complete=1

echo
echo "Installed isolated Phase 91 entry: $entry_id"
echo "The clean upstream kernel, stock modules, and saved GRUB default were not changed."
if [ "$arm_next_boot" = 1 ]; then
	echo "The next boot only is armed for Phase 91. Reboot when ready."
else
	echo "Select the Phase 91 portable entry manually from GRUB when ready."
fi
