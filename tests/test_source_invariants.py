# SPDX-License-Identifier: GPL-2.0

from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "phase55" / "modules" / "mshw0485_touch.c"
CONTROLLER = ROOT / "phase55" / "modules" / "spi-geni-qcom.c"
GPI = ROOT / "phase55" / "modules" / "gpi.c"
LEGACY_CLIENT = ROOT / "src" / "g6ts_biosref.c"
DMA_KBUILD = ROOT / "phase55" / "modules" / "Kbuild"
LIFECYCLE_PROFILE = ROOT / "phase55" / "modules" / "g6ts_lifecycle_profile.h"
ROOT_MAKEFILE = ROOT / "Makefile"
PHASE75_OVERLAY = ROOT / "dts" / "phase75-mshw0485-production.dtso"
PHASE75_DEPLOY = ROOT / "scripts" / "deploy_phase75_identity.sh"
PHASE76_BOOT = ROOT / "boot" / "63_sp11_713_phase76_behavior"
PHASE76_DEPLOY = ROOT / "scripts" / "deploy_phase76_behavior.sh"
PHASE77_BOOT = ROOT / "boot" / "64_sp11_713_phase77_recovery"
PHASE77_DEPLOY = ROOT / "scripts" / "deploy_phase77_recovery.sh"
PHASE78_BOOT = ROOT / "boot" / "65_sp11_713_phase78_storm_breaker"
PHASE78_DEPLOY = ROOT / "scripts" / "deploy_phase78_storm_breaker.sh"
PHASE80_BOOT = ROOT / "boot" / "67_sp11_713_phase80_host_recovery"
PHASE80_DEPLOY = ROOT / "scripts" / "deploy_phase80_host_recovery.sh"
PHASE81_BOOT = ROOT / "boot" / "68_sp11_713_phase81_ready_quiesce"
PHASE81_DEPLOY = ROOT / "scripts" / "deploy_phase81_ready_quiesce.sh"
PHASE82_BOOT = ROOT / "boot" / "69_sp11_713_phase82_set70"
PHASE82_DEPLOY = ROOT / "scripts" / "deploy_phase82_set70.sh"
PHASE84_BOOT = ROOT / "boot" / "70_sp11_713_phase84_init_parity"
PHASE84_DEPLOY = ROOT / "scripts" / "deploy_phase84_init_parity.sh"
PHASE85_BOOT = ROOT / "boot" / "70_sp11_713_phase85_cfu_parity"
PHASE86_BOOT = ROOT / "boot" / "71_sp11_713_phase86_windows_heat"
PHASE86_DEPLOY = ROOT / "scripts" / "deploy_phase86_windows_heat.sh"
PHASE87_BOOT = ROOT / "boot" / "72_sp11_713_phase87_linux_link_heat"
PHASE87_DEPLOY = ROOT / "scripts" / "deploy_phase87_linux_link_heat.sh"
PHASE88_BOOT = ROOT / "boot" / "74_sp11_713_phase88_linux_se_heat"
PHASE88_DEPLOY = ROOT / "scripts" / "deploy_phase88_linux_se_heat.sh"
PHASE89_BOOT = ROOT / "boot" / "75_sp11_713_phase89_linux_transport_heat"
PHASE89_DEPLOY = ROOT / "scripts" / "deploy_phase89_linux_transport_heat.sh"


def function_body(source: str, name: str) -> str:
    definition = re.search(
        rf"\b{re.escape(name)}\s*\([^;{{]*\)\s*\{{",
        source,
    )
    if definition is None:
        raise AssertionError(f"function definition not found: {name}")
    opening = source.index("{", definition.start())
    depth = 0
    for offset in range(opening, len(source)):
        if source[offset] == "{":
            depth += 1
        elif source[offset] == "}":
            depth -= 1
            if depth == 0:
                return source[opening : offset + 1]
    raise AssertionError(f"unterminated function {name}")


class SourceInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CLIENT.read_text(encoding="utf-8")
        cls.controller_source = CONTROLLER.read_text(encoding="utf-8")
        cls.gpi_source = GPI.read_text(encoding="utf-8")
        cls.legacy_source = LEGACY_CLIENT.read_text(encoding="utf-8")
        cls.dma_kbuild = DMA_KBUILD.read_text(encoding="utf-8")
        cls.lifecycle_profile = LIFECYCLE_PROFILE.read_text(encoding="utf-8")
        cls.root_makefile = ROOT_MAKEFILE.read_text(encoding="utf-8")
        cls.phase75_overlay = PHASE75_OVERLAY.read_text(encoding="utf-8")
        cls.phase75_deploy = PHASE75_DEPLOY.read_text(encoding="utf-8")
        cls.phase76_boot = PHASE76_BOOT.read_text(encoding="utf-8")
        cls.phase76_deploy = PHASE76_DEPLOY.read_text(encoding="utf-8")
        cls.phase77_boot = PHASE77_BOOT.read_text(encoding="utf-8")
        cls.phase77_deploy = PHASE77_DEPLOY.read_text(encoding="utf-8")
        cls.phase78_boot = PHASE78_BOOT.read_text(encoding="utf-8")
        cls.phase78_deploy = PHASE78_DEPLOY.read_text(encoding="utf-8")
        cls.phase80_boot = PHASE80_BOOT.read_text(encoding="utf-8")
        cls.phase80_deploy = PHASE80_DEPLOY.read_text(encoding="utf-8")
        cls.phase81_boot = PHASE81_BOOT.read_text(encoding="utf-8")
        cls.phase81_deploy = PHASE81_DEPLOY.read_text(encoding="utf-8")
        cls.phase82_boot = PHASE82_BOOT.read_text(encoding="utf-8")
        cls.phase82_deploy = PHASE82_DEPLOY.read_text(encoding="utf-8")
        cls.phase84_boot = PHASE84_BOOT.read_text(encoding="utf-8")
        cls.phase84_deploy = PHASE84_DEPLOY.read_text(encoding="utf-8")
        cls.phase85_boot = PHASE85_BOOT.read_text(encoding="utf-8")
        cls.phase86_boot = PHASE86_BOOT.read_text(encoding="utf-8")
        cls.phase86_deploy = PHASE86_DEPLOY.read_text(encoding="utf-8")
        cls.phase87_boot = PHASE87_BOOT.read_text(encoding="utf-8")
        cls.phase87_deploy = PHASE87_DEPLOY.read_text(encoding="utf-8")
        cls.phase88_boot = PHASE88_BOOT.read_text(encoding="utf-8")
        cls.phase88_deploy = PHASE88_DEPLOY.read_text(encoding="utf-8")
        cls.phase89_boot = PHASE89_BOOT.read_text(encoding="utf-8")
        cls.phase89_deploy = PHASE89_DEPLOY.read_text(encoding="utf-8")

    def test_default_build_is_the_production_dma_set(self):
        self.assertIn("all: production", self.root_makefile)
        self.assertIn("production: phase55", self.root_makefile)
        self.assertIn("legacy-fifo: phase52", self.root_makefile)

    def test_phase75_dtb_is_reproducible_from_fifo_baseline(self):
        for token in (
            "&spi10",
            "qcom,enable-gsi-dma",
            "dmas = <&gpi_dma1 0 2 4>, <&gpi_dma1 1 2 4>",
            'dma-names = "tx", "rx"',
            'compatible = "microsoft,mshw0485"',
        ):
            self.assertIn(token, self.phase75_overlay)
        self.assertIn("base_fifo_dtb", self.phase75_deploy)
        self.assertNotIn("prebuilt/", self.phase75_deploy)

    def test_production_identity_is_distinct_from_legacy_fifo(self):
        self.assertIn('G6TS_NAME\t\t\t"mshw0485-touch"', self.source)
        self.assertIn('compatible = "microsoft,mshw0485"', self.source)
        self.assertNotIn('compatible = "microsoft,mshw0485-biosref"', self.source)
        self.assertIn("obj-m += mshw0485_touch.o", self.dma_kbuild)
        self.assertNotIn("obj-m += g6ts_biosref.o", self.dma_kbuild)
        self.assertIn('compatible = "microsoft,mshw0485-biosref"',
                      self.legacy_source)

    def test_recovery_uses_hardware_validated_minimal_order(self):
        body = function_body(self.source, "g6ts_full_reinitialize_locked")
        ordered = (
            "g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x05",
            "g6ts_dma_feature_exchange(ts, GET_FEATURE, 0x70",
            "g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x70",
            "g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x56",
        )
        positions = [body.index(item) for item in ordered]
        self.assertEqual(positions, sorted(positions))

    def test_cold_boot_only_setup_is_not_replayed_during_recovery(self):
        body = function_body(self.source, "g6ts_full_reinitialize_locked")
        forbidden = (
            "GET_FEATURE, 0x60",
            "OUTPUT_REPORT, 0x65",
            "GET_FEATURE, 0x06",
            "GET_FEATURE, 0x73",
        )
        for command in forbidden:
            self.assertNotIn(command, body)

        # KDNET proves that report 0x09 belongs to Windows initialization and
        # reset recovery. Phase 72 proves only that the combined Linux sequence
        # containing this short report eliminated the observed reset storm.
        self.assertIn("OUTPUT_REPORT, 0x09", body)

        for removed_symbol in (
            "g6ts_output65",
            "g6ts_output09_a1_template",
            "g6ts_output09_a5_template",
            "g6ts_etw_firmware_version",
        ):
            self.assertNotIn(removed_symbol, self.source)

    def test_windows_init_parity_gates_each_unresolved_owner(self):
        self.assertIn("static bool g6ts_windows_init_parity;", self.source)
        self.assertIn(
            "module_param_named(windows_init_parity, "
            "g6ts_windows_init_parity, bool, 0444)",
            self.source,
        )
        body = function_body(self.source, "g6ts_windows_cold_attach_locked")
        get73 = body.index("GET_FEATURE, 0x73")
        get06 = body.index("GET_FEATURE, 0x06")
        feedback_boundary = body.index("G6TS_INIT_WINDOWS_FEEDBACK_REQUIRED")
        a1 = body.index("G6TS_INIT_WINDOWS_FEEDBACK_A1")
        a5 = body.index("G6TS_INIT_WINDOWS_FEEDBACK_A5")
        set05 = body.index("G6TS_INIT_WINDOWS_SET_FEATURE05")
        config_boundary = body.index(
            "G6TS_INIT_WINDOWS_CONFIG_OWNER_REQUIRED"
        )
        get70 = body.index("G6TS_INIT_WINDOWS_GET_FEATURE70")
        set70 = body.index("G6TS_INIT_WINDOWS_SET_FEATURE70")
        set56 = body.index("G6TS_INIT_WINDOWS_SET_FEATURE56")
        cfu_boundary = body.index("G6TS_INIT_WINDOWS_CFU_OWNER_REQUIRED")
        self.assertLess(get73, get06)
        self.assertLess(get06, feedback_boundary)
        self.assertLess(feedback_boundary, a1)
        self.assertLess(a1, a5)
        self.assertLess(a5, set05)
        self.assertLess(set05, config_boundary)
        self.assertLess(config_boundary, get70)
        self.assertLess(get70, set70)
        self.assertLess(set70, set56)
        self.assertLess(set56, cfu_boundary)
        self.assertIn("ts->mode_enabled = false", body)
        for forbidden in (
            "0x60",
            "0x65",
        ):
            self.assertNotIn(forbidden, body)

        self.assertIn("content[0] != 0xfe || content[1] != 0xff", body)
        self.assertIn("ts->last_content_len != 1", body)
        self.assertIn(
            "ts->body[HIDSPI_INPUT_BODY_HEADER_SIZE] != 0x02", body
        )
        self.assertIn("msleep(G6TS_WINDOWS_CONFIG_DELAY_MS)", body)
        self.assertIn("g6ts_parity_report56_identity", body)
        self.assertIn("g6ts_parity_report56_flag", body)

        config_provider = function_body(
            self.source, "g6ts_windows_config_provider_valid"
        )
        self.assertIn("g6ts_parity_report56_identity_count", config_provider)
        self.assertIn("G6TS_WINDOWS_REPORT56_ID_LEN", config_provider)

    def test_windows_feedback_builders_match_recovered_offsets(self):
        a1 = function_body(self.source, "g6ts_build_windows_feedback_a1")
        for token in (
            "content[0] = 0x8e",
            "content[1] = 0xa1",
            "content[2] = g6ts_parity_display_bitmap",
            "content[3] = g6ts_parity_stitching_flag",
            "put_unaligned_le32(g6ts_parity_hinge_angle, &content[4])",
            "put_unaligned_le16(g6ts_parity_fast_host_id, &content[40])",
        ):
            self.assertIn(token, a1)

        a5 = function_body(self.source, "g6ts_build_windows_feedback_a5")
        for token in (
            "content[0] = 0x8e",
            "content[1] = 0xa5",
            "content[2] = 0",
            "content[3] = BIT(1)",
            "put_unaligned_le16(g6ts_parity_fast_host_id, &content[39])",
            "put_unaligned_le16(0x0040, &content[46])",
        ):
            self.assertIn(token, a5)

    def test_windows_cfu_inventory_is_bounded_and_has_no_payload_path(self):
        self.assertIn("static bool g6ts_parity_cfu_inventory;", self.source)
        self.assertIn(
            "module_param_named(parity_cfu_inventory, "
            "g6ts_parity_cfu_inventory, bool, 0444)",
            self.source,
        )
        body = function_body(self.source, "g6ts_windows_cfu_inventory_locked")
        ordered = (
            "G6TS_INIT_WINDOWS_CFU_GET_VERSION",
            "G6TS_INIT_WINDOWS_CFU_START_TRANSACTION",
            "G6TS_INIT_WINDOWS_CFU_START_LIST",
            "G6TS_INIT_WINDOWS_CFU_OFFER",
            "G6TS_INIT_WINDOWS_CFU_END_LIST",
            "G6TS_INIT_WINDOWS_FINAL_FEATURE73",
            "G6TS_INIT_WINDOWS_HEAT_OWNER_REQUIRED",
        )
        positions = [body.index(item) for item in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("GET_FEATURE, 0x60", body)
        self.assertIn("content[8] != 0 || content[12] != 0x02", body)
        self.assertIn("ts->parity_cfu_branch_required = true", body)
        self.assertIn("GET_FEATURE, 0x73", body)
        self.assertNotIn("FIRMWARE_UPDATE_CONTENT", self.source)
        self.assertNotIn("g6ts_cfu_payload", self.source)

        sender = function_body(self.source, "g6ts_windows_cfu_send_locked")
        self.assertIn("OUTPUT_REPORT, 0x65", sender)
        self.assertIn("DATA, 0x65", sender)
        self.assertIn("G6TS_WINDOWS_CFU_OFFER_LEN", sender)

        provider = function_body(
            self.source, "g6ts_windows_cfu_provider_valid"
        )
        self.assertIn("g6ts_sp11_cfu_offer", provider)
        self.assertIn("g6ts_parity_cfu_offer_count", provider)

    def test_windows_init_parity_validates_exact_sp11_descriptor(self):
        body = function_body(
            self.source, "g6ts_validate_sp11_device_descriptor"
        )
        for token in (
            "G6TS_SP11_REPORT_DESCRIPTOR_LEN",
            "G6TS_SP11_MAX_INPUT_LEN",
            "G6TS_SP11_MAX_OUTPUT_LEN",
            "G6TS_SP11_MAX_FRAGMENT_LEN",
            "G6TS_SP11_VENDOR_ID",
            "G6TS_SP11_PRODUCT_ID",
            "G6TS_SP11_VERSION_ID",
            "G6TS_SP11_DESCRIPTOR_FLAGS",
        ):
            self.assertIn(token, body)

    def test_windows_init_parity_uses_recovered_acpi_power_order(self):
        power = function_body(self.source, "g6ts_windows_power_on")
        for token in (
            'g6ts_acpi_method(&ts->spi->dev, "_PS0")',
            'g6ts_acpi_method(&ts->spi->dev, "_RST")',
            "gpiod_set_value_cansleep(ts->power_gpio, 1)",
            "msleep(500)",
            "gpiod_set_value_cansleep(ts->reset_gpio, 0)",
            "msleep(300)",
        ):
            self.assertIn(token, power)
        self.assertLess(
            power.index("gpiod_set_value_cansleep(ts->power_gpio, 1)"),
            power.index("msleep(500)"),
        )
        self.assertLess(
            power.index("gpiod_set_value_cansleep(ts->reset_gpio, 0)"),
            power.index("msleep(300)"),
        )

        recovery = function_body(self.source, "g6ts_full_reinitialize_locked")
        self.assertIn("g6ts_windows_power_on(ts) : g6ts_power_on(ts)", recovery)

    def test_phase84_is_input_disabled_and_one_shot(self):
        for token in (
            "sp11-phase84-init-parity",
            "sp11_entry=7.1.3-phase84-init-parity",
            "spi_geni_qcom.sp11_windows_se_init=1",
            "gpi.sp11_windows_ring_layout=1",
            "mshw0485_touch.windows_init_parity=1",
            "mshw0485_touch.parity_display_bitmap=1",
            "mshw0485_touch.parity_stitching_flag=0",
            "mshw0485_touch.parity_hinge_angle=400",
            "mshw0485_touch.parity_fast_host_id=400",
            "mshw0485_touch.parity_report56_identity="
            "0xbc,0xe6,0x4a,0x2e,0x86,0x78",
            "mshw0485_touch.parity_report56_flag=0",
        ):
            self.assertIn(token, self.phase84_boot)
        self.assertNotIn("behavior_v2=1", self.phase84_boot)
        self.assertNotIn("windows_orchestrator=1", self.phase84_boot)
        self.assertIn("grub-reboot sp11-phase84-init-parity", self.phase84_deploy)
        self.assertIn("saved GRUB default remains unchanged", self.phase84_deploy)
        self.assertNotIn("grub-set-default", self.phase84_deploy)

    def test_phase85_is_exact_cfu_inventory_only(self):
        required = (
            "sp11-phase85-cfu-parity",
            "sp11_entry=7.1.3-phase85-cfu-parity",
            "spi_geni_qcom.sp11_windows_se_init=1",
            "gpi.sp11_windows_ring_layout=1",
            "mshw0485_touch.windows_init_parity=1",
            "mshw0485_touch.parity_cfu_inventory=1",
            "mshw0485_touch.parity_cfu_offer="
            "0x00,0x00,0x12,0x00,0x89,0x14,0x00,0x3f,"
            "0xff,0xff,0xff,0xff,0x04,0x04,0x75,0x00",
        )
        for token in required:
            self.assertIn(token, self.phase85_boot)
        self.assertNotIn("behavior_v2=1", self.phase85_boot)
        self.assertNotIn("windows_orchestrator=1", self.phase85_boot)
        self.assertNotIn("parity_cfu_inventory", self.phase84_boot)

    def test_phase86_admits_heat_only_after_complete_parity_chronology(self):
        required = (
            "sp11-phase86-windows-heat",
            "sp11_entry=7.1.3-phase86-windows-heat",
            "spi_geni_qcom.sp11_windows_se_init=1",
            "gpi.sp11_windows_ring_layout=1",
            "mshw0485_touch.windows_init_parity=1",
            "mshw0485_touch.parity_cfu_inventory=1",
            "mshw0485_touch.parity_heat_input=1",
            "mshw0485_touch.behavior_v2=1",
            "mshw0485_touch.host_fault_recovery=1",
            "mshw0485_touch.ready_quiesce=1",
        )
        for token in required:
            self.assertIn(token, self.phase86_boot)
        self.assertIn(
            "grub-reboot sp11-phase86-windows-heat", self.phase86_deploy
        )
        self.assertNotIn("grub-set-default", self.phase86_deploy)

        cfu = function_body(self.source, "g6ts_windows_cfu_inventory_locked")
        self.assertLess(
            cfu.index("G6TS_INIT_WINDOWS_FINAL_FEATURE73"),
            cfu.index("if (!g6ts_parity_heat_input)"),
        )
        self.assertLess(
            cfu.index("if (!g6ts_parity_heat_input)"),
            cfu.index("ts->mode_enabled = true"),
        )
        self.assertIn("ts->awaiting_ready_heat = true", cfu)

        probe = function_body(self.source, "g6ts_probe")
        self.assertIn(
            "(!g6ts_windows_init_parity || !g6ts_parity_cfu_inventory)",
            probe,
        )

    def test_phase87_is_phase86_plus_linux_qspi_link(self):
        for token in (
            "sp11-phase87-linux-link-heat",
            "sp11_entry=7.1.3-phase87-linux-link-heat",
            "spi_geni_qcom.sp11_windows_se_init=1",
            "gpi.sp11_windows_ring_layout=1",
            "gpi.sp11_qspi_linux_link=1",
            "mshw0485_touch.windows_init_parity=1",
            "mshw0485_touch.parity_cfu_inventory=1",
            "mshw0485_touch.parity_heat_input=1",
            "mshw0485_touch.behavior_v2=1",
        ):
            self.assertIn(token, self.phase87_boot)
        self.assertNotIn("sp11_qspi_linux_link=1", self.phase84_boot)
        self.assertNotIn("sp11_qspi_linux_link=1", self.phase86_boot)
        self.assertIn(
            "grub-reboot sp11-phase87-linux-link-heat",
            self.phase87_deploy,
        )
        self.assertNotIn("grub-set-default", self.phase87_deploy)

    def test_phase88_restores_only_linux_se_initialization(self):
        shared = (
            "gpi.sp11_windows_ring_layout=1",
            "gpi.sp11_qspi_linux_link=1",
            "mshw0485_touch.windows_init_parity=1",
            "mshw0485_touch.parity_cfu_inventory=1",
            "mshw0485_touch.parity_heat_input=1",
            "mshw0485_touch.behavior_v2=1",
            "mshw0485_touch.host_fault_recovery=1",
            "mshw0485_touch.ready_quiesce=1",
        )
        for token in shared:
            self.assertIn(token, self.phase87_boot)
            self.assertIn(token, self.phase88_boot)
        self.assertIn("spi_geni_qcom.sp11_windows_se_init=1", self.phase87_boot)
        self.assertNotIn(
            "spi_geni_qcom.sp11_windows_se_init=1", self.phase88_boot
        )
        self.assertIn("sp11-phase88-linux-se-heat", self.phase88_boot)
        self.assertIn(
            "grub-reboot sp11-phase88-linux-se-heat",
            self.phase88_deploy,
        )
        self.assertNotIn("grub-set-default", self.phase88_deploy)

    def test_phase89_restores_phase75_gpi_geometry(self):
        shared = (
            "mshw0485_touch.windows_init_parity=1",
            "mshw0485_touch.parity_cfu_inventory=1",
            "mshw0485_touch.parity_heat_input=1",
            "mshw0485_touch.behavior_v2=1",
            "mshw0485_touch.host_fault_recovery=1",
            "mshw0485_touch.ready_quiesce=1",
        )
        for token in shared:
            self.assertIn(token, self.phase88_boot)
            self.assertIn(token, self.phase89_boot)
        for token in (
            "spi_geni_qcom.sp11_windows_se_init=1",
            "gpi.sp11_windows_ring_layout=1",
            "gpi.sp11_qspi_linux_link=1",
        ):
            self.assertNotIn(token, self.phase89_boot)
        self.assertIn("sp11-phase89-linux-transport-heat", self.phase89_boot)
        self.assertIn(
            "grub-reboot sp11-phase89-linux-transport-heat",
            self.phase89_deploy,
        )
        self.assertNotIn("grub-set-default", self.phase89_deploy)

    def test_windows_controller_init_is_guarded_and_exactly_ordered(self):
        body = function_body(
            self.controller_source,
            "spi_geni_sp11_qspi_prepare_windows_hw",
        )
        self.assertIn("GENI_IF_DISABLE_RO", body)
        self.assertIn("FIFO_IF_DISABLE", body)
        writes = (
            "GENI_DMA_MODE_EN, se->base + SE_GENI_DMA_MODE_EN",
            "0, se->base + SE_GSI_IRQ_EN",
            "0xf, se->base + SE_GSI_EVENT_EN",
            "SP11_QSPI_M_IRQ_INIT, se->base + SE_GENI_M_IRQ_EN",
            "SP11_QSPI_S_IRQ_INIT, se->base + SE_GENI_S_IRQ_EN",
            "0xf, se->base + SE_DMA_TX_IRQ_MSK",
            "0xd, se->base + SE_DMA_TX_IRQ_EN",
            "0xfff, se->base + SE_DMA_RX_IRQ_MSK",
            "0x1d, se->base + SE_DMA_RX_IRQ_EN",
            "SP11_QSPI_M_IRQ_CLEAR, se->base + SE_GENI_M_IRQ_CLEAR",
            "SP11_QSPI_S_IRQ_CLEAR, se->base + SE_GENI_S_IRQ_CLEAR",
            "0xf, se->base + SE_DMA_TX_IRQ_CLR",
            "0xfff, se->base + SE_DMA_RX_IRQ_CLR",
        )
        positions = [body.index(write) for write in writes]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("module_param(sp11_windows_se_init, bool, 0444)",
                      self.controller_source)

        init = function_body(self.controller_source, "spi_geni_init")
        self.assertIn(
            "if (!sp11_windows_se_init || !spi_geni_is_sp11_qspi(mas))",
            init,
        )
        self.assertIn("spi_geni_sp11_qspi_prepare_windows_hw(mas)", init)

    def test_windows_gpi_ring_geometry_is_exact_and_opt_in(self):
        self.assertIn("#define SP11_WINDOWS_CHAN_TRES\t16", self.gpi_source)
        self.assertIn("#define SP11_WINDOWS_EVENT_TRES\t32", self.gpi_source)
        self.assertIn(
            "module_param(sp11_windows_ring_layout, bool, 0444)",
            self.gpi_source,
        )
        alloc = function_body(self.gpi_source, "gpi_alloc_chan_resources")
        self.assertIn("gchan->protocol == QCOM_GPI_QSPI", alloc)
        self.assertIn("elements = SP11_WINDOWS_CHAN_TRES", alloc)
        init = function_body(self.gpi_source, "gpi_ch_init")
        self.assertIn("elements = SP11_WINDOWS_EVENT_TRES", init)
        tre = function_body(self.gpi_source, "gpi_create_spi_tre")
        self.assertIn(
            "module_param(sp11_qspi_linux_link, bool, 0444)",
            self.gpi_source,
        )
        self.assertIn(
            "(!sp11_windows_ring_layout || sp11_qspi_linux_link)",
            tre,
        )

    def test_assignment_initializes_every_output_slot(self):
        body = function_body(self.source, "g6ts_assign_tracks")
        initialization = body.index("contact_slots[i] = -1")
        early_return = body.index("if (!active_count || !count)")
        self.assertLess(initialization, early_return)

    def test_phase70_policy_is_opt_in_and_read_only(self):
        self.assertIn("static bool g6ts_windows_orchestrator;", self.source)
        self.assertIn(
            "module_param_named(windows_orchestrator, "
            "g6ts_windows_orchestrator, bool, 0444)",
            self.source,
        )

    def test_phase70_assignment_uses_sensor_space_and_strict_radius(self):
        body = function_body(self.source, "g6ts_track_distance")
        for token in (
            "sensor_x_q24",
            "sensor_y_q24",
            "G6TS_WINDOWS_ASSIGN_X_SCALE_Q24",
            "G6TS_WINDOWS_ASSIGN_Y_SCALE_Q24",
            "squared >= G6TS_WINDOWS_ASSIGN_RADIUS",
        ):
            self.assertIn(token, body)

    def test_phase70_direct_coordinates_do_not_use_scalar_smoothing(self):
        body = function_body(self.source, "g6ts_update_track")
        start = body.index("if (g6ts_windows_orchestrator)")
        fallback = body.index("} else {", start)
        windows_branch = body[start:fallback]
        self.assertIn("track->output_x = contact->x", windows_branch)
        self.assertIn("track->output_y = contact->y", windows_branch)
        self.assertNotIn("g6ts_filter_coordinate", windows_branch)

    def test_phase76_profile_is_opt_in_and_transport_independent(self):
        self.assertIn("static bool g6ts_behavior_v2;", self.source)
        self.assertIn(
            "module_param_named(behavior_v2, g6ts_behavior_v2, bool, 0444)",
            self.source,
        )
        probe = function_body(self.source, "g6ts_probe")
        self.assertIn(
            "g6ts_behavior_v2 && g6ts_windows_orchestrator", probe
        )
        recovery = function_body(self.source, "g6ts_full_reinitialize_locked")
        self.assertNotIn("g6ts_behavior_v2", recovery)

    def test_phase76_uses_proven_geometry_and_two_frame_gate(self):
        centroid = function_body(self.source, "g6ts_phase76_output_centroid")
        self.assertIn("G6TS_WINDOWS_CENTROID_BASELINE", centroid)
        self.assertIn("contact->output_x", centroid)
        self.assertIn("contact->output_y", centroid)

        distance = function_body(self.source, "g6ts_track_distance")
        self.assertIn(
            "g6ts_windows_orchestrator || g6ts_behavior_v2", distance
        )
        confirmation = function_body(
            self.source, "g6ts_confirmation_requirement"
        )
        self.assertIn("G6TS_BEHAVIOR_CONFIRM_NORMAL", confirmation)

        update = function_body(self.source, "g6ts_update_track")
        phase76 = update[update.index("else if (g6ts_behavior_v2)") :]
        self.assertIn("contact->output_x", phase76)
        self.assertNotIn("g6ts_filter_coordinate", phase76.split("} else {")[0])

    def test_phase76_exposes_read_only_behavior_counters(self):
        show = function_body(self.source, "behavior_stats_show")
        for token in (
            "last_header=%4ph",
            "last_class=%u",
            "last_content_id=%u",
            "last_content_len=%u",
            "heat_frames",
            "components",
            "accepted_contacts",
            "assignment_matches",
            "processing_average_ns",
            "panel_resets",
        ):
            self.assertIn(token, show)
        self.assertIn("static DEVICE_ATTR_RO(behavior_stats)", self.source)

    def test_phase76_deployment_is_isolated_from_phase75(self):
        for token in (
            "sp11-phase76-behavior",
            "sp11_entry=7.1.3-phase76-behavior",
            "mshw0485_touch.behavior_v2=1",
        ):
            self.assertIn(token, self.phase76_boot)
        self.assertIn("phase75_assets", self.phase76_deploy)
        self.assertIn("grub-reboot sp11-phase76-behavior", self.phase76_deploy)
        self.assertIn("saved GRUB default remains unchanged", self.phase76_deploy)
        self.assertNotIn("grub-set-default", self.phase76_deploy)

    def test_phase77_software_recovery_is_opt_in_and_gated(self):
        self.assertIn("static bool g6ts_reset_recovery_v2;", self.source)
        self.assertIn(
            "module_param_named(reset_recovery_v2, "
            "g6ts_reset_recovery_v2, bool, 0444)",
            self.source,
        )

        irq = function_body(self.source, "g6ts_interrupt_thread")
        self.assertIn("g6ts_note_panel_reset_locked(ts, true)", irq)
        reset = function_body(self.source, "g6ts_note_panel_reset_locked")
        self.assertIn("G6TS_RECOVERY_SOFTWARE", reset)
        self.assertIn("reset_notifications++", reset)
        self.assertIn("g6ts_release_contacts", reset)
        reader = function_body(self.source, "g6ts_dma_read_response")
        self.assertIn("if (READ_ONCE(ts->mode_enabled))", reader)

        data_report = function_body(self.source, "g6ts_handle_data_report")
        self.assertIn("ts->awaiting_ready_heat", data_report)
        self.assertIn("ts->ready_heat_frames++", data_report)
        self.assertIn("g6ts_report_heat_contacts", data_report)

        feature = function_body(self.source, "g6ts_dma_feature_exchange")
        expected = function_body(self.source, "g6ts_recovery_read_expected")
        for body in (feature, expected):
            self.assertIn("g6ts_note_panel_reset_locked(ts, false)", body)
            self.assertIn("return -EPIPE", body)

        recovery = function_body(self.source, "g6ts_full_reinitialize_locked")
        hardware = recovery.index("path == G6TS_RECOVERY_HARDWARE")
        power_off = recovery.index("g6ts_power_off", hardware)
        descriptor = recovery.index("g6ts_device_descriptor_cmd")
        verify = recovery.index("ts->awaiting_ready_heat = true")
        enable = recovery.index("ts->mode_enabled = true")
        self.assertLess(hardware, power_off)
        self.assertLess(power_off, descriptor)
        self.assertLess(descriptor, verify)
        self.assertLess(verify, enable)

        worker = function_body(self.source, "g6ts_recovery_work")
        self.assertIn("software_recovery_fallbacks", worker)
        self.assertIn("G6TS_RECOVERY_HARDWARE", worker)

    def test_phase77_deployment_is_isolated_from_saved_baseline(self):
        for token in (
            "sp11-phase77-recovery",
            "sp11_entry=7.1.3-phase77-recovery",
            "mshw0485_touch.behavior_v2=1",
            "mshw0485_touch.reset_recovery_v2=1",
        ):
            self.assertIn(token, self.phase77_boot)
        self.assertIn("phase75_assets", self.phase77_deploy)
        self.assertIn("grub-reboot sp11-phase77-recovery", self.phase77_deploy)
        self.assertIn("saved GRUB default remains unchanged", self.phase77_deploy)
        self.assertNotIn("grub-set-default", self.phase77_deploy)

    def test_phase78_reset_storm_breaker_is_bounded_and_opt_in(self):
        self.assertIn("static bool g6ts_reset_storm_breaker;", self.source)
        self.assertIn(
            "module_param_named(reset_storm_breaker, "
            "g6ts_reset_storm_breaker, bool, 0444)",
            self.source,
        )
        self.assertIn("#define G6TS_RESET_STORM_WINDOW_MS\t5000U", self.source)
        self.assertIn("#define G6TS_RESET_STORM_LIMIT\t\t3U", self.source)

        reset = function_body(self.source, "g6ts_note_panel_reset_locked")
        self.assertIn("interval_ms <= G6TS_RESET_STORM_WINDOW_MS", reset)
        self.assertIn("ts->rapid_reset_streak >= G6TS_RESET_STORM_LIMIT", reset)
        self.assertIn("ts->recovery_path = G6TS_RECOVERY_HARDWARE", reset)
        self.assertIn("ts->reset_storm_escalations++", reset)

        worker = function_body(self.source, "g6ts_recovery_work")
        self.assertIn("path == G6TS_RECOVERY_HARDWARE", worker)
        self.assertIn("ts->rapid_reset_streak = 0", worker)

        for token in (
            "sp11-phase78-storm-breaker",
            "sp11_entry=7.1.3-phase78-storm-breaker",
            "mshw0485_touch.behavior_v2=1",
            "mshw0485_touch.reset_recovery_v2=1",
            "mshw0485_touch.reset_storm_breaker=1",
        ):
            self.assertIn(token, self.phase78_boot)
        self.assertIn("phase75_assets", self.phase78_deploy)
        self.assertIn(
            "grub-reboot sp11-phase78-storm-breaker", self.phase78_deploy
        )
        self.assertIn("saved GRUB default remains unchanged", self.phase78_deploy)
        self.assertNotIn("grub-set-default", self.phase78_deploy)

    def test_phase79_changes_only_the_logical_set70_content_length(self):
        self.assertIn("static bool g6ts_feature70_one_byte;", self.source)
        self.assertIn(
            "module_param_named(feature70_one_byte, "
            "g6ts_feature70_one_byte, bool, 0444)",
            self.source,
        )
        recovery = function_body(self.source, "g6ts_full_reinitialize_locked")
        phase79 = recovery.index("if (g6ts_feature70_one_byte)")
        phase72 = recovery.index("else if (g6ts_mode_config_fix", phase79)
        isolated = recovery[phase79:phase72]
        self.assertIn("g6ts_mode_enable", isolated)
        self.assertIn("sizeof(g6ts_mode_enable)", isolated)
        self.assertNotIn("mode_config", isolated)

    def test_phase80_recovers_irq_faults_without_miscounting_panel_resets(self):
        self.assertIn("static bool g6ts_host_fault_recovery;", self.source)
        self.assertIn(
            "module_param_named(host_fault_recovery, "
            "g6ts_host_fault_recovery, bool, 0444)",
            self.source,
        )
        host_fault = function_body(self.source, "g6ts_note_host_fault_locked")
        for token in (
            "irq_protocol_errors++",
            "irq_transport_errors++",
            "host_fault_recoveries++",
            "G6TS_RECOVERY_HARDWARE",
            "g6ts_release_contacts",
            "schedule_delayed_work",
        ):
            self.assertIn(token, host_fault)
        self.assertNotIn("reset_notifications++", host_fault)

        irq = function_body(self.source, "g6ts_interrupt_thread")
        self.assertIn("g6ts_note_host_fault_locked(ts, ret)", irq)
        self.assertIn("ret != -EAGAIN", irq)
        self.assertIn("G6TS_IRQ_DRAIN_LIMIT", irq)
        self.assertIn("irq_drain_overflows++", irq)
        self.assertIn("g6ts_note_host_fault_locked(ts, -EOVERFLOW)", irq)

        for token in (
            "sp11-phase80-host-recovery",
            "sp11_entry=7.1.3-phase80-host-recovery",
            "mshw0485_touch.behavior_v2=1",
            "mshw0485_touch.reset_recovery_v2=1",
            "mshw0485_touch.host_fault_recovery=1",
        ):
            self.assertIn(token, self.phase80_boot)
        self.assertNotIn("feature70_one_byte=1", self.phase80_boot)
        self.assertIn("phase75_assets", self.phase80_deploy)
        self.assertIn(
            "grub-reboot sp11-phase80-host-recovery", self.phase80_deploy
        )
        self.assertIn("saved GRUB default remains unchanged", self.phase80_deploy)
        self.assertNotIn("grub-set-default", self.phase80_deploy)

    def test_phase81_only_suppresses_invalid_header_after_ready_deasserts(self):
        self.assertIn("static bool g6ts_ready_quiesce;", self.source)
        self.assertIn(
            "module_param_named(ready_quiesce, "
            "g6ts_ready_quiesce, bool, 0444)",
            self.source,
        )
        reader = function_body(self.source, "g6ts_dma_read_response")
        invalid = reader.index("invalid HID-SPI header")
        quiesce = reader.index("if (g6ts_ready_quiesce)")
        deasserted = reader.index("if (!pending)", quiesce)
        empty = reader.index("return -EAGAIN", deasserted)
        protocol = reader.index("return -EPROTO", invalid)
        self.assertLess(quiesce, deasserted)
        self.assertLess(deasserted, empty)
        self.assertLess(empty, protocol)
        self.assertIn("quiesced_empty_reads++", reader)
        self.assertIn("if (pending < 0)", reader)

        probe = function_body(self.source, "g6ts_probe")
        self.assertIn(
            "g6ts_ready_quiesce && !g6ts_host_fault_recovery", probe
        )

        for token in (
            "sp11-phase81-ready-quiesce",
            "sp11_entry=7.1.3-phase81-ready-quiesce",
            "mshw0485_touch.behavior_v2=1",
            "mshw0485_touch.reset_recovery_v2=1",
            "mshw0485_touch.host_fault_recovery=1",
            "mshw0485_touch.ready_quiesce=1",
        ):
            self.assertIn(token, self.phase81_boot)
        self.assertIn("phase75_assets", self.phase81_deploy)
        self.assertIn(
            "grub-reboot sp11-phase81-ready-quiesce", self.phase81_deploy
        )
        self.assertIn("saved GRUB default remains unchanged", self.phase81_deploy)
        self.assertNotIn("grub-set-default", self.phase81_deploy)

    def test_phase82_combines_phase81_with_only_the_set70_length_axis(self):
        profile = function_body(self.source, "g6ts_profile_name")
        phase82 = profile.index(
            "g6ts_ready_quiesce && g6ts_feature70_one_byte"
        )
        phase81 = profile.index("if (g6ts_ready_quiesce)", phase82 + 1)
        self.assertLess(phase82, phase81)

        for token in (
            "sp11-phase82-set70",
            "sp11_entry=7.1.3-phase82-set70",
            "mshw0485_touch.behavior_v2=1",
            "mshw0485_touch.reset_recovery_v2=1",
            "mshw0485_touch.host_fault_recovery=1",
            "mshw0485_touch.ready_quiesce=1",
            "mshw0485_touch.feature70_one_byte=1",
        ):
            self.assertIn(token, self.phase82_boot)
        self.assertNotIn("reset_storm_breaker=1", self.phase82_boot)
        self.assertIn("phase75_assets", self.phase82_deploy)
        self.assertIn("feature70_one_byte", self.phase82_deploy)
        self.assertIn("grub-reboot sp11-phase82-set70", self.phase82_deploy)
        self.assertIn("saved GRUB default remains unchanged", self.phase82_deploy)
        self.assertNotIn("grub-set-default", self.phase82_deploy)

    def test_frame_orchestrator_has_one_ordered_collection_boundary(self):
        body = function_body(self.source, "g6ts_report_heat_contacts")
        ordered = (
            "g6ts_assign_tracks",
            "g6ts_update_track",
            "g6ts_advance_unmatched_tracks",
            "g6ts_create_unmatched_tracks",
            "g6ts_collect_linux_contacts",
        )
        positions = [body.index(token) for token in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("input_sync", body)

    def test_generated_profile_contains_all_twenty_transitions(self):
        self.assertEqual(self.lifecycle_profile.count(" -> "), 20)
        for old_class in range(5):
            for new_class in range(4):
                self.assertIn(
                    f"/* {old_class} -> {new_class} */", self.lifecycle_profile
                )
        self.assertIn("G6TS_WINDOWS_HISTORY_CAPACITY 10U", self.lifecycle_profile)
        self.assertIn("G6TS_WINDOWS_ASSIGN_RADIUS 5U", self.lifecycle_profile)
        self.assertIn(
            "G6TS_WINDOWS_SCORE3_PRIMARY_Q24 838860800LL",
            self.lifecycle_profile,
        )

    def test_windows_score_three_postprocessor_uses_recovered_peak_counts(self):
        peak_body = function_body(self.source, "g6ts_local_peak_counts")
        scorer_body = function_body(self.source, "g6ts_classify_contact")
        for token in (
            "local_peak_count",
            "strong_local_peak_count",
            "G6TS_LOCAL_PEAK_CAPACITY",
            "G6TS_LOCAL_PEAK_FLOOR_Q12",
        ):
            self.assertIn(token, peak_body)
        self.assertIn("G6TS_WINDOWS_SCORE3_PRIMARY_Q24", scorer_body)
        self.assertIn("G6TS_WINDOWS_SCORE3_SINGLE_Q24", scorer_body)


if __name__ == "__main__":
    unittest.main()
