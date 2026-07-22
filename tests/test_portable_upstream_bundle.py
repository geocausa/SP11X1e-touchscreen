# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "dts" / "upstream-7.1.3-mshw0485-phase91.dtso"
INSTALLER = ROOT / "scripts" / "install_upstream_713_phase91.sh"
PACKAGER = ROOT / "scripts" / "package_upstream_713_phase91.sh"
PHASE91_BOOT = ROOT / "boot" / "77_sp11_713_phase91_windows_cadence"


class PortableUpstreamBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay = OVERLAY.read_text(encoding="utf-8")
        cls.installer = INSTALLER.read_text(encoding="utf-8")
        cls.packager = PACKAGER.read_text(encoding="utf-8")
        cls.phase91_boot = PHASE91_BOOT.read_text(encoding="utf-8")

    def test_shell_scripts_parse(self):
        for script in (INSTALLER, PACKAGER):
            subprocess.run(
                ["bash", "-n", str(script)],
                check=True,
                capture_output=True,
                text=True,
            )

    def test_overlay_supplies_every_clean_upstream_gap(self):
        for token in (
            "&gpi_dma1",
            "&i2c10",
            "&tlmm",
            "&spi10",
            'status = "okay"',
            "qcom,biosref-qspi",
            "qcom,enable-gsi-dma",
            "dmas = <&gpi_dma1 0 2 4>, <&gpi_dma1 1 2 4>",
            'pins = "gpio49", "gpio50"',
            'function = "qup1_se2"',
            'compatible = "microsoft,mshw0485"',
            "interrupts = <51 8>",
            "interrupt-gpios = <&tlmm 51 1>",
            "power-gpios = <&tlmm 64 0>",
            "reset-gpios = <&tlmm 48 0>",
        ):
            self.assertIn(token, self.overlay)
        self.assertNotIn("mshw0485-biosref", self.overlay)

    def test_installer_builds_against_exact_running_kernel(self):
        for token in (
            "kdir=/lib/modules/$release/build",
            'target_release=$(cat "$kdir/include/config/kernel.release")',
            'config_is QCOM_GPI_DMA m',
            'config_is SPI_QCOM_GENI m',
            'ALLOW_UNTESTED_KERNEL=1',
            'expected_vermagic=$(modinfo -F vermagic "$stock_spi")',
            'actual_vermagic=$(modinfo -F vermagic',
        ):
            self.assertIn(token, self.installer)

    def test_installer_is_transactional_and_does_not_replace_stock_tree(self):
        self.assertIn("updates/sp11-phase91-portable", self.installer)
        self.assertIn('rm -rf "$stage_modules"', self.installer)
        self.assertIn('depmod -a "$release"', self.installer)
        self.assertIn('grub-reboot "$entry_id"', self.installer)
        self.assertNotIn("grub-set-default", self.installer)
        self.assertNotIn('cp -a "$stock_gpi"', self.installer)
        self.assertNotIn('cp -a "$stock_spi"', self.installer)
        self.assertIn("deployment_complete=0", self.installer)
        self.assertIn('rm -rf "$target_assets"', self.installer)

    def test_installer_rejects_unsafe_platforms(self):
        for token in (
            '"$(uname -m)" = aarch64',
            "microsoft,denali-oled",
            "Secure Boot is enabled",
            "CONFIG_MODULE_SIG_FORCE",
            "built-in cannot be replaced safely",
            "UKI/systemd-boot installs are unsupported",
            "already contains a touchscreen node",
        ):
            self.assertIn(token, self.installer)

    def test_phase91_options_match_validated_boot_entry(self):
        options = (
            "windows_init_parity=1",
            "parity_linux_power=1",
            "windows_read_cadence=1",
            "parity_display_bitmap=1",
            "parity_stitching_flag=0",
            "parity_hinge_angle=400",
            "parity_fast_host_id=400",
            "parity_report56_identity=0xbc,0xe6,0x4a,0x2e,0x86,0x78",
            "parity_report56_flag=0",
            "parity_cfu_inventory=1",
            "parity_cfu_offer=0x00,0x00,0x12,0x00,0x89,0x14,0x00,0x3f,"
            "0xff,0xff,0xff,0xff,0x04,0x04,0x75,0x00",
            "parity_heat_input=1",
            "behavior_v2=1",
            "host_fault_recovery=1",
            "ready_quiesce=1",
        )
        for option in options:
            full = f"mshw0485_touch.{option}"
            self.assertIn(full, self.installer)
            self.assertIn(full, self.phase91_boot)

    def test_release_is_source_only(self):
        self.assertIn("prebuilt modules included: no", self.packager)
        self.assertIn("-name '*.ko'", self.packager)
        self.assertIn("git archive --format=tar HEAD", self.packager)
        self.assertIn('output_name=$(basename -- "$output")', self.packager)
        self.assertIn('sha256sum "$output_name"', self.packager)


if __name__ == "__main__":
    unittest.main()
