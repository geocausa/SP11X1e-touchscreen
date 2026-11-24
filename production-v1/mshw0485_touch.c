// SPDX-License-Identifier: GPL-2.0
/*
 * Microsoft Surface G6 Touch (MSHW0485) touchscreen driver.
 */

#include <linux/acpi.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/hid-over-spi.h>
#include <linux/input.h>
#include <linux/input/mt.h>
#include <linux/input/touchscreen.h>
#include <linux/interrupt.h>
#include <linux/jiffies.h>
#include <linux/kernel.h>
#include <linux/ktime.h>
#include <linux/math.h>
#include <linux/math64.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/pm.h>
#include <linux/slab.h>
#include <linux/spi/spi.h>
#include <linux/unaligned.h>
#include <linux/workqueue.h>

#include "g6ts_classifier_profile.h"

#define G6TS_NAME			"mshw0485-touch"
#define G6TS_SPI_HZ			40000000U
#define G6TS_MAX_BODY			8192U
#define G6TS_HEADER_SYNC		0x5a
#define G6TS_HEADER_VERSION		0x03
#define G6TS_FEATURE_RESPONSE_LIMIT	64U
#define G6TS_RECOVERY_DELAY_MS		100U
#define G6TS_RECOVERY_RETRY_MS		500U
#define G6TS_RECOVERY_LIMIT		3U
#define G6TS_HEAT_ROWS			46U
#define G6TS_HEAT_COLS			68U
#define G6TS_HEAT_SAMPLES		(G6TS_HEAT_ROWS * G6TS_HEAT_COLS)
#define G6TS_CAPIMG_CONTAINER_SECTION	0x0000
#define G6TS_HEAT_SECTION		0x0100
#define G6TS_CAPIMG_PROPS_SECTION	0x0200
#define G6TS_METADATA_SECTION		0xff00
#define G6TS_CAPIMG_PROPS_V0_MIN_SIZE	0x17U
#define G6TS_CAPIMG_PROPS_V1_MIN_SIZE	0x70U
#define G6TS_FEATURE06_LEN		119U
#define G6TS_DEFAULT_HIMETRIC_WIDTH	27389U
#define G6TS_DEFAULT_HIMETRIC_HEIGHT	18259U
#define G6TS_NSR_BINS			16U
#define G6TS_NSR_CUTOFF			655U
/*
 * TouchPenProcessor0C83.dll converts a calibrated byte through a linear
 * lookup whose zero crossing is approximately 180.  The SP11 configuration
 * starts a candidate at raw <= 171.  Its scan-line union joins only
 * edge-adjacent cells.  One- and two-cell candidates survive only when
 * their peak is stronger than the secondary detector threshold (raw <= 162);
 * all candidates of three or more cells continue downstream.
 */
#define G6TS_HEAT_SIGNAL_ZERO		180U
#define G6TS_HEAT_THRESHOLD		9U
#define G6TS_HEAT_ACTIVE_MAX		(G6TS_HEAT_SIGNAL_ZERO - G6TS_HEAT_THRESHOLD)
#define G6TS_HEAT_STRONG_MAX		162U
#define G6TS_HEAT_MIN_PIXELS		3U
#define G6TS_HEAT_PALM_PIXELS		48U
#define G6TS_HEAT_MERGED_MAX_PIXELS	64U
#define G6TS_HEAT_PALM_SPAN		12U
#define G6TS_EDGE_PALM_SPAN		7U
#define G6TS_EDGE_PALM_PIXELS		28U
#define G6TS_EDGE_CONFIRM_PIXELS	16U
#define G6TS_SPLIT_MIN_DIST_SQ		4U
#define G6TS_SPLIT_VALLEY_PCT		85U
#define G6TS_SPLIT_MAX_PEAKS		4U
#define G6TS_MAX_CONTACTS		10U
#define G6TS_LOGICAL_MAX		32767U
#define G6TS_MT_AXIS_MAX_TENTH_MM	1000U
#define G6TS_MT_AXIS_RES		10U
#define G6TS_MT_PRESSURE_MAX		255U
#define G6TS_DUPLICATE_MERGE_DIST_SQ	36U
#define G6TS_CONTACT_HOLD_FRAMES	6U
#define G6TS_TRACK_CONFIRM_EDGE		3U
#define G6TS_TRACK_CONFIRM_WEAK		5U
#define G6TS_TRACK_CONFIRM_SPLIT	8U
#define G6TS_TRACK_SPLIT_RADIUS		2048U
#define G6TS_TRACK_CONFIRM_STRONG	2U
#define G6TS_CENTROID_BASELINE		171U
#define G6TS_SCORE_SHIFT		24U
#define G6TS_RUNTIME_OFFSET_Q24		(-177430463LL)
#define G6TS_ASSIGN_X_SCALE_Q24		68082944U
#define G6TS_ASSIGN_Y_SCALE_Q24		67306464U
#define G6TS_ASSIGN_RADIUS		5U
#define G6TS_SIGNAL_INTERCEPT_Q24	6710886
#define G6TS_SIGNAL_STEP_Q24		37251
#define G6TS_SECONDARY_A_Q12		645663
#define G6TS_SECONDARY_NOISE_Q12	36895
#define G6TS_SECONDARY_SEED_Q12		225
#define G6TS_LOCAL_PEAK_FLOOR_Q12	164
#define G6TS_LOCAL_PEAK_CAPACITY	10U
#define G6TS_AXIS_SCALE_Q12		18919
#define G6TS_SPREAD_SCALE_Q12		25736
#define G6TS_HALO_RATIO_Q12		614
#define G6TS_HALO_UNAVAILABLE_Q12	(100U << G6TS_CLASSIFIER_SHIFT)
#define G6TS_ASSIGN_MAX			(G6TS_MAX_CONTACTS * 2U)
#define G6TS_ASSIGN_UNMATCHED_COST	1000000
#define G6TS_ASSIGN_INVALID_COST	3000000

/* Exact SP11 HID-over-SPI descriptor constants. */
#define G6TS_SP11_REPORT_DESCRIPTOR_LEN	1484U
#define G6TS_SP11_MAX_INPUT_LEN		8192U
#define G6TS_SP11_MAX_OUTPUT_LEN		512U
#define G6TS_SP11_MAX_FRAGMENT_LEN	8192U
#define G6TS_SP11_VENDOR_ID		0x045eU
#define G6TS_SP11_PRODUCT_ID		0x0c83U
#define G6TS_SP11_VERSION_ID		0x0004U
#define G6TS_SP11_DESCRIPTOR_FLAGS	0x0001U
#define G6TS_FEEDBACK_LEN		63U
#define G6TS_CLEAN_DISPLAY_ON		1U
#define G6TS_CLEAN_HINGE_SLATE		400U
#define G6TS_CLEAN_FAST_HOST_ID		1U
#define G6TS_HEADER_BODY_MIN_US		490U
#define G6TS_HEADER_BODY_MAX_US		550U
#define G6TS_HIDSPI_CMD_TIMEOUT_MS	2000U
#define G6TS_HIDSPI_CMD_STATUS_OK	0x01U

enum g6ts_pm_mode {
	G6TS_PM_SLEEP,
	G6TS_PM_OFF,
	G6TS_PM_LEGACY,
};

enum g6ts_initialization_stage {
	G6TS_INIT_IDLE,
	G6TS_INIT_RESET_RESPONSE,
	G6TS_INIT_DEVICE_DESCRIPTOR,
	G6TS_INIT_REPORT_DESCRIPTOR,
	G6TS_INIT_HEAT_CAPS06,
	G6TS_INIT_FEEDBACK_A1,
	G6TS_INIT_FEEDBACK_A5,
	G6TS_INIT_SET_FEATURE05,
	G6TS_INIT_GET_FEATURE70,
	G6TS_INIT_SET_FEATURE70,
	G6TS_INIT_WAIT_HEAT,
};

/*
 * HidSpiCx-conformant suspend/resume policy:
 *  - "off":    send write-only SET_POWER(OFF) and cut rails (matching Windows
 *              SP11 D3Cold Modern Standby), then recover asynchronously on wake
 *              with zero synchronous PM stall and zero standby rail draw.
 *  - "sleep":  send write-only SET_POWER(SLEEP), retain rails, and warm-wake
 *              with SET_POWER(ON) (async cold fallback on timeout/D3Cold).
 *  - "legacy": skip SET_POWER and synchronously power-cycle GPIOs on wake.
 */
static char *g6ts_pm_sleep_mode = "off";
module_param_named(pm_sleep_mode, g6ts_pm_sleep_mode, charp, 0444);
MODULE_PARM_DESC(pm_sleep_mode,
		 "HID-SPI suspend/resume mode: off (default), sleep, or legacy");

static const u8 g6ts_header_cmd[8] = {
	0xeb, 0x00, 0x10, 0x00, 0xff, 0xff, 0xff, 0xff,
};

static const u8 g6ts_body_cmd[8] = {
	0xeb, 0x00, 0x10, 0x04, 0xff, 0xff, 0xff, 0xff,
};

/* HID-over-SPI DEVICE_DESCRIPTOR and REPORT_DESCRIPTOR requests. */
static const u8 g6ts_device_descriptor_cmd[8] = {
	0xe2, 0x00, 0x20, 0x00, DEVICE_DESCRIPTOR, 0x00, 0x00, 0x00,
};

static const u8 g6ts_report_descriptor_cmd[8] = {
	0xe2, 0x00, 0x20, 0x00, REPORT_DESCRIPTOR, 0x00, 0x00, 0x00,
};

static const u8 g6ts_mode_enable[] = { 0x01 };

/* TouchPenProcessor project-0x0c83 sensor-row to NSR-bin mapping. */
static const u8 g6ts_nsr_row_to_bin[G6TS_HEAT_ROWS] = {
	0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
	0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
	2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
};

struct g6ts_contact {
	u64 weighted_x;
	u64 weighted_y;
	u32 strength;
	u32 sensor_x_q24;
	u32 sensor_y_q24;
	u16 pixels;
	u16 x;
	u16 y;
	u16 output_x;
	u16 output_y;
	u16 touch_major;
	u16 touch_minor;
	u8 pressure;
	u8 peak_value;
	u8 min_col;
	u8 max_col;
	u8 min_row;
	u8 max_row;
	s32 features_q12[G6TS_FEATURE_COUNT];
	s64 scores_q24[G6TS_CLASS_COUNT];
	u8 local_peak_count;
	u8 strong_local_peak_count;
	u8 shape_class;
	bool shape_allowed;
	bool touches_edge;
};

struct g6ts_track {
	u32 strength;
	u16 raw_x;
	u16 raw_y;
	u16 output_x;
	u16 output_y;
	u16 touch_major;
	u16 touch_minor;
	u8 pressure;
	u16 pixels;
	u32 sensor_x_q24;
	u32 sensor_y_q24;
	s32 sensor_velocity_x_q24;
	s32 sensor_velocity_y_q24;
	s16 velocity_x;
	s16 velocity_y;
	u16 age;
	u8 missed;
	u8 evidence;
	u8 required_evidence;
	u8 shape_class;
	bool active;
	bool confirmed;
};

struct g6ts_assignment_workspace {
	int cost[G6TS_ASSIGN_MAX][G6TS_ASSIGN_MAX];
	int u[G6TS_ASSIGN_MAX + 1];
	int v[G6TS_ASSIGN_MAX + 1];
	int p[G6TS_ASSIGN_MAX + 1];
	int way[G6TS_ASSIGN_MAX + 1];
	int minv[G6TS_ASSIGN_MAX + 1];
	bool used[G6TS_ASSIGN_MAX + 1];
	int active_slots[G6TS_MAX_CONTACTS];
};

struct g6ts {
	struct spi_device *spi;
	struct input_dev *input;
	struct touchscreen_properties prop;
	/* Serializes transport, initialization, recovery, and power changes. */
	struct mutex io_lock;
	struct gpio_desc *interrupt_gpio;
	struct gpio_desc *power_gpio;
	struct gpio_desc *reset_gpio;
	u8 *body;
	u8 heatmap[G6TS_HEAT_SAMPLES];
	u8 heat_seen[G6TS_HEAT_SAMPLES];
	u8 heat_component[G6TS_HEAT_SAMPLES];
	u8 heat_work[G6TS_HEAT_SAMPLES];
	u16 heat_queue[G6TS_HEAT_SAMPLES];
	u16 nsr_bins[G6TS_NSR_BINS];
	struct g6ts_contact contacts[G6TS_MAX_CONTACTS];
	struct g6ts_track tracks[G6TS_MAX_CONTACTS];
	struct g6ts_assignment_workspace assignment;
	struct delayed_work recovery_work;
	u8 last_header[HIDSPI_INPUT_HEADER_SIZE];
	u8 last_class;
	u16 last_content_len;
	u16 expected_report_descriptor_len;
	u8 last_content_id;
	int interrupt_irq;
	atomic64_t interrupt_edges;
	s64 handled_interrupt_edges;
	u64 reset_notifications;
	u64 recovery_successes;
	u64 recovery_failures;
	u64 hardware_recovery_attempts;
	u64 host_fault_recoveries;
	u64 irq_transport_errors;
	u64 irq_protocol_errors;
	u64 quiesced_empty_reads;
	u64 cadence_single_response_irqs;
	u64 ready_heat_frames;
	u64 ready_verification_failures;
	u64 pm_sleep_acks;
	u64 pm_off_acks;
	u64 pm_sleep_fallbacks;
	u64 pm_warm_wakes;
	u64 pm_cold_fallbacks;
	u64 pm_last_wake_us;
	u64 heat_frames;
	u64 non_touch_heat_frames;
	u64 heat_errors;
	u32 sensor_rows;
	u32 sensor_cols;
	u32 himetric_width;
	u32 himetric_height;
	u8 sensor_orientation;
	u8 feedback_v06_seq;
	bool feature06_valid;
	u64 component_total;
	u64 contact_total;
	u64 weak_rejections;
	u64 nsr_rejections;
	u64 palm_rejections;
	u64 edge_palm_rejections;
	u64 merged_splits;
	u64 duplicate_merges;
	u64 assignment_matches;
	u64 new_tracks;
	u64 output_frames;
	u64 output_contacts;
	u64 processing_ns_total;
	u64 processing_ns_max;
	u8 nsr_bin_count;
	enum g6ts_initialization_stage initialization_stage;
	u8 recovery_fail_streak;
	int last_host_fault;
	bool nsr_valid;
	bool awaiting_ready_heat;
	bool mode_enabled;
	bool suspended_in_sleep;
	bool fatal_transport_error;
	bool stopping;
};

static const char *
g6ts_initialization_stage_name(enum g6ts_initialization_stage stage)
{
	switch (stage) {
	case G6TS_INIT_IDLE:
		return "idle";
	case G6TS_INIT_RESET_RESPONSE:
		return "reset-response";
	case G6TS_INIT_DEVICE_DESCRIPTOR:
		return "device-descriptor";
	case G6TS_INIT_REPORT_DESCRIPTOR:
		return "report-descriptor";
	case G6TS_INIT_HEAT_CAPS06:
		return "heat-caps06";
	case G6TS_INIT_FEEDBACK_A1:
		return "feedback-a1";
	case G6TS_INIT_FEEDBACK_A5:
		return "feedback-a5";
	case G6TS_INIT_SET_FEATURE05:
		return "set-feature05";
	case G6TS_INIT_GET_FEATURE70:
		return "get-feature70";
	case G6TS_INIT_SET_FEATURE70:
		return "set-feature70";
	case G6TS_INIT_WAIT_HEAT:
		return "wait-heat";
	}

	return "invalid";
}

static ssize_t behavior_stats_show(struct device *dev,
				   struct device_attribute *attr, char *buf)
{
	struct g6ts *ts = dev_get_drvdata(dev);
	u64 average_ns;
	ssize_t length;

	mutex_lock(&ts->io_lock);
	average_ns = ts->heat_frames ?
		div64_u64(ts->processing_ns_total, ts->heat_frames) : 0;
	length = sysfs_emit(buf,
			    "profile=production-v1\n"
			    "initialization_stage=%s\n"
			    "last_header=%4ph\n"
			    "last_class=%u\n"
			    "last_content_id=%u\n"
			    "last_content_len=%u\n"
			    "mode_enabled=%u\n"
			    "awaiting_ready_heat=%u\n"
			    "feature06_valid=%u\n"
			    "sensor_geometry=%ux%u\n"
			    "himetric_size=%ux%u\n"
			    "heat_frames=%llu\n"
			    "non_touch_heat_frames=%llu\n"
			    "heat_errors=%llu\n"
			    "components=%llu\n"
			    "accepted_contacts=%llu\n"
			    "weak_rejections=%llu\n"
			    "nsr_rejections=%llu\n"
			    "palm_rejections=%llu\n"
			    "edge_palm_rejections=%llu\n"
			    "merged_splits=%llu\n"
			    "duplicate_merges=%llu\n"
			    "assignment_matches=%llu\n"
			    "new_tracks=%llu\n"
			    "output_frames=%llu\n"
			    "output_contacts=%llu\n"
			    "processing_average_ns=%llu\n"
			    "processing_max_ns=%llu\n"
			    "panel_resets=%llu\n"
			    "recovery_successes=%llu\n"
			    "recovery_failures=%llu\n"
			    "hardware_recovery_attempts=%llu\n"
			    "host_fault_recoveries=%llu\n"
			    "irq_transport_errors=%llu\n"
			    "irq_protocol_errors=%llu\n"
			    "quiesced_empty_reads=%llu\n"
			    "cadence_single_response_irqs=%llu\n"
			    "last_host_fault=%d\n"
			    "ready_heat_frames=%llu\n"
			    "ready_verification_failures=%llu\n"
			    "pm_sleep_mode=%s\n"
			    "pm_sleep_acks=%llu\n"
			    "pm_off_acks=%llu\n"
			    "pm_sleep_fallbacks=%llu\n"
			    "pm_warm_wakes=%llu\n"
			    "pm_cold_fallbacks=%llu\n"
			    "pm_last_wake_us=%llu\n",
			    g6ts_initialization_stage_name(ts->initialization_stage),
			    ts->last_header, ts->last_class,
			    ts->last_content_id, ts->last_content_len,
			    ts->mode_enabled, ts->awaiting_ready_heat,
			    ts->feature06_valid,
			    ts->sensor_rows, ts->sensor_cols,
			    ts->himetric_width, ts->himetric_height,
			    ts->heat_frames, ts->non_touch_heat_frames,
			    ts->heat_errors,
			    ts->component_total, ts->contact_total,
			    ts->weak_rejections, ts->nsr_rejections,
			    ts->palm_rejections, ts->edge_palm_rejections,
			    ts->merged_splits, ts->duplicate_merges,
			    ts->assignment_matches,
			    ts->new_tracks, ts->output_frames,
			    ts->output_contacts, average_ns,
			    ts->processing_ns_max, ts->reset_notifications,
			    ts->recovery_successes, ts->recovery_failures,
			    ts->hardware_recovery_attempts,
			    ts->host_fault_recoveries,
			    ts->irq_transport_errors,
			    ts->irq_protocol_errors,
			    ts->quiesced_empty_reads,
			    ts->cadence_single_response_irqs,
			    ts->last_host_fault,
			    ts->ready_heat_frames,
			    ts->ready_verification_failures,
			    g6ts_pm_sleep_mode,
			    ts->pm_sleep_acks,
			    ts->pm_off_acks,
			    ts->pm_sleep_fallbacks,
			    ts->pm_warm_wakes,
			    ts->pm_cold_fallbacks,
			    ts->pm_last_wake_us);
	mutex_unlock(&ts->io_lock);

	return length;
}
static DEVICE_ATTR_RO(behavior_stats);

static struct attribute *g6ts_attributes[] = {
	&dev_attr_behavior_stats.attr,
	NULL,
};

static const struct attribute_group g6ts_attribute_group = {
	.attrs = g6ts_attributes,
};

static int g6ts_acpi_method(struct device *dev, const char *method)
{
	acpi_handle handle = ACPI_HANDLE(dev);
	acpi_status status;

	if (!handle)
		return -ENODEV;
	status = acpi_evaluate_object(handle, (char *)method, NULL, NULL);
	return ACPI_FAILURE(status) ? -EIO : 0;
}

static int g6ts_power_on(struct g6ts *ts)
{
	int ret;

	if (ts->power_gpio && ts->reset_gpio) {
		gpiod_set_value_cansleep(ts->reset_gpio, 0);
		gpiod_set_value_cansleep(ts->power_gpio, 1);
		msleep(500);
		gpiod_set_value_cansleep(ts->reset_gpio, 1);
		msleep(300);
		return 0;
	}

	ret = g6ts_acpi_method(&ts->spi->dev, "_PS0");
	if (ret)
		return dev_err_probe(&ts->spi->dev, ret,
				     "ACPI _PS0 failed\n");

	ret = g6ts_acpi_method(&ts->spi->dev, "_RST");
	if (ret) {
		g6ts_acpi_method(&ts->spi->dev, "_PS3");
		return dev_err_probe(&ts->spi->dev, ret,
				     "ACPI _RST failed\n");
	}

	return 0;
}

static int g6ts_power_off(struct g6ts *ts)
{
	if (ts->power_gpio && ts->reset_gpio) {
		gpiod_set_value_cansleep(ts->reset_gpio, 0);
		usleep_range(10000, 12000);
		gpiod_set_value_cansleep(ts->power_gpio, 0);
		return 0;
	}

	return g6ts_acpi_method(&ts->spi->dev, "_PS3");
}

/*
 * Submit RX first and TX second through the controller's SP11 QSPI pairing
 * path. The ordering and 1-4-4 lane selection match the Windows GPI capture.
 */
static int g6ts_dma_read_pair(struct g6ts *ts, const u8 cmd[8],
			      void *rx, size_t rx_len)
{
	struct spi_transfer xfers[2] = {
		{
			.tx_buf = cmd,
			.len = 8,
			.speed_hz = G6TS_SPI_HZ,
			.bits_per_word = 8,
			.tx_nbits = SPI_NBITS_QUAD,
		}, {
			.rx_buf = rx,
			.len = rx_len,
			.speed_hz = G6TS_SPI_HZ,
			.bits_per_word = 8,
			.rx_nbits = SPI_NBITS_QUAD,
		},
	};
	struct spi_message msg;

	spi_message_init_with_transfers(&msg, xfers, ARRAY_SIZE(xfers));
	return spi_sync(ts->spi, &msg);
}

static int g6ts_dma_output(struct g6ts *ts, const void *buf, size_t len)
{
	struct spi_transfer xfer = {
		.tx_buf = buf,
		.len = len,
		.speed_hz = G6TS_SPI_HZ,
		.bits_per_word = 8,
		.tx_nbits = SPI_NBITS_QUAD,
	};
	struct spi_message msg;

	spi_message_init_with_transfers(&msg, &xfer, 1);
	return spi_sync(ts->spi, &msg);
}

static int g6ts_dma_hidspi_output(struct g6ts *ts, u8 report_type,
				  u8 content_id, const u8 *content,
				  size_t content_len)
{
	u8 packet[72] = { 0xe2, 0x00, 0x20, 0x00 };
	size_t packet_len;

	if (content_len > sizeof(packet) - 8)
		return -E2BIG;

	packet[4] = report_type;
	put_unaligned_le16(content_len, &packet[5]);
	packet[7] = content_id;
	if (content_len)
		memcpy(&packet[8], content, content_len);
	packet_len = round_up(8 + content_len, 4);

	dev_dbg(&ts->spi->dev,
		"G6TS DMA output type=%u id=%#02x content_len=%zu wire=%*ph\n",
		report_type, content_id, content_len, (int)packet_len, packet);
	return g6ts_dma_output(ts, packet, packet_len);
}

static int g6ts_pending(struct g6ts *ts)
{
	return gpiod_get_value_cansleep(ts->interrupt_gpio);
}

static bool g6ts_has_unread_response(struct g6ts *ts)
{
	int pending = g6ts_pending(ts);

	return pending > 0 ||
	       atomic64_read(&ts->interrupt_edges) > ts->handled_interrupt_edges;
}

static irqreturn_t g6ts_interrupt_edge(int irq, void *data)
{
	struct g6ts *ts = data;

	atomic64_inc(&ts->interrupt_edges);
	return IRQ_WAKE_THREAD;
}

static int g6ts_wait_pending(struct g6ts *ts, unsigned int timeout_ms)
{
	unsigned long deadline = jiffies + msecs_to_jiffies(timeout_ms);
	int value;

	do {
		value = g6ts_pending(ts);
		if (value < 0 || value ||
		    atomic64_read(&ts->interrupt_edges) >
		    ts->handled_interrupt_edges)
			return value < 0 ? value : 0;
		usleep_range(1000, 2000);
	} while (time_before(jiffies, deadline));

	return -ETIMEDOUT;
}

static void g6ts_clear_last_response(struct g6ts *ts)
{
	ts->last_class = 0xff;
	ts->last_content_len = 0;
	ts->last_content_id = 0xff;
}

static bool g6ts_is_heat_report_id(u8 content_id)
{
	switch (content_id) {
	case 0x07:
	case 0x08:
	case 0x0a:
	case 0x0b:
	case 0x0c:
	case 0x0d:
	case 0x12:
	case 0x1a:
	case 0x1c:
		return true;
	default:
		return false;
	}
}

static void g6ts_apply_input_resolution(struct g6ts *ts)
{
	u32 width_hm = ts->himetric_width ? ts->himetric_width :
					    G6TS_DEFAULT_HIMETRIC_WIDTH;
	u32 height_hm = ts->himetric_height ? ts->himetric_height :
					      G6TS_DEFAULT_HIMETRIC_HEIGHT;
	u32 res_x = DIV_ROUND_CLOSEST_ULL((u64)G6TS_LOGICAL_MAX * 100U,
					  width_hm);
	u32 res_y = DIV_ROUND_CLOSEST_ULL((u64)G6TS_LOGICAL_MAX * 100U,
					  height_hm);

	if (!ts->input)
		return;
	input_abs_set_res(ts->input, ABS_MT_POSITION_X, res_x);
	input_abs_set_res(ts->input, ABS_MT_POSITION_Y, res_y);
}

static int g6ts_parse_feature06(struct g6ts *ts, const u8 *content,
				size_t content_len)
{
	const u8 *props = NULL;
	size_t props_len = 0;
	u32 outer_len, rows, cols, width_hm, height_hm;
	u16 outer_type;
	u8 version, orientation = 0;

	if (content_len < 7)
		return -EMSGSIZE;

	outer_len = get_unaligned_le32(content);
	outer_type = get_unaligned_le16(content + 4);
	if (outer_len < 7 || outer_len > content_len)
		return -EPROTO;

	if (outer_type == G6TS_CAPIMG_PROPS_SECTION) {
		props = content;
		props_len = outer_len;
	} else if (outer_type == G6TS_CAPIMG_CONTAINER_SECTION) {
		size_t offset = 7;

		while (offset < outer_len) {
			u32 sub_len;
			u16 sub_type;

			if (outer_len - offset < 7)
				return -EPROTO;
			sub_len = get_unaligned_le32(content + offset);
			sub_type = get_unaligned_le16(content + offset + 4);
			if (sub_len < 7 || sub_len > outer_len - offset)
				return -EPROTO;
			if (sub_type == G6TS_CAPIMG_PROPS_SECTION) {
				props = content + offset;
				props_len = sub_len;
				break;
			}
			offset += sub_len;
		}
	} else {
		return -EPROTO;
	}

	if (!props)
		return -ENOENT;

	version = props[6];
	if (version == 0) {
		if (props_len < G6TS_CAPIMG_PROPS_V0_MIN_SIZE)
			return -EPROTO;
		rows = get_unaligned_le16(props + 0x07);
		cols = get_unaligned_le16(props + 0x0b);
		width_hm = get_unaligned_le32(props + 0x0f);
		height_hm = get_unaligned_le32(props + 0x13);
	} else if (version == 1) {
		if (props_len < G6TS_CAPIMG_PROPS_V1_MIN_SIZE)
			return -EPROTO;
		rows = get_unaligned_le32(props + 0x07);
		cols = get_unaligned_le32(props + 0x0b);
		width_hm = get_unaligned_le32(props + 0x0f);
		height_hm = get_unaligned_le32(props + 0x13);
		orientation = props[0x17];
	} else {
		return -EPROTO;
	}

	if (rows != G6TS_HEAT_ROWS || cols != G6TS_HEAT_COLS ||
	    !width_hm || !height_hm)
		return -EPROTO;

	ts->sensor_rows = rows;
	ts->sensor_cols = cols;
	ts->himetric_width = width_hm;
	ts->himetric_height = height_hm;
	ts->sensor_orientation = orientation;
	ts->feature06_valid = true;
	g6ts_apply_input_resolution(ts);
	return 0;
}

static int g6ts_extract_nsr_metadata(struct g6ts *ts, const u8 *section,
				     size_t section_len)
{
	size_t position = 7;

	/* Windows starts its nested metadata dispatcher at section byte seven. */
	while (position < section_len) {
		size_t payload_len, record_end;
		const u8 *record;
		unsigned int count, i;

		if (section[position] == 0xff)
			break;
		if (section_len - position < 4)
			return -EPROTO;
		record = section + position;
		payload_len = get_unaligned_le16(record + 2);
		if (record[0] == 0x00 && payload_len == 0)
			break;
		if (payload_len > section_len - position - 4)
			return -EPROTO;
		record_end = position + 4 + payload_len;

		if (record[0] == 0x04) {
			if (ts->nsr_valid || payload_len < 4)
				return -EPROTO;
			count = record[4];
			if (count > G6TS_NSR_BINS ||
			    count > (payload_len - 4) / 4)
				return -EPROTO;
			memset(ts->nsr_bins, 0, sizeof(ts->nsr_bins));
			for (i = 0; i < count; i++) {
				u16 value = get_unaligned_le16(record + 8 + i * 4);

				ts->nsr_bins[i] = value;
			}
			ts->nsr_bin_count = count;
			ts->nsr_valid = true;
		}
		position = record_end;
	}

	return 0;
}

static int g6ts_extract_heatmap(struct g6ts *ts, const u8 *content,
				size_t content_len)
{
	size_t container_end, offset;
	u32 container_len;
	bool found = false;

	/*
	 * Report 0x12 begins with a two-byte scan time, followed by a Heat
	 * container.  Its seven-byte container header is followed by length-
	 * prefixed sections.  Windows asks IHeatFrameRawData for section 0x0100.
	 */
	if (content_len < 9)
		return -EMSGSIZE;
	container_len = get_unaligned_le32(content + 2);
	if (container_len < 7 || container_len > content_len - 2)
		return -EPROTO;
	container_end = 2 + container_len;
	offset = 9;
	ts->nsr_valid = false;
	ts->nsr_bin_count = 0;

	while (offset < container_end) {
		const u8 *section = content + offset;
		size_t section_end, position;
		u32 section_len;
		u16 section_type;
		u32 written = 0;

		if (container_end - offset < 8)
			return -EPROTO;
		section_len = get_unaligned_le32(section);
		if (section_len < 8 || section_len > container_end - offset)
			return -EPROTO;
		section_end = offset + section_len;
		section_type = get_unaligned_le16(section + 4);

		if (section_type == G6TS_METADATA_SECTION) {
			int ret = g6ts_extract_nsr_metadata(ts, section,
							    section_len);

			if (ret)
				return ret;
			offset = section_end;
			continue;
		}
		if (section_type != G6TS_HEAT_SECTION) {
			offset = section_end;
			continue;
		}
		if (found || section[6] != 1 || section[7] != 8)
			return -EPROTO;

		memset(ts->heatmap, G6TS_HEAT_SIGNAL_ZERO, sizeof(ts->heatmap));
		memset(ts->heat_seen, 0, sizeof(ts->heat_seen));
		position = offset + 8;
		while (position < section_end) {
			u32 destination, count;
			u32 i;

			if (section_end - position < 8)
				return -EPROTO;
			destination = get_unaligned_le32(content + position);
			count = get_unaligned_le32(content + position + 4);
			position += 8;
			if (count > section_end - position ||
			    count > G6TS_HEAT_SAMPLES ||
			    destination > G6TS_HEAT_SAMPLES - count)
				return -EPROTO;
			for (i = 0; i < count; i++) {
				if (ts->heat_seen[destination + i])
					return -EPROTO;
				ts->heat_seen[destination + i] = 1;
			}
			memcpy(ts->heatmap + destination, content + position, count);
			written += count;
			position += count;
		}
		if (!written || written > G6TS_HEAT_SAMPLES)
			return -EPROTO;
		found = true;
		offset = section_end;
	}

	return found ? 0 : -ENOENT;
}

static bool g6ts_heat_active(const struct g6ts *ts, unsigned int index)
{
	return ts->heatmap[index] <= G6TS_HEAT_ACTIVE_MAX;
}

static void g6ts_store_contact(struct g6ts *ts,
			       const struct g6ts_contact *contact,
			       unsigned int *contact_count)
{
	unsigned int weakest = 0;
	unsigned int i;

	if (*contact_count < G6TS_MAX_CONTACTS) {
		ts->contacts[(*contact_count)++] = *contact;
		return;
	}

	for (i = 1; i < G6TS_MAX_CONTACTS; i++)
		if (ts->contacts[i].strength < ts->contacts[weakest].strength)
			weakest = i;
	if (contact->strength > ts->contacts[weakest].strength)
		ts->contacts[weakest] = *contact;
}

static s32 g6ts_signal_q12(u8 value)
{
	s32 signal_q24 = G6TS_SIGNAL_INTERCEPT_Q24 -
			 value * G6TS_SIGNAL_STEP_Q24;

	return (signal_q24 + BIT(G6TS_CLASSIFIER_SHIFT - 1)) >>
		G6TS_CLASSIFIER_SHIFT;
}

/*
 * FUN_180047078 recomputes the normal output centroid relative to project
 * baseline index 171.  On the ordinary zero-context path captured for project
 * 0x0c83, empty cells outside the thresholded component cannot have positive
 * weight against that baseline.  The expanded-window traversal therefore
 * reduces exactly to this component-local weighted centroid.  Keep the
 * detector centroid in contact->x/y for assignment and place this later
 * output-stage position in contact->output_x/y.
 */
static void g6ts_phase76_output_centroid(struct g6ts *ts,
					 struct g6ts_contact *contact)
{
	u64 weighted_x = 0, weighted_y = 0;
	u64 weight_total = 0;
	unsigned int index;

	for (index = 0; index < G6TS_HEAT_SAMPLES; index++) {
		u8 value;
		u32 weight;

		if (!ts->heat_component[index])
			continue;
		value = ts->heatmap[index];
		if (value >= G6TS_CENTROID_BASELINE)
			continue;
		weight = G6TS_CENTROID_BASELINE - value;
		weight_total += weight;
		weighted_x += (u64)(index % G6TS_HEAT_COLS) * weight;
		weighted_y += (u64)(index / G6TS_HEAT_COLS) * weight;
	}
	if (!weight_total)
		return;

	contact->output_x = div_u64(weighted_x * G6TS_LOGICAL_MAX,
				    weight_total * (G6TS_HEAT_COLS - 1));
	contact->output_y = div_u64(weighted_y * G6TS_LOGICAL_MAX,
				    weight_total * (G6TS_HEAT_ROWS - 1));

	/*
	 * Mirror FUN_180054690: snap one-cell-wide boundary components cleanly
	 * to the physical display edges so bezel swipes reach 0..32767.
	 */
	if (contact->min_col == 0 && contact->max_col == 0)
		contact->output_x = 0;
	else if (contact->min_col == G6TS_HEAT_COLS - 1 &&
		 contact->max_col == G6TS_HEAT_COLS - 1)
		contact->output_x = G6TS_LOGICAL_MAX;

	if (contact->min_row == 0 && contact->max_row == 0)
		contact->output_y = 0;
	else if (contact->min_row == G6TS_HEAT_ROWS - 1 &&
		 contact->max_row == G6TS_HEAT_ROWS - 1)
		contact->output_y = G6TS_LOGICAL_MAX;
}

/*
 * Mirror FUN_180040438's candidate +0x4d local-maximum producer and
 * FUN_180041fd8's +0x4e strict 0.04 filter.  The DLL's equality epsilon is
 * 0.0001 while adjacent byte lookup values differ by about 0.00222, so Q12
 * ordering is identical for this byte-input path.
 */
static void g6ts_local_peak_counts(const struct g6ts *ts,
				   struct g6ts_contact *contact)
{
	static const s8 neighbours[][2] = {
		{ -1, 0 }, { 1, 0 }, { 0, -1 }, { 0, 1 },
	};
	unsigned int index;

	contact->local_peak_count = 0;
	contact->strong_local_peak_count = 0;
	for (index = 0; index < G6TS_HEAT_SAMPLES; index++) {
		unsigned int row, col, equal_index = UINT_MAX;
		s32 current_signal, equal_signal = 0;
		unsigned int lower = 0, near_equal = 0, n;
		bool selected;

		if (!ts->heat_component[index])
			continue;
		row = index / G6TS_HEAT_COLS;
		col = index % G6TS_HEAT_COLS;
		current_signal = g6ts_signal_q12(ts->heatmap[index]);
		for (n = 0; n < ARRAY_SIZE(neighbours); n++) {
			int neighbour_col = col + neighbours[n][0];
			int neighbour_row = row + neighbours[n][1];
			unsigned int neighbour_index;
			s32 neighbour_signal;

			if (neighbour_row < 0 || neighbour_row >= G6TS_HEAT_ROWS ||
			    neighbour_col < 0 || neighbour_col >= G6TS_HEAT_COLS) {
				neighbour_index = UINT_MAX;
				neighbour_signal = 0;
			} else {
				neighbour_index = neighbour_row * G6TS_HEAT_COLS +
						  neighbour_col;
				neighbour_signal =
					g6ts_signal_q12(ts->heatmap[neighbour_index]);
			}
			if (current_signal > neighbour_signal) {
				lower++;
			} else if (current_signal == neighbour_signal) {
				near_equal++;
				equal_index = neighbour_index;
				equal_signal = neighbour_signal;
			}
		}

		selected = lower == 4;
		if (lower == 3 && near_equal == 1)
			selected = equal_signal < current_signal ||
				   (equal_signal == current_signal &&
				    index < equal_index);
		if (!selected ||
		    contact->local_peak_count >= G6TS_LOCAL_PEAK_CAPACITY)
			continue;
		contact->local_peak_count++;
		if (current_signal > G6TS_LOCAL_PEAK_FLOOR_Q12)
			contact->strong_local_peak_count++;
	}
}

static u8 g6ts_secondary_cutoff(u8 peak_value, unsigned int pass)
{
	static const u16 fractions_q12[] = { 2048, 3072, 3584 };
	u32 fraction = fractions_q12[pass];
	u64 cutoff_q24;
	u32 cutoff_q12;

	cutoff_q24 = (u64)((1U << G6TS_CLASSIFIER_SHIFT) - fraction) *
		      G6TS_SECONDARY_A_Q12;
	cutoff_q24 += (u64)fraction *
		       ((peak_value << G6TS_CLASSIFIER_SHIFT) +
			G6TS_SECONDARY_NOISE_Q12);
	cutoff_q12 = (cutoff_q24 + BIT(G6TS_CLASSIFIER_SHIFT - 1)) >>
		      G6TS_CLASSIFIER_SHIFT;
	return min_t(u32, U8_MAX,
		     (cutoff_q12 + BIT(G6TS_CLASSIFIER_SHIFT - 1)) >>
		     G6TS_CLASSIFIER_SHIFT);
}

static bool g6ts_secondary_neighbour(const struct g6ts *ts, int row, int col,
				     u8 cutoff)
{
	unsigned int index;

	if (row < 0 || row >= G6TS_HEAT_ROWS ||
	    col < 0 || col >= G6TS_HEAT_COLS)
		return false;
	index = row * G6TS_HEAT_COLS + col;
	return ts->heat_component[index] && !ts->heat_work[index] &&
	       ts->heatmap[index] <= cutoff;
}

static void g6ts_secondary_features(struct g6ts *ts,
				    struct g6ts_contact *contact)
{
	static const s8 neighbours[][2] = {
		{ -1, 0 }, { 0, -1 }, { 1, 0 }, { 0, 1 },
	};
	unsigned int area = (contact->max_col - contact->min_col + 1) *
			    (contact->max_row - contact->min_row + 1);
	unsigned int pass;

	for (pass = 0; pass < 3; pass++) {
		contact->features_q12[1 + pass] =
			contact->pixels << G6TS_CLASSIFIER_SHIFT;
		contact->features_q12[4 + pass] = 1U << G6TS_CLASSIFIER_SHIFT;
	}
	/* FUN_180041fd8 only reruns bounded candidates above 0.05 + 0.02. */
	if (area >= 0x4e3 || g6ts_signal_q12(contact->peak_value) <= 287)
		return;

	for (pass = 0; pass < 3; pass++) {
		u8 cutoff = g6ts_secondary_cutoff(contact->peak_value, pass);
		unsigned int accepted = 0, largest = 0, start;

		memset(ts->heat_work, 0, sizeof(ts->heat_work));
		for (start = 0; start < G6TS_HEAT_SAMPLES; start++) {
			unsigned int head = 0, tail = 0, pixels = 0;
			u8 peak = U8_MAX;

			if (!ts->heat_component[start] || ts->heat_work[start] ||
			    ts->heatmap[start] > cutoff)
				continue;
			ts->heat_work[start] = 1;
			ts->heat_queue[tail++] = start;
			while (head < tail) {
				unsigned int index = ts->heat_queue[head++];
				unsigned int row = index / G6TS_HEAT_COLS;
				unsigned int col = index % G6TS_HEAT_COLS;
				unsigned int n;

				pixels++;
				peak = min_t(u8, peak, ts->heatmap[index]);
				for (n = 0; n < ARRAY_SIZE(neighbours); n++) {
					int nr = row + neighbours[n][1];
					int nc = col + neighbours[n][0];
					unsigned int neighbour;

					if (!g6ts_secondary_neighbour(ts, nr, nc, cutoff))
						continue;
					neighbour = nr * G6TS_HEAT_COLS + nc;
					ts->heat_work[neighbour] = 1;
					ts->heat_queue[tail++] = neighbour;
				}
			}
			if (pixels <= 2 &&
			    g6ts_signal_q12(peak) <= G6TS_SECONDARY_SEED_Q12)
				continue;
			accepted++;
			largest = max(largest, pixels);
		}
		contact->features_q12[1 + pass] =
			largest << G6TS_CLASSIFIER_SHIFT;
		contact->features_q12[4 + pass] =
			accepted << G6TS_CLASSIFIER_SHIFT;
	}
}

static void g6ts_geometry_features(struct g6ts *ts,
				   struct g6ts_contact *contact)
{
	u64 sum = 0, sum_x = 0, sum_y = 0;
	u64 sum_xx = 0, sum_yy = 0, sum_xy = 0;
	s64 var_x, var_y, covariance, trace, delta, discriminant;
	u64 denominator;
	u32 sigma_major_q12, sigma_minor_q12;
	u32 major_axis, minor_axis;
	u32 pitch_tenth_mm, major_tenth_mm, minor_tenth_mm;
	unsigned int index;

	pitch_tenth_mm = DIV_ROUND_CLOSEST(ts->himetric_width ?
					   ts->himetric_width :
					   G6TS_DEFAULT_HIMETRIC_WIDTH,
					   (G6TS_HEAT_COLS - 1) * 10U);
	contact->touch_major = pitch_tenth_mm;
	contact->touch_minor = pitch_tenth_mm;

	for (index = 0; index < G6TS_HEAT_SAMPLES; index++) {
		u32 row, col;
		s32 signal;

		if (!ts->heat_component[index])
			continue;
		row = index / G6TS_HEAT_COLS;
		col = index % G6TS_HEAT_COLS;
		signal = g6ts_signal_q12(ts->heatmap[index]);
		if (signal <= 0)
			continue;
		sum += signal;
		sum_x += (u64)signal * col;
		sum_y += (u64)signal * row;
		sum_xx += (u64)signal * col * col;
		sum_yy += (u64)signal * row * row;
		sum_xy += (u64)signal * col * row;
	}
	if (!sum) {
		contact->features_q12[7] = 1U << G6TS_CLASSIFIER_SHIFT;
		contact->features_q12[8] = 1U << G6TS_CLASSIFIER_SHIFT;
		return;
	}

	denominator = sum * sum;
	var_x = div64_s64(((s64)(sum_xx * sum) - (s64)(sum_x * sum_x)) *
			    (1U << G6TS_CLASSIFIER_SHIFT), denominator);
	var_y = div64_s64(((s64)(sum_yy * sum) - (s64)(sum_y * sum_y)) *
			    (1U << G6TS_CLASSIFIER_SHIFT), denominator);
	covariance = div64_s64(((s64)(sum_xy * sum) - (s64)(sum_x * sum_y)) *
				 (1U << G6TS_CLASSIFIER_SHIFT), denominator);
	trace = max_t(s64, 0, var_x + var_y);
	delta = var_x - var_y;
	discriminant = int_sqrt64(delta * delta + 4 * covariance * covariance);
	sigma_major_q12 = int_sqrt64(((trace + discriminant) / 2) <<
				     G6TS_CLASSIFIER_SHIFT);
	sigma_minor_q12 = int_sqrt64(max_t(s64, 0, (trace - discriminant) / 2) <<
				     G6TS_CLASSIFIER_SHIFT);
	/*
	 * For a uniform elliptical contact, full diameter is 4*sigma along
	 * each principal axis.  Convert to 0.1 mm (ABS_MT_TOUCH_* res=10)
	 * floored at one sensor pitch so light single-cell taps stay nonzero.
	 */
	major_tenth_mm = ((u64)sigma_major_q12 * 4U * pitch_tenth_mm) >>
			 G6TS_CLASSIFIER_SHIFT;
	minor_tenth_mm = ((u64)sigma_minor_q12 * 4U * pitch_tenth_mm) >>
			 G6TS_CLASSIFIER_SHIFT;
	contact->touch_major = clamp_t(u32, major_tenth_mm, pitch_tenth_mm,
				       G6TS_MT_AXIS_MAX_TENTH_MM);
	contact->touch_minor = clamp_t(u32, minor_tenth_mm, pitch_tenth_mm,
				       contact->touch_major);

	major_axis = max_t(u32, 1U << G6TS_CLASSIFIER_SHIFT,
			   ((u64)sigma_major_q12 * G6TS_AXIS_SCALE_Q12) >>
			   G6TS_CLASSIFIER_SHIFT);
	minor_axis = max_t(u32, 1U << G6TS_CLASSIFIER_SHIFT,
			   ((u64)sigma_minor_q12 * G6TS_AXIS_SCALE_Q12) >>
			   G6TS_CLASSIFIER_SHIFT);
	contact->features_q12[7] = div_u64((u64)major_axis <<
					   G6TS_CLASSIFIER_SHIFT, minor_axis);
	if (contact->pixels < 2) {
		contact->features_q12[8] = 1U << G6TS_CLASSIFIER_SHIFT;
	} else {
		s64 spread = trace * G6TS_SPREAD_SCALE_Q12;
		u32 samples = (1U << G6TS_CLASSIFIER_SHIFT) *
			      (contact->pixels - 1);

		contact->features_q12[8] = div64_s64(spread, samples);
	}
}

static s32 g6ts_halo_feature(struct g6ts *ts,
			     const struct g6ts_contact *contact)
{
	static const s8 neighbours[][2] = {
		{ -1, 0 }, { 0, -1 }, { 1, 0 }, { 0, 1 },
	};
	u8 state[16][16];
	int origin_col = contact->min_col - 3;
	int origin_row = contact->min_row - 3;
	s32 peak = g6ts_signal_q12(contact->peak_value);
	s32 peak_threshold = peak / 4;
	s64 halo = 0;
	unsigned int radius, n;
	int row, col;

	if (contact->max_col - contact->min_col + 1 >= 11 ||
	    contact->max_row - contact->min_row + 1 >= 11 || peak <= 0)
		return G6TS_HALO_UNAVAILABLE_Q12;
	memset(state, 5, sizeof(state));
	for (row = max(0, origin_row); row <=
		     min_t(int, G6TS_HEAT_ROWS - 1, contact->max_row + 3); row++) {
		for (col = max(0, origin_col); col <=
		     min_t(int, G6TS_HEAT_COLS - 1, contact->max_col + 3); col++) {
			unsigned int index = row * G6TS_HEAT_COLS + col;

			if (ts->heat_component[index])
				state[row - origin_row][col - origin_col] = 0;
			else if (!g6ts_heat_active(ts, index))
				state[row - origin_row][col - origin_col] = 4;
		}
	}
	for (row = contact->min_row; row <= contact->max_row; row++) {
		for (col = contact->min_col; col <= contact->max_col; col++) {
			if (state[row - origin_row][col - origin_col])
				continue;
			for (n = 0; n < ARRAY_SIZE(neighbours); n++) {
				int nc = col + neighbours[n][0];
				int nr = row + neighbours[n][1];

				if (nr < 0 || nr >= G6TS_HEAT_ROWS || nc < 0 ||
				    nc >= G6TS_HEAT_COLS ||
				    state[nr - origin_row][nc - origin_col] != 4)
					continue;
				if (g6ts_signal_q12(ts->heatmap[nr * G6TS_HEAT_COLS + nc]) >
				    peak_threshold)
					state[nr - origin_row][nc - origin_col] = 1;
			}
		}
	}
	for (radius = 1; radius <= 2; radius++) {
		for (row = max_t(int, 0, contact->min_row - radius); row <=
		     min_t(int, G6TS_HEAT_ROWS - 1, contact->max_row + radius); row++) {
			for (col = max_t(int, 0, contact->min_col - radius); col <=
			     min_t(int, G6TS_HEAT_COLS - 1, contact->max_col + radius); col++) {
				unsigned int current_index;
				s32 current_signal;

				if (state[row - origin_row][col - origin_col] > radius)
					continue;
				current_index = row * G6TS_HEAT_COLS + col;
				current_signal = g6ts_signal_q12(ts->heatmap[current_index]);
				for (n = 0; n < ARRAY_SIZE(neighbours); n++) {
					int nc = col + neighbours[n][0];
					int nr = row + neighbours[n][1];
					unsigned int next_index;
					s32 next;

					if (nr < 0 || nr >= G6TS_HEAT_ROWS || nc < 0 ||
					    nc >= G6TS_HEAT_COLS ||
					    state[nr - origin_row][nc - origin_col] != 4)
						continue;
					next_index = nr * G6TS_HEAT_COLS + nc;
					next = g6ts_signal_q12(ts->heatmap[next_index]);
					if (next < peak_threshold && current_signal > next &&
					    current_signal > 0 &&
					    (s64)next << G6TS_CLASSIFIER_SHIFT >
						(s64)current_signal * G6TS_HALO_RATIO_Q12) {
						state[nr - origin_row][nc - origin_col] =
							radius + 1;
						halo += next;
					}
				}
			}
		}
	}
	return div64_s64(halo << G6TS_CLASSIFIER_SHIFT, peak);
}

static u8 g6ts_classify_contact(struct g6ts_contact *contact)
{
	s64 best_score = S64_MIN;
	u8 best_class = 0;
	unsigned int class, row, col;

	for (class = 0; class < ARRAY_SIZE(g6ts_classifier_models); class++) {
		const struct g6ts_classifier_model *model =
			&g6ts_classifier_models[class];
		s64 distance = 0;

		contact->scores_q24[class] =
			-9999LL * (1LL << G6TS_SCORE_SHIFT);
		if (contact->pixels > model->max_points)
			continue;
		for (row = 0; row < G6TS_FEATURE_COUNT; row++) {
			s64 transformed = 0;

			for (col = row; col < G6TS_FEATURE_COUNT; col++) {
				s32 residual;

				if (col == 9 && contact->features_q12[col] ==
						G6TS_HALO_UNAVAILABLE_Q12)
					residual = 0;
				else
					residual = contact->features_q12[col] -
						   model->means_q12[col];
				transformed += (s64)residual *
					       model->transform_q12[row][col];
			}
			transformed >>= G6TS_CLASSIFIER_SHIFT;
			if (transformed > INT_MAX || transformed < -INT_MAX ||
			    distance > S64_MAX - transformed * transformed) {
				distance = S64_MAX;
				break;
			}
			distance += transformed * transformed;
		}
		if (distance != S64_MAX) {
			s64 score = ((s64)model->score_offset_q12 <<
				     G6TS_CLASSIFIER_SHIFT) - distance / 2 +
				    G6TS_RUNTIME_OFFSET_Q24;

			contact->scores_q24[class] = score;
		}
	}
	for (class = 0; class < G6TS_CLASS_COUNT; class++) {
		if (contact->scores_q24[class] > best_score) {
			best_score = contact->scores_q24[class];
			best_class = class;
		}
	}
	return best_class;
}

static bool g6ts_contact_touches_edge(const struct g6ts_contact *contact)
{
	return contact->min_col == 0 ||
	       contact->max_col == G6TS_HEAT_COLS - 1 ||
	       contact->min_row == 0 ||
	       contact->max_row == G6TS_HEAT_ROWS - 1;
}

static bool g6ts_is_edge_palm(const struct g6ts_contact *contact,
			      bool post_classify)
{
	unsigned int edge_span = 0;

	if (!contact->touches_edge)
		return false;

	if (contact->min_col == 0 || contact->max_col == G6TS_HEAT_COLS - 1)
		edge_span = max_t(unsigned int, edge_span,
				  contact->max_row - contact->min_row + 1);
	if (contact->min_row == 0 || contact->max_row == G6TS_HEAT_ROWS - 1)
		edge_span = max_t(unsigned int, edge_span,
				  contact->max_col - contact->min_col + 1);
	if (edge_span >= G6TS_EDGE_PALM_SPAN)
		return true;

	return post_classify &&
	       contact->pixels >= G6TS_EDGE_PALM_PIXELS &&
	       !contact->shape_allowed;
}

static void g6ts_finalize_component(struct g6ts *ts,
				    struct g6ts_contact *contact)
{
	u32 peak_sig;

	contact->touches_edge = g6ts_contact_touches_edge(contact);
	contact->x = div_u64(contact->weighted_x * G6TS_LOGICAL_MAX,
			     (u64)contact->strength * (G6TS_HEAT_COLS - 1));
	contact->y = div_u64(contact->weighted_y * G6TS_LOGICAL_MAX,
			     (u64)contact->strength * (G6TS_HEAT_ROWS - 1));
	contact->output_x = contact->x;
	contact->output_y = contact->y;
	peak_sig = G6TS_HEAT_SIGNAL_ZERO -
		   min_t(u8, contact->peak_value, G6TS_HEAT_SIGNAL_ZERO);
	contact->pressure = clamp_t(u32,
				    DIV_ROUND_CLOSEST(peak_sig *
						      G6TS_MT_PRESSURE_MAX,
						      G6TS_HEAT_SIGNAL_ZERO),
				    1U, G6TS_MT_PRESSURE_MAX);
	contact->sensor_x_q24 = div_u64(contact->weighted_x << 24,
					contact->strength);
	contact->sensor_y_q24 = div_u64(contact->weighted_y << 24,
					contact->strength);
	g6ts_phase76_output_centroid(ts, contact);
	g6ts_local_peak_counts(ts, contact);
	contact->features_q12[0] = contact->pixels << G6TS_CLASSIFIER_SHIFT;
	g6ts_secondary_features(ts, contact);
	g6ts_geometry_features(ts, contact);
	contact->features_q12[9] = g6ts_halo_feature(ts, contact);
	contact->shape_class = g6ts_classify_contact(contact);
	/* FUN_180049458 permits the classifier's classes zero and two. */
	contact->shape_allowed = contact->shape_class == 0 ||
				 contact->shape_class == 2;
	dev_dbg(&ts->spi->dev,
		"candidate class=%u allowed=%u pixels=%u edge=%u peaks=%u/%u halo_q12=%d scores=[%lld,%lld,%lld,%lld]\n",
		contact->shape_class, contact->shape_allowed, contact->pixels,
		contact->touches_edge, contact->local_peak_count,
		contact->strong_local_peak_count, contact->features_q12[9],
		contact->scores_q24[0], contact->scores_q24[1],
		contact->scores_q24[2], contact->scores_q24[3]);
}

struct g6ts_split_peak {
	u8 row;
	u8 col;
	u8 strength;
};

static bool g6ts_peaks_have_valley(const struct g6ts *ts,
				   const struct g6ts_split_peak *a,
				   const struct g6ts_split_peak *b)
{
	unsigned int min_peak = min_t(unsigned int, a->strength, b->strength);
	unsigned int min_seg = U8_MAX;
	unsigned int step;

	for (step = 1; step <= 3; step++) {
		unsigned int r = ((unsigned int)a->row * (4U - step) +
				  (unsigned int)b->row * step + 2U) / 4U;
		unsigned int c = ((unsigned int)a->col * (4U - step) +
				  (unsigned int)b->col * step + 2U) / 4U;
		u8 raw = ts->heatmap[r * G6TS_HEAT_COLS + c];
		unsigned int sig = raw < G6TS_HEAT_SIGNAL_ZERO ?
				   G6TS_HEAT_SIGNAL_ZERO - raw : 0;

		min_seg = min_t(unsigned int, min_seg, sig);
	}

	return min_seg * 100U <= min_peak * G6TS_SPLIT_VALLEY_PCT;
}

/*
 * Split a merged close-pinch component into separate fingers only when at
 * least two strong local maxima sit >= 2 sensor cells (~8 mm) apart with a
 * >= 15% capacitive valley between them.  Flat palms and single fingertips
 * fail the valley test and remain unsplit.
 */
static bool g6ts_try_split_merged_component(struct g6ts *ts,
					    unsigned int comp_len,
					    unsigned int *contact_count)
{
	static const s8 neighbours[][2] = {
		{ -1, 0 }, { 1, 0 }, { 0, -1 }, { 0, 1 },
	};
	struct g6ts_split_peak candidates[G6TS_LOCAL_PEAK_CAPACITY];
	struct g6ts_split_peak selected[G6TS_SPLIT_MAX_PEAKS];
	unsigned int cand_count = 0, sel_count = 0;
	unsigned int i, j, k;

	for (i = 0; i < comp_len && cand_count < G6TS_LOCAL_PEAK_CAPACITY; i++) {
		unsigned int index = ts->heat_queue[i];
		unsigned int row = index / G6TS_HEAT_COLS;
		unsigned int col = index % G6TS_HEAT_COLS;
		u8 raw = ts->heatmap[index];
		s32 current_signal;
		unsigned int lower = 0, near_equal = 0, n;
		unsigned int equal_index = UINT_MAX;
		bool is_peak;

		if (raw > G6TS_HEAT_STRONG_MAX)
			continue;
		current_signal = g6ts_signal_q12(raw);
		if (current_signal <= G6TS_LOCAL_PEAK_FLOOR_Q12)
			continue;
		for (n = 0; n < ARRAY_SIZE(neighbours); n++) {
			int nc = (int)col + neighbours[n][0];
			int nr = (int)row + neighbours[n][1];
			unsigned int nidx;
			s32 nsig;

			if (nr < 0 || nr >= G6TS_HEAT_ROWS ||
			    nc < 0 || nc >= G6TS_HEAT_COLS) {
				nidx = UINT_MAX;
				nsig = 0;
			} else {
				nidx = nr * G6TS_HEAT_COLS + nc;
				nsig = g6ts_signal_q12(ts->heatmap[nidx]);
			}
			if (current_signal > nsig) {
				lower++;
			} else if (current_signal == nsig) {
				near_equal++;
				equal_index = nidx;
			}
		}
		is_peak = lower == 4 ||
			  (lower == 3 && near_equal == 1 && index < equal_index);
		if (!is_peak)
			continue;

		candidates[cand_count].row = row;
		candidates[cand_count].col = col;
		candidates[cand_count].strength = G6TS_HEAT_SIGNAL_ZERO - raw;
		cand_count++;
	}

	if (cand_count < 2)
		return false;

	/* Sort strongest peaks first. */
	for (i = 1; i < cand_count; i++) {
		struct g6ts_split_peak key = candidates[i];

		j = i;
		while (j > 0 && candidates[j - 1].strength < key.strength) {
			candidates[j] = candidates[j - 1];
			j--;
		}
		candidates[j] = key;
	}

	for (i = 0; i < cand_count && sel_count < G6TS_SPLIT_MAX_PEAKS; i++) {
		bool distinct = true;

		for (j = 0; j < sel_count; j++) {
			int dr = (int)candidates[i].row - selected[j].row;
			int dc = (int)candidates[i].col - selected[j].col;

			if ((unsigned int)(dr * dr + dc * dc) <
			    G6TS_SPLIT_MIN_DIST_SQ ||
			    !g6ts_peaks_have_valley(ts, &candidates[i],
						    &selected[j])) {
				distinct = false;
				break;
			}
		}
		if (distinct)
			selected[sel_count++] = candidates[i];
	}

	if (sel_count < 2)
		return false;

	for (k = 0; k < sel_count; k++) {
		struct g6ts_contact sub = {
			.min_col = G6TS_HEAT_COLS - 1,
			.min_row = G6TS_HEAT_ROWS - 1,
			.peak_value = U8_MAX,
		};

		memset(ts->heat_component, 0, sizeof(ts->heat_component));
		for (i = 0; i < comp_len; i++) {
			unsigned int index = ts->heat_queue[i];
			unsigned int row = index / G6TS_HEAT_COLS;
			unsigned int col = index % G6TS_HEAT_COLS;
			unsigned int best_k = 0;
			unsigned int best_d = UINT_MAX;

			for (j = 0; j < sel_count; j++) {
				int dr = (int)row - selected[j].row;
				int dc = (int)col - selected[j].col;
				unsigned int d = dr * dr + dc * dc;

				if (d < best_d) {
					best_d = d;
					best_k = j;
				}
			}
			if (best_k != k)
				continue;

			ts->heat_component[index] = 1;
			sub.pixels++;
			sub.strength += G6TS_HEAT_SIGNAL_ZERO - ts->heatmap[index];
			sub.weighted_x += (u64)col *
					  (G6TS_HEAT_SIGNAL_ZERO - ts->heatmap[index]);
			sub.weighted_y += (u64)row *
					  (G6TS_HEAT_SIGNAL_ZERO - ts->heatmap[index]);
			sub.min_col = min_t(u8, sub.min_col, col);
			sub.max_col = max_t(u8, sub.max_col, col);
			sub.min_row = min_t(u8, sub.min_row, row);
			sub.max_row = max_t(u8, sub.max_row, row);
			sub.peak_value = min_t(u8, sub.peak_value,
					       ts->heatmap[index]);
		}
		if (!sub.pixels || !sub.strength)
			continue;
		if (sub.pixels < G6TS_HEAT_MIN_PIXELS &&
		    sub.peak_value > G6TS_HEAT_STRONG_MAX)
			continue;
		g6ts_finalize_component(ts, &sub);
		if (g6ts_is_edge_palm(&sub, true)) {
			ts->edge_palm_rejections++;
			continue;
		}
		g6ts_store_contact(ts, &sub, contact_count);
	}

	memset(ts->heat_component, 0, sizeof(ts->heat_component));
	ts->merged_splits++;
	return true;
}

static unsigned int g6ts_find_contacts(struct g6ts *ts)
{
	unsigned int contact_count = 0;
	unsigned int start;

	memset(ts->heat_seen, 0, sizeof(ts->heat_seen));

	for (start = 0; start < G6TS_HEAT_SAMPLES; start++) {
		struct g6ts_contact contact = {
			.min_col = G6TS_HEAT_COLS - 1,
			.min_row = G6TS_HEAT_ROWS - 1,
			.peak_value = U8_MAX,
		};
		unsigned int head = 0, tail = 0, comp_len, idx;

		if (ts->heat_seen[start] || !g6ts_heat_active(ts, start))
			continue;
		ts->heat_seen[start] = 1;
		ts->heat_queue[tail++] = start;

		while (head < tail) {
			unsigned int index = ts->heat_queue[head++];
			unsigned int row = index / G6TS_HEAT_COLS;
			unsigned int col = index % G6TS_HEAT_COLS;
			unsigned int strength = G6TS_HEAT_SIGNAL_ZERO -
						ts->heatmap[index];
			int dr, dc;

			contact.pixels++;
			contact.strength += strength;
			contact.weighted_x += (u64)col * strength;
			contact.weighted_y += (u64)row * strength;
			contact.min_col = min_t(u8, contact.min_col, col);
			contact.max_col = max_t(u8, contact.max_col, col);
			contact.min_row = min_t(u8, contact.min_row, row);
			contact.max_row = max_t(u8, contact.max_row, row);
			contact.peak_value = min_t(u8, contact.peak_value,
						   ts->heatmap[index]);

			for (dr = -1; dr <= 1; dr++) {
				for (dc = -1; dc <= 1; dc++) {
					int neighbour_row = row + dr;
					int neighbour_col = col + dc;
					unsigned int neighbour;

					if (abs(dr) + abs(dc) != 1 ||
					    neighbour_row < 0 ||
					    neighbour_row >= G6TS_HEAT_ROWS ||
					    neighbour_col < 0 ||
					    neighbour_col >= G6TS_HEAT_COLS)
						continue;
					neighbour = neighbour_row * G6TS_HEAT_COLS +
						    neighbour_col;
					if (ts->heat_seen[neighbour] ||
					    !g6ts_heat_active(ts, neighbour))
						continue;
					ts->heat_seen[neighbour] = 1;
					ts->heat_queue[tail++] = neighbour;
				}
			}
		}

		comp_len = tail;
		ts->component_total++;
		if (contact.pixels < G6TS_HEAT_MIN_PIXELS &&
		    contact.peak_value > G6TS_HEAT_STRONG_MAX) {
			ts->weak_rejections++;
			continue;
		}
		if (ts->nsr_valid) {
			unsigned int sensor_row = div_u64(contact.weighted_y +
							     contact.strength / 2,
							     contact.strength);

			if (sensor_row < ARRAY_SIZE(g6ts_nsr_row_to_bin)) {
				u8 bin = g6ts_nsr_row_to_bin[sensor_row];

				if (bin < ts->nsr_bin_count &&
				    ts->nsr_bins[bin] > G6TS_NSR_CUTOFF) {
					ts->nsr_rejections++;
					continue;
				}
			}
		}
		if (contact.pixels > G6TS_HEAT_MERGED_MAX_PIXELS ||
		    contact.max_col - contact.min_col + 1 > G6TS_HEAT_PALM_SPAN ||
		    contact.max_row - contact.min_row + 1 > G6TS_HEAT_PALM_SPAN) {
			ts->palm_rejections++;
			continue;
		}
		if (contact.pixels >= 6 &&
		    g6ts_try_split_merged_component(ts, comp_len,
						    &contact_count))
			continue;

		if (contact.pixels > G6TS_HEAT_PALM_PIXELS) {
			ts->palm_rejections++;
			continue;
		}
		contact.touches_edge = g6ts_contact_touches_edge(&contact);
		if (g6ts_is_edge_palm(&contact, false)) {
			ts->edge_palm_rejections++;
			continue;
		}

		memset(ts->heat_component, 0, sizeof(ts->heat_component));
		for (idx = 0; idx < comp_len; idx++)
			ts->heat_component[ts->heat_queue[idx]] = 1;
		g6ts_finalize_component(ts, &contact);
		memset(ts->heat_component, 0, sizeof(ts->heat_component));
		if (g6ts_is_edge_palm(&contact, true)) {
			ts->edge_palm_rejections++;
			continue;
		}
		g6ts_store_contact(ts, &contact, &contact_count);
	}

	ts->contact_total += contact_count;
	return contact_count;
}

static u16 g6ts_assignment_coordinate(u32 position_q24, u32 scale_q24)
{
	u64 scaled = (u64)position_q24 * scale_q24;

	return min_t(u64, (scaled + BIT_ULL(47)) >> 48, S16_MAX);
}

static unsigned int g6ts_track_distance(const struct g6ts_track *track,
					const struct g6ts_contact *contact)
{
	const u32 x_scale = G6TS_ASSIGN_X_SCALE_Q24;
	const u32 y_scale = G6TS_ASSIGN_Y_SCALE_Q24;
	s64 predicted_x = clamp_t(s64,
		(s64)track->sensor_x_q24 + track->sensor_velocity_x_q24,
		0, (s64)(G6TS_HEAT_COLS - 1) << 24);
	s64 predicted_y = clamp_t(s64,
		(s64)track->sensor_y_q24 + track->sensor_velocity_y_q24,
		0, (s64)(G6TS_HEAT_ROWS - 1) << 24);
	s32 track_x = g6ts_assignment_coordinate(predicted_x, x_scale);
	s32 track_y = g6ts_assignment_coordinate(predicted_y, y_scale);
	s32 candidate_x = g6ts_assignment_coordinate(contact->sensor_x_q24,
						     x_scale);
	s32 candidate_y = g6ts_assignment_coordinate(contact->sensor_y_q24,
						     y_scale);
	s32 dx = track_x - candidate_x;
	s32 dy = track_y - candidate_y;
	u32 squared = dx * dx + dy * dy;

	if (squared >= G6TS_ASSIGN_RADIUS * G6TS_ASSIGN_RADIUS)
		return G6TS_ASSIGN_INVALID_COST;
	return squared;
}

static u8 g6ts_confirmation_requirement(const struct g6ts *ts,
					const struct g6ts_contact *contact)
{
	unsigned int i;
	u8 required = G6TS_TRACK_CONFIRM_STRONG;

	if (contact->pixels < G6TS_HEAT_MIN_PIXELS)
		required = G6TS_TRACK_CONFIRM_WEAK;
	if (contact->touches_edge &&
	    contact->pixels >= G6TS_EDGE_CONFIRM_PIXELS)
		required = max_t(u8, required, G6TS_TRACK_CONFIRM_EDGE);
	if (!contact->shape_allowed)
		required = max_t(u8, required, G6TS_TRACK_CONFIRM_WEAK);

	for (i = 0; i < G6TS_MAX_CONTACTS; i++) {
		const struct g6ts_track *track = &ts->tracks[i];
		s32 dx, dy;
		u64 squared;

		if (!track->active || !track->confirmed || track->missed)
			continue;
		dx = (s32)track->raw_x - contact->x;
		dy = (s32)track->raw_y - contact->y;
		squared = (s64)dx * dx + (s64)dy * dy;
		if (squared > (u64)G6TS_TRACK_SPLIT_RADIUS *
				      G6TS_TRACK_SPLIT_RADIUS)
			continue;

		/*
		 * A new, smaller island beside an established finger is commonly a
		 * transient split of that finger.  Preserve real close multitouch by
		 * accepting it after sustained evidence rather than deleting it.
		 */
		required = max_t(u8, required, G6TS_TRACK_CONFIRM_WEAK);
		if ((u64)contact->strength * 2 <= track->strength ||
		    (u32)contact->pixels * 2 <= track->pixels)
			required = G6TS_TRACK_CONFIRM_SPLIT;
	}

	return required;
}

/*
 * Windows builds a predicted-position Euclidean cost matrix and solves a
 * global assignment.  Use a square matrix with explicit dummy rows/columns
 * so a gated-out pairing loses to closing one track and opening another.
 */
static void g6ts_assign_tracks(struct g6ts *ts, unsigned int count,
			       int contact_slots[G6TS_MAX_CONTACTS])
{
	struct g6ts_assignment_workspace *work = &ts->assignment;
	unsigned int active_count = 0;
	unsigned int n, row, col, i, j;

	memset(work, 0, sizeof(*work));
	for (i = 0; i < G6TS_MAX_CONTACTS; i++)
		contact_slots[i] = -1;

	for (i = 0; i < G6TS_MAX_CONTACTS; i++) {
		if (ts->tracks[i].active)
			work->active_slots[active_count++] = i;
	}
	if (!active_count || !count)
		return;

	n = active_count + count;
	for (row = 0; row < n; row++) {
		for (col = 0; col < n; col++) {
			if (row < active_count && col < count) {
				struct g6ts_track *track;

				track = &ts->tracks[work->active_slots[row]];
				work->cost[row][col] =
					g6ts_track_distance(track,
							    &ts->contacts[col]);
			} else if (row < active_count || col < count) {
				work->cost[row][col] = G6TS_ASSIGN_UNMATCHED_COST;
			} else {
				work->cost[row][col] = 0;
			}
		}
	}

	/* Hungarian minimum-cost assignment, using one-based work arrays. */
	for (i = 1; i <= n; i++) {
		int j0 = 0;

		work->p[0] = i;
		for (j = 0; j <= n; j++) {
			work->minv[j] = INT_MAX;
			work->used[j] = false;
		}
		do {
			int i0, delta = INT_MAX, j1 = 0;

			work->used[j0] = true;
			i0 = work->p[j0];
			for (j = 1; j <= n; j++) {
				int reduced_cost;

				if (work->used[j])
					continue;
				reduced_cost = work->cost[i0 - 1][j - 1] -
					       work->u[i0] - work->v[j];
				if (reduced_cost < work->minv[j]) {
					work->minv[j] = reduced_cost;
					work->way[j] = j0;
				}
				if (work->minv[j] < delta) {
					delta = work->minv[j];
					j1 = j;
				}
			}
			for (j = 0; j <= n; j++) {
				if (work->used[j]) {
					work->u[work->p[j]] += delta;
					work->v[j] -= delta;
				} else if (j) {
					work->minv[j] -= delta;
				}
			}
			j0 = j1;
		} while (work->p[j0]);

		do {
			int j1 = work->way[j0];

			work->p[j0] = work->p[j1];
			j0 = j1;
		} while (j0);
	}

	for (j = 1; j <= n; j++) {
		row = work->p[j] - 1;
		col = j - 1;
		if (row < active_count && col < count &&
		    work->cost[row][col] < G6TS_ASSIGN_INVALID_COST)
			contact_slots[col] = work->active_slots[row];
	}
	for (i = 0; i < count; i++)
		if (contact_slots[i] >= 0)
			ts->assignment_matches++;
}

static void g6ts_update_track(struct g6ts_track *track,
			      const struct g6ts_contact *contact)
{
	u16 old_x = track->raw_x;
	u16 old_y = track->raw_y;
	u32 old_sensor_x_q24 = track->sensor_x_q24;
	u32 old_sensor_y_q24 = track->sensor_y_q24;

	track->raw_x = contact->x;
	track->raw_y = contact->y;
	track->velocity_x = (s32)contact->x - old_x;
	track->velocity_y = (s32)contact->y - old_y;
	track->sensor_x_q24 = contact->sensor_x_q24;
	track->sensor_y_q24 = contact->sensor_y_q24;
	track->sensor_velocity_x_q24 = (s32)((s64)contact->sensor_x_q24 -
						 old_sensor_x_q24);
	track->sensor_velocity_y_q24 = (s32)((s64)contact->sensor_y_q24 -
						 old_sensor_y_q24);
	track->output_x = contact->output_x;
	track->output_y = contact->output_y;
	track->touch_major = contact->touch_major;
	track->touch_minor = contact->touch_minor;
	track->pressure = contact->pressure;
	track->strength = contact->strength;
	track->pixels = contact->pixels;
	track->shape_class = contact->shape_class;
	if (track->age < U16_MAX)
		track->age++;
	if (!track->confirmed && contact->shape_allowed &&
	    track->evidence < U8_MAX) {
		track->evidence++;
		if (track->evidence >= track->required_evidence)
			track->confirmed = true;
	}
	track->missed = 0;
}

static int g6ts_new_track(struct g6ts *ts,
			  const struct g6ts_contact *contact)
{
	unsigned int slot;

	for (slot = 0; slot < G6TS_MAX_CONTACTS; slot++) {
		struct g6ts_track *track = &ts->tracks[slot];

		if (track->active)
			continue;
		memset(track, 0, sizeof(*track));
		track->raw_x = contact->x;
		track->raw_y = contact->y;
		track->output_x = contact->output_x;
		track->output_y = contact->output_y;
		track->sensor_x_q24 = contact->sensor_x_q24;
		track->sensor_y_q24 = contact->sensor_y_q24;
		track->touch_major = contact->touch_major;
		track->touch_minor = contact->touch_minor;
		track->pressure = contact->pressure;
		track->strength = contact->strength;
		track->pixels = contact->pixels;
		track->shape_class = contact->shape_class;
		track->age = 1;
		track->evidence = contact->shape_allowed ? 1 : 0;
		track->required_evidence =
			g6ts_confirmation_requirement(ts, contact);
		track->confirmed = track->required_evidence <= 1;
		track->active = true;
		ts->new_tracks++;
		return slot;
	}
	return -ENOSPC;
}

static void g6ts_advance_unmatched_tracks(struct g6ts *ts,
					  unsigned long current_slots)
{
	unsigned int i;

	for (i = 0; i < G6TS_MAX_CONTACTS; i++) {
		struct g6ts_track *track = &ts->tracks[i];

		if (!track->active || (current_slots & BIT(i)))
			continue;
		if (track->missed < G6TS_CONTACT_HOLD_FRAMES) {
			track->missed++;
			track->velocity_x /= 2;
			track->velocity_y /= 2;
			track->sensor_velocity_x_q24 /= 2;
			track->sensor_velocity_y_q24 /= 2;
		} else {
			memset(track, 0, sizeof(*track));
		}
	}
}

static unsigned long
g6ts_create_unmatched_tracks(struct g6ts *ts, unsigned int count,
			     const int contact_slots[G6TS_MAX_CONTACTS],
			     unsigned long current_slots)
{
	unsigned int i;

	for (i = 0; i < count; i++) {
		int slot;

		if (contact_slots[i] >= 0)
			continue;
		slot = g6ts_new_track(ts, &ts->contacts[i]);
		if (slot >= 0)
			current_slots |= BIT(slot);
	}
	return current_slots;
}

static void g6ts_collect_linux_contacts(struct g6ts *ts,
					unsigned long current_slots)
{
	const u32 x_scale = G6TS_ASSIGN_X_SCALE_Q24;
	const u32 y_scale = G6TS_ASSIGN_Y_SCALE_Q24;
	unsigned long suppressed_slots = 0;
	unsigned int reported = 0;
	unsigned int i, j;

	/*
	 * Suppress duplicate sub-blobs whose physical centers lie within 6 mm
	 * (< 36 mm^2) on the same frame, keeping the stronger/older finger.
	 */
	for (i = 0; i < G6TS_MAX_CONTACTS; i++) {
		const struct g6ts_track *first = &ts->tracks[i];
		u16 first_x, first_y;

		if (!first->active || !first->confirmed ||
		    !(current_slots & BIT(i)) || (suppressed_slots & BIT(i)))
			continue;
		first_x = g6ts_assignment_coordinate(first->sensor_x_q24,
						     x_scale);
		first_y = g6ts_assignment_coordinate(first->sensor_y_q24,
						     y_scale);
		for (j = i + 1; j < G6TS_MAX_CONTACTS; j++) {
			const struct g6ts_track *second = &ts->tracks[j];
			u16 second_x, second_y;
			s32 dx, dy;

			if (!second->active || !second->confirmed ||
			    !(current_slots & BIT(j)) ||
			    (suppressed_slots & BIT(j)))
				continue;
			second_x = g6ts_assignment_coordinate(second->sensor_x_q24,
							      x_scale);
			second_y = g6ts_assignment_coordinate(second->sensor_y_q24,
							      y_scale);
			dx = (s32)first_x - second_x;
			dy = (s32)first_y - second_y;
			if ((u32)(dx * dx + dy * dy) >=
			    G6TS_DUPLICATE_MERGE_DIST_SQ)
				continue;

			if (second->strength > first->strength ||
			    (second->strength == first->strength &&
			     second->age > first->age)) {
				suppressed_slots |= BIT(i);
				ts->duplicate_merges++;
				break;
			}
			suppressed_slots |= BIT(j);
			ts->duplicate_merges++;
		}
	}

	for (i = 0; i < G6TS_MAX_CONTACTS; i++) {
		struct g6ts_track *track = &ts->tracks[i];

		/* Retained tracks remain assignable but never become ghost contacts. */
		if (!track->active || !track->confirmed ||
		    !(current_slots & BIT(i)) || (suppressed_slots & BIT(i)))
			continue;
		input_mt_slot(ts->input, i);
		input_mt_report_slot_state(ts->input, MT_TOOL_FINGER, true);
		touchscreen_report_pos(ts->input, &ts->prop, track->output_x,
				       track->output_y, true);
		input_report_abs(ts->input, ABS_MT_TOUCH_MAJOR,
				 track->touch_major);
		input_report_abs(ts->input, ABS_MT_TOUCH_MINOR,
				 track->touch_minor);
		input_report_abs(ts->input, ABS_MT_PRESSURE, track->pressure);
		reported++;
	}
	input_mt_sync_frame(ts->input);
	input_sync(ts->input);
	ts->output_frames++;
	ts->output_contacts += reported;
}

static int g6ts_report_heat_contacts(struct g6ts *ts, const u8 *content,
				     size_t content_len)
{
	u64 started_ns = ktime_get_ns();
	unsigned long current_slots = 0;
	int contact_slots[G6TS_MAX_CONTACTS];
	unsigned int count, i;
	int ret;

	ret = g6ts_extract_heatmap(ts, content, content_len);
	if (ret) {
		if (ret == -ENOENT)
			ts->non_touch_heat_frames++;
		else
			ts->heat_errors++;
		return ret;
	}
	count = g6ts_find_contacts(ts);
	g6ts_assign_tracks(ts, count, contact_slots);

	for (i = 0; i < count; i++) {
		int slot = contact_slots[i];

		if (slot < 0)
			continue;
		g6ts_update_track(&ts->tracks[slot], &ts->contacts[i]);
		current_slots |= BIT(slot);
	}

	/*
	 * The frame transaction is deliberately explicit and single-threaded:
	 * assignment -> matched updates -> unmatched lifecycle -> new tracks ->
	 * final Linux collection.  No input event escapes an intermediate stage.
	 */
	g6ts_advance_unmatched_tracks(ts, current_slots);
	current_slots = g6ts_create_unmatched_tracks(ts, count, contact_slots,
						     current_slots);
	g6ts_collect_linux_contacts(ts, current_slots);
	ts->heat_frames++;
	started_ns = ktime_get_ns() - started_ns;
	ts->processing_ns_total += started_ns;
	ts->processing_ns_max = max(ts->processing_ns_max, started_ns);

	return 0;
}

static void g6ts_release_contacts(struct g6ts *ts)
{
	input_mt_sync_frame(ts->input);
	input_sync(ts->input);
	memset(ts->tracks, 0, sizeof(ts->tracks));
}

static void g6ts_handle_data_report(struct g6ts *ts)
{
	const u8 *payload = ts->body + HIDSPI_INPUT_BODY_HEADER_SIZE;
	u16 x, y;
	bool active;

	if (ts->last_class != DATA)
		return;
	/*
	 * Heat is demand-driven on this panel: the first frame may not exist until
	 * a finger reaches the glass.  Phase 77 therefore opens the response path
	 * after the mode handshake, but suppresses every non-Heat input report
	 * until a complete Heat frame has passed the normal structural parser.
	 */
	if (ts->awaiting_ready_heat &&
	    !g6ts_is_heat_report_id(ts->last_content_id))
		return;

	if (ts->last_content_id == 0x40 && ts->last_content_len == 5) {
		active = payload[0] & BIT(0);
		x = get_unaligned_le16(&payload[1]);
		y = get_unaligned_le16(&payload[3]);

		input_report_key(ts->input, BTN_TOUCH, active);
		if (active)
			touchscreen_report_pos(ts->input, &ts->prop, x, y, false);
		input_sync(ts->input);
		return;
	}

	if (g6ts_is_heat_report_id(ts->last_content_id) &&
	    ts->last_content_len + 1 <= G6TS_MAX_BODY) {
		int ret;

		ret = g6ts_report_heat_contacts(ts, payload, ts->last_content_len);
		if (ret == -ENOENT)
			return;
		if (ret) {
			if (ts->awaiting_ready_heat)
				ts->ready_verification_failures++;
			g6ts_release_contacts(ts);
			dev_warn_ratelimited(&ts->spi->dev,
					     "malformed Heat frame: %d\n", ret);
		} else if (ts->awaiting_ready_heat) {
			ts->awaiting_ready_heat = false;
			ts->ready_heat_frames++;
			dev_info(&ts->spi->dev,
				 "touch input ready after first valid Heat frame\n");
		}
	}
}

/* Read one complete pending HID-over-SPI response, and never retry. */
static int g6ts_dma_read_response(struct g6ts *ts)
{
	const struct hidspi_dev_descriptor *descriptor;
	s64 interrupt_edges;
	size_t body_len;
	u16 words;
	int pending;
	int ret;

	g6ts_clear_last_response(ts);
	pending = g6ts_pending(ts);
	interrupt_edges = atomic64_read(&ts->interrupt_edges);
	if (pending <= 0 &&
	    interrupt_edges <= ts->handled_interrupt_edges) {
		return pending < 0 ? pending : -EAGAIN;
	}
	ts->handled_interrupt_edges = interrupt_edges;

	ret = g6ts_dma_read_pair(ts, g6ts_header_cmd, ts->last_header,
				 sizeof(ts->last_header));
	if (ret) {
		ts->fatal_transport_error = true;
		return ret;
	}

	if ((ts->last_header[0] & 0x0f) != G6TS_HEADER_VERSION ||
	    ts->last_header[3] != G6TS_HEADER_SYNC) {
		/* Let the panel retire the body transaction before rechecking. */
		usleep_range(100, 200);
		pending = g6ts_pending(ts);
		if (!pending) {
			ts->quiesced_empty_reads++;
			return -EAGAIN;
		}
		if (pending < 0)
			return pending;
		dev_warn_ratelimited(&ts->spi->dev,
				     "invalid HID-SPI header=%4ph ready=%d\n",
				     ts->last_header, g6ts_pending(ts));
		return -EPROTO;
	}

	words = get_unaligned_le16(&ts->last_header[1]) & 0x3fff;
	body_len = (size_t)words * 4;
	if (body_len < HIDSPI_INPUT_BODY_HEADER_SIZE ||
	    body_len > G6TS_MAX_BODY)
		return -EMSGSIZE;
	usleep_range(G6TS_HEADER_BODY_MIN_US, G6TS_HEADER_BODY_MAX_US);

	ret = g6ts_dma_read_pair(ts, g6ts_body_cmd, ts->body, body_len);
	if (ret) {
		ts->fatal_transport_error = true;
		return ret;
	}

	ts->last_class = ts->body[0];
	ts->last_content_len = get_unaligned_le16(&ts->body[1]);
	ts->last_content_id = ts->body[3];
	if (ts->last_content_len > body_len - HIDSPI_INPUT_BODY_HEADER_SIZE)
		return -EPROTO;

	if (ts->last_class == DEVICE_DESCRIPTOR_RESPONSE &&
	    ts->last_content_len == HIDSPI_DEVICE_DESCRIPTOR_SIZE) {
		descriptor = (const struct hidspi_dev_descriptor *)
			     (ts->body + HIDSPI_INPUT_BODY_HEADER_SIZE);
		ts->expected_report_descriptor_len =
			le16_to_cpu(descriptor->rep_desc_len);
	}
	/* Recovery consumes and validates replies before reopening Linux input. */
	if (READ_ONCE(ts->mode_enabled))
		g6ts_handle_data_report(ts);
	return 0;
}

/* io_lock is held by both the IRQ thread and the recovery worker. */
static void g6ts_note_panel_reset_locked(struct g6ts *ts,
					 bool schedule_recovery)
{
	ts->reset_notifications++;
	ts->mode_enabled = false;
	ts->awaiting_ready_heat = false;
	g6ts_release_contacts(ts);
	dev_warn(&ts->spi->dev,
		 "panel reset notification #%llu\n",
		 ts->reset_notifications);

	if (schedule_recovery && !READ_ONCE(ts->stopping))
		schedule_delayed_work(&ts->recovery_work,
				      msecs_to_jiffies(G6TS_RECOVERY_DELAY_MS));
}

/* io_lock is held and the caller has observed one complete IRQ read failure. */
static void g6ts_note_host_fault_locked(struct g6ts *ts, int error)
{
	if (error == -EPROTO || error == -EMSGSIZE)
		ts->irq_protocol_errors++;
	else
		ts->irq_transport_errors++;
	ts->last_host_fault = error;

	/*
	 * A fresh hardware recovery is allowed to use the transport again.  A new
	 * fatal error during that attempt will still stop the worker, preserving
	 * bounded-failure behavior.
	 */
	ts->fatal_transport_error = false;
	ts->mode_enabled = false;
	ts->awaiting_ready_heat = false;
	ts->host_fault_recoveries++;
	g6ts_release_contacts(ts);
	dev_warn(&ts->spi->dev,
		 "host HID-SPI fault #%llu ret=%d; scheduling cold recovery\n",
		 ts->host_fault_recoveries, error);

	if (!READ_ONCE(ts->stopping))
		schedule_delayed_work(&ts->recovery_work,
				      msecs_to_jiffies(G6TS_RECOVERY_DELAY_MS));
}

static irqreturn_t g6ts_interrupt_thread(int irq, void *data)
{
	struct g6ts *ts = data;
	int ret;

	if (!READ_ONCE(ts->mode_enabled))
		return IRQ_HANDLED;

	mutex_lock(&ts->io_lock);
	if (g6ts_has_unread_response(ts)) {
		ret = g6ts_dma_read_response(ts);
		if (ret) {
			if (ret != -EAGAIN)
				g6ts_note_host_fault_locked(ts, ret);
		} else if (ts->last_class == RESET_RESPONSE) {
			g6ts_note_panel_reset_locked(ts, true);
		} else {
			ts->cadence_single_response_irqs++;
		}
	}
	mutex_unlock(&ts->io_lock);
	return IRQ_HANDLED;
}

static int g6ts_parse_pm_mode(const char *mode_name, enum g6ts_pm_mode *mode)
{
	if (!mode_name || !strcmp(mode_name, "off")) {
		*mode = G6TS_PM_OFF;
		return 0;
	}
	if (!strcmp(mode_name, "sleep")) {
		*mode = G6TS_PM_SLEEP;
		return 0;
	}
	if (!strcmp(mode_name, "legacy")) {
		*mode = G6TS_PM_LEGACY;
		return 0;
	}
	return -EINVAL;
}

static int g6ts_hidspi_set_power_locked(struct g6ts *ts,
					enum hidspi_power_state state)
{
	u8 power_state = (u8)state;
	unsigned long deadline;
	unsigned int response_index;
	int ret;

	ret = g6ts_dma_hidspi_output(ts, COMMAND_CONTENT,
				     HIDSPI_SET_POWER_CMD_ID,
				     &power_state, sizeof(power_state));
	if (ret)
		return ret;

	/*
	 * Per the HID-over-SPI specification and Windows HidSpiCx state
	 * machine (c_writingPowerDownRequest -> c_completingPowerSuccessOnPowerDown),
	 * SET_POWER(SLEEP) and SET_POWER(OFF) complete on write with no device
	 * response.  Only SET_POWER(ON) produces a COMMAND_RESPONSE ACK.
	 */
	if (state != HIDSPI_ON)
		return 0;

	deadline = jiffies + msecs_to_jiffies(G6TS_HIDSPI_CMD_TIMEOUT_MS);
	for (response_index = 0;
	     response_index < G6TS_FEATURE_RESPONSE_LIMIT;
	     response_index++) {
		unsigned int remaining_ms;

		if (!time_before(jiffies, deadline))
			return -ETIMEDOUT;
		remaining_ms = max_t(unsigned int, 1U,
				     jiffies_to_msecs(deadline - jiffies));

		ret = g6ts_wait_pending(ts, remaining_ms);
		if (ret)
			return ret;

		ret = g6ts_dma_read_response(ts);
		if (ret)
			return ret;

		if (ts->last_class == COMMAND_RESPONSE &&
		    ts->last_content_id == HIDSPI_SET_POWER_CMD_ID &&
		    ts->last_content_len == 1 &&
		    ts->body[HIDSPI_INPUT_BODY_HEADER_SIZE] ==
		    G6TS_HIDSPI_CMD_STATUS_OK)
			return 0;
		if (ts->last_class == RESET_RESPONSE)
			return -EPIPE;
		if (ts->last_class == DATA ||
		    (ts->last_class == OUTPUT_REPORT_RESPONSE &&
		     ts->last_content_id == 0x09))
			continue;

		return -EPROTO;
	}

	return -EOVERFLOW;
}

static int g6ts_dma_feature_exchange(struct g6ts *ts, u8 report_type,
				     u8 content_id, const u8 *content,
				     size_t content_len)
{
	u8 expected_class;
	unsigned int response_index;
	int ret;

	if (report_type == SET_FEATURE)
		expected_class = SET_FEATURE_RESPONSE;
	else if (report_type == GET_FEATURE)
		expected_class = GET_FEATURE_RESPONSE;
	else
		return -EINVAL;

	ret = g6ts_dma_hidspi_output(ts, report_type, content_id,
				     content, content_len);
	if (ret) {
		ts->fatal_transport_error = true;
		return ret;
	}

	for (response_index = 0;
	     response_index < G6TS_FEATURE_RESPONSE_LIMIT;
	     response_index++) {
		ret = g6ts_wait_pending(ts, 1000);
		if (ret)
			return ret;

		ret = g6ts_dma_read_response(ts);
		if (ret)
			return ret;

		if (ts->last_class == expected_class &&
		    ts->last_content_id == content_id)
			return 0;
		if (ts->last_class == RESET_RESPONSE) {
			g6ts_note_panel_reset_locked(ts, false);
			return -EPIPE;
		}

		/* Streaming data can precede a solicited feature response. */
		if (ts->last_class == DATA)
			continue;
		if (ts->last_class == OUTPUT_REPORT_RESPONSE &&
		    ts->last_content_id == 0x09)
			continue;

		return -EPROTO;
	}

	return -EOVERFLOW;
}

static int g6ts_expect_response(struct g6ts *ts, u8 response_class,
				u8 content_id, size_t min_content_len)
{
	if (ts->last_class != response_class ||
	    ts->last_content_id != content_id ||
	    ts->last_content_len < min_content_len)
		return -EPROTO;

	return 0;
}

static int g6ts_validate_sp11_device_descriptor(struct g6ts *ts)
{
	const struct hidspi_dev_descriptor *descriptor;

	if (ts->last_class != DEVICE_DESCRIPTOR_RESPONSE ||
	    ts->last_content_id != 0 ||
	    ts->last_content_len != HIDSPI_DEVICE_DESCRIPTOR_SIZE)
		return -EPROTO;

	descriptor = (const struct hidspi_dev_descriptor *)
		(ts->body + HIDSPI_INPUT_BODY_HEADER_SIZE);
	if (le16_to_cpu(descriptor->dev_desc_len) !=
			HIDSPI_DEVICE_DESCRIPTOR_SIZE ||
	    le16_to_cpu(descriptor->bcd_ver) != 0x0300 ||
	    le16_to_cpu(descriptor->rep_desc_len) !=
			G6TS_SP11_REPORT_DESCRIPTOR_LEN ||
	    le16_to_cpu(descriptor->max_input_len) != G6TS_SP11_MAX_INPUT_LEN ||
	    le16_to_cpu(descriptor->max_output_len) != G6TS_SP11_MAX_OUTPUT_LEN ||
	    le16_to_cpu(descriptor->max_frag_len) != G6TS_SP11_MAX_FRAGMENT_LEN ||
	    le16_to_cpu(descriptor->vendor_id) != G6TS_SP11_VENDOR_ID ||
	    le16_to_cpu(descriptor->product_id) != G6TS_SP11_PRODUCT_ID ||
	    le16_to_cpu(descriptor->version_id) != G6TS_SP11_VERSION_ID ||
	    le16_to_cpu(descriptor->flags) != G6TS_SP11_DESCRIPTOR_FLAGS ||
	    le32_to_cpu(descriptor->reserved) != 0)
		return -ENODEV;

	return 0;
}

static int g6ts_recovery_read_expected(struct g6ts *ts, u8 response_class,
				       u8 content_id, size_t min_content_len);

static void g6ts_build_clean_feedback_a1(u8 content[G6TS_FEEDBACK_LEN])
{
	memset(content, 0, G6TS_FEEDBACK_LEN);
	content[0] = 0x8e;
	content[1] = 0xa1;
	content[2] = G6TS_CLEAN_DISPLAY_ON;
	content[3] = 0;
	put_unaligned_le32(G6TS_CLEAN_HINGE_SLATE, &content[4]);
	put_unaligned_le16(G6TS_CLEAN_FAST_HOST_ID, &content[40]);
}

static void g6ts_build_clean_feedback_a5(struct g6ts *ts,
					 u8 content[G6TS_FEEDBACK_LEN])
{
	memset(content, 0, G6TS_FEEDBACK_LEN);
	content[0] = 0x8e;
	content[1] = 0xa5;
	content[2] = ts->feedback_v06_seq;
	content[3] = BIT(1);
	put_unaligned_le16(G6TS_CLEAN_FAST_HOST_ID, &content[39]);
	put_unaligned_le16(0x0040, &content[46]);
}

/*
 * Clean Col02 touch initialization: parses live Feature 0x06 geometry, sends
 * the attach-time Display-On A1 + V06 A5 feedback pair, enables HEAT streaming
 * via Feature 0x05=1, and acknowledges Feature 0x70={0x01} to satisfy the
 * firmware attach watchdog without touching Col05 (pen BLE) or Col06 (CFU).
 */
static int g6ts_clean_touch_attach_locked(struct g6ts *ts)
{
	u8 feedback[G6TS_FEEDBACK_LEN];
	const u8 *content;
	int ret;

	ts->initialization_stage = G6TS_INIT_HEAT_CAPS06;
	ret = g6ts_dma_feature_exchange(ts, GET_FEATURE, 0x06, NULL, 0);
	if (ret)
		return ret;
	ret = g6ts_expect_response(ts, GET_FEATURE_RESPONSE, 0x06,
				   G6TS_FEATURE06_LEN);
	if (ret || ts->last_content_len != G6TS_FEATURE06_LEN)
		return ret ? ret : -EPROTO;
	content = ts->body + HIDSPI_INPUT_BODY_HEADER_SIZE;
	ret = g6ts_parse_feature06(ts, content, ts->last_content_len);
	if (ret)
		return ret;

	ts->initialization_stage = G6TS_INIT_FEEDBACK_A1;
	g6ts_build_clean_feedback_a1(feedback);
	ret = g6ts_dma_hidspi_output(ts, OUTPUT_REPORT, 0x09, feedback,
				     sizeof(feedback));
	if (ret) {
		ts->fatal_transport_error = true;
		return ret;
	}
	ret = g6ts_recovery_read_expected(ts, DATA, 0xa0, 1);
	if (ret || ts->last_content_len != 1 ||
	    ts->body[HIDSPI_INPUT_BODY_HEADER_SIZE] != 0x01)
		return ret ? ret : -EPROTO;

	ts->initialization_stage = G6TS_INIT_FEEDBACK_A5;
	g6ts_build_clean_feedback_a5(ts, feedback);
	ret = g6ts_dma_hidspi_output(ts, OUTPUT_REPORT, 0x09, feedback,
				     sizeof(feedback));
	if (ret) {
		ts->fatal_transport_error = true;
		return ret;
	}
	ts->feedback_v06_seq++;

	ts->initialization_stage = G6TS_INIT_SET_FEATURE05;
	ret = g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x05,
					g6ts_mode_enable,
					sizeof(g6ts_mode_enable));
	if (ret)
		return ret;
	ret = g6ts_expect_response(ts, SET_FEATURE_RESPONSE, 0x05, 0);
	if (ret || ts->last_content_len != 0)
		return ret ? ret : -EPROTO;

	/*
	 * Live hardware isolation proves the Touch G6 firmware runs a 5.19 s
	 * post-attach watchdog waiting for the one-byte Feature 0x70={0x01}
	 * host acknowledgment.  Machine-specific report 0x56 (BT MAC) and
	 * CFU 0x60/0x65 are not required.
	 */
	ts->initialization_stage = G6TS_INIT_GET_FEATURE70;
	ret = g6ts_dma_feature_exchange(ts, GET_FEATURE, 0x70, NULL, 0);
	if (ret)
		return ret;
	ret = g6ts_expect_response(ts, GET_FEATURE_RESPONSE, 0x70, 1);
	if (ret)
		return ret;

	ts->initialization_stage = G6TS_INIT_SET_FEATURE70;
	ret = g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x70,
					g6ts_mode_enable,
					sizeof(g6ts_mode_enable));
	if (ret)
		return ret;
	ret = g6ts_expect_response(ts, SET_FEATURE_RESPONSE, 0x70, 0);
	if (ret || ts->last_content_len != 0)
		return ret ? ret : -EPROTO;

	ts->initialization_stage = G6TS_INIT_WAIT_HEAT;
	ts->awaiting_ready_heat = true;
	ts->mode_enabled = true;
	return 0;
}

static int g6ts_recovery_read_expected(struct g6ts *ts, u8 response_class,
				       u8 content_id, size_t min_content_len)
{
	unsigned int response_index;
	int ret;

	for (response_index = 0;
	     response_index < G6TS_FEATURE_RESPONSE_LIMIT;
	     response_index++) {
		ret = g6ts_wait_pending(ts, 1000);
		if (ret)
			return ret;

		ret = g6ts_dma_read_response(ts);
		if (ret)
			return ret;
		if (ts->last_class == response_class &&
		    ts->last_content_id == content_id &&
		    ts->last_content_len >= min_content_len)
			return 0;
		if (ts->last_class == RESET_RESPONSE) {
			g6ts_note_panel_reset_locked(ts, false);
			return -EPIPE;
		}

		/* Stale input can precede the solicited reply. */
		if (ts->last_class == DATA ||
		    (ts->last_class == OUTPUT_REPORT_RESPONSE &&
		     ts->last_content_id == 0x09))
			continue;

		return -EPROTO;
	}

	return -EOVERFLOW;
}

static int g6ts_full_reinitialize_locked(struct g6ts *ts)
{
	int ret;

	ts->mode_enabled = false;
	ts->awaiting_ready_heat = false;
	ts->expected_report_descriptor_len = 0;
	ts->initialization_stage = G6TS_INIT_IDLE;

	ts->hardware_recovery_attempts++;
	ret = g6ts_power_off(ts);
	if (ret)
		return ret;
	msleep(100);
	ret = g6ts_power_on(ts);
	if (ret)
		return ret;

	ts->initialization_stage = G6TS_INIT_RESET_RESPONSE;
	ret = g6ts_wait_pending(ts, 1000);
	if (ret)
		goto out;
	ret = g6ts_dma_read_response(ts);
	if (ret)
		goto out;
	ret = g6ts_expect_response(ts, RESET_RESPONSE, 0, 0);
	if (ret)
		goto out;

	ts->initialization_stage = G6TS_INIT_DEVICE_DESCRIPTOR;
	ret = g6ts_dma_output(ts, g6ts_device_descriptor_cmd,
			      sizeof(g6ts_device_descriptor_cmd));
	if (ret) {
		ts->fatal_transport_error = true;
		goto out;
	}
	ret = g6ts_recovery_read_expected(ts, DEVICE_DESCRIPTOR_RESPONSE, 0,
					  HIDSPI_DEVICE_DESCRIPTOR_SIZE);
	if (ret)
		goto out;
	ret = g6ts_validate_sp11_device_descriptor(ts);
	if (ret)
		goto out;
	if (!ts->expected_report_descriptor_len ||
	    ts->expected_report_descriptor_len >
		    G6TS_MAX_BODY - HIDSPI_INPUT_BODY_HEADER_SIZE) {
		ret = -EPROTO;
		goto out;
	}

	ts->initialization_stage = G6TS_INIT_REPORT_DESCRIPTOR;
	ret = g6ts_dma_output(ts, g6ts_report_descriptor_cmd,
			      sizeof(g6ts_report_descriptor_cmd));
	if (ret) {
		ts->fatal_transport_error = true;
		goto out;
	}
	ret = g6ts_recovery_read_expected(ts, REPORT_DESCRIPTOR_RESPONSE, 0,
					  ts->expected_report_descriptor_len);
	if (ret || ts->last_content_len != ts->expected_report_descriptor_len) {
		if (!ret)
			ret = -EPROTO;
		goto out;
	}

	ret = g6ts_clean_touch_attach_locked(ts);
	if (ret)
		goto out;
	return 0;
out:
	ts->mode_enabled = false;
	return ret;
}

static void g6ts_recovery_work(struct work_struct *work)
{
	struct g6ts *ts = container_of(to_delayed_work(work), struct g6ts,
				      recovery_work);
	bool retry = false;
	int ret;

	mutex_lock(&ts->io_lock);
	if (ts->stopping) {
		mutex_unlock(&ts->io_lock);
		return;
	}

	ts->mode_enabled = false;
	g6ts_release_contacts(ts);
	ret = g6ts_full_reinitialize_locked(ts);
	if (!ret) {
		ts->recovery_fail_streak = 0;
		ts->recovery_successes++;
		dev_info(&ts->spi->dev,
			 "touch controller initialized recoveries=%llu resets=%llu\n",
			 ts->recovery_successes, ts->reset_notifications);
	} else {
		ts->recovery_failures++;
		ts->recovery_fail_streak++;
		retry = !ts->fatal_transport_error &&
			ts->recovery_fail_streak < G6TS_RECOVERY_LIMIT;
		dev_warn(&ts->spi->dev,
			 "touch controller initialization failed stage=%s ret=%d failures=%llu%s\n",
			 g6ts_initialization_stage_name(ts->initialization_stage),
			 ret, ts->recovery_failures,
			 retry ? "; retrying" : "");
	}
	mutex_unlock(&ts->io_lock);

	if (retry && !READ_ONCE(ts->stopping))
		schedule_delayed_work(&ts->recovery_work,
				      msecs_to_jiffies(G6TS_RECOVERY_RETRY_MS));
}

static int g6ts_probe(struct spi_device *spi)
{
	enum g6ts_pm_mode pm_mode;
	struct g6ts *ts;
	int ret;

	if (g6ts_parse_pm_mode(g6ts_pm_sleep_mode, &pm_mode))
		return dev_err_probe(&spi->dev, -EINVAL,
				     "invalid pm_sleep_mode '%s' (expected off, sleep, or legacy)\n",
				     g6ts_pm_sleep_mode);

	ts = devm_kzalloc(&spi->dev, sizeof(*ts), GFP_KERNEL);
	if (!ts)
		return -ENOMEM;
	ts->body = devm_kmalloc(&spi->dev, G6TS_MAX_BODY, GFP_KERNEL);
	if (!ts->body)
		return -ENOMEM;
	ts->spi = spi;
	ts->interrupt_gpio = devm_gpiod_get(&spi->dev, "interrupt", GPIOD_IN);
	if (IS_ERR(ts->interrupt_gpio))
		return dev_err_probe(&spi->dev, PTR_ERR(ts->interrupt_gpio),
				     "failed to get interrupt GPIO\n");
	ts->interrupt_irq = gpiod_to_irq(ts->interrupt_gpio);
	if (ts->interrupt_irq < 0)
		return dev_err_probe(&spi->dev, ts->interrupt_irq,
				     "failed to map interrupt GPIO\n");
	ret = devm_request_threaded_irq(&spi->dev, ts->interrupt_irq,
					g6ts_interrupt_edge,
					g6ts_interrupt_thread,
					IRQF_TRIGGER_FALLING | IRQF_ONESHOT,
					G6TS_NAME, ts);
	if (ret)
		return dev_err_probe(&spi->dev, ret,
				     "failed to request interrupt\n");
	ts->power_gpio =
		devm_gpiod_get_optional(&spi->dev, "power", GPIOD_OUT_LOW);
	if (IS_ERR(ts->power_gpio))
		return dev_err_probe(&spi->dev, PTR_ERR(ts->power_gpio),
				     "failed to get power GPIO\n");
	ts->reset_gpio =
		devm_gpiod_get_optional(&spi->dev, "reset", GPIOD_OUT_LOW);
	if (IS_ERR(ts->reset_gpio))
		return dev_err_probe(&spi->dev, PTR_ERR(ts->reset_gpio),
				     "failed to get reset GPIO\n");
	if (!!ts->power_gpio != !!ts->reset_gpio)
		return dev_err_probe(&spi->dev, -EINVAL,
				     "power and reset GPIOs must be paired\n");

	mutex_init(&ts->io_lock);
	INIT_DELAYED_WORK(&ts->recovery_work, g6ts_recovery_work);
	spi_set_drvdata(spi, ts);
	ret = devm_device_add_group(&spi->dev, &g6ts_attribute_group);
	if (ret)
		return dev_err_probe(&spi->dev, ret,
				     "failed to create diagnostic attributes\n");
	spi->max_speed_hz = G6TS_SPI_HZ;
	spi->bits_per_word = 8;
	spi->mode = SPI_MODE_0 | SPI_TX_QUAD | SPI_RX_QUAD;
	ret = spi_setup(spi);
	if (ret)
		return dev_err_probe(&spi->dev, ret, "spi_setup failed\n");

	ts->input = devm_input_allocate_device(&spi->dev);
	if (!ts->input)
		return -ENOMEM;
	ts->input->name = "Microsoft Surface G6 Touch";
	ts->input->id.bustype = BUS_SPI;
	ts->input->dev.parent = &spi->dev;
	ts->sensor_rows = G6TS_HEAT_ROWS;
	ts->sensor_cols = G6TS_HEAT_COLS;
	ts->himetric_width = G6TS_DEFAULT_HIMETRIC_WIDTH;
	ts->himetric_height = G6TS_DEFAULT_HIMETRIC_HEIGHT;
	input_set_abs_params(ts->input, ABS_MT_POSITION_X, 0,
			     G6TS_LOGICAL_MAX, 0, 0);
	input_set_abs_params(ts->input, ABS_MT_POSITION_Y, 0,
			     G6TS_LOGICAL_MAX, 0, 0);
	input_set_abs_params(ts->input, ABS_MT_TOUCH_MAJOR, 0,
			     G6TS_MT_AXIS_MAX_TENTH_MM, 0, 0);
	input_set_abs_params(ts->input, ABS_MT_TOUCH_MINOR, 0,
			     G6TS_MT_AXIS_MAX_TENTH_MM, 0, 0);
	input_set_abs_params(ts->input, ABS_MT_PRESSURE, 0,
			     G6TS_MT_PRESSURE_MAX, 0, 0);
	input_abs_set_res(ts->input, ABS_MT_TOUCH_MAJOR, G6TS_MT_AXIS_RES);
	input_abs_set_res(ts->input, ABS_MT_TOUCH_MINOR, G6TS_MT_AXIS_RES);
	g6ts_apply_input_resolution(ts);
	touchscreen_parse_properties(ts->input, true, &ts->prop);
	ret = input_mt_init_slots(ts->input, G6TS_MAX_CONTACTS,
				  INPUT_MT_DIRECT | INPUT_MT_DROP_UNUSED |
				  INPUT_MT_TRACK);
	if (ret)
		return dev_err_probe(&spi->dev, ret,
				     "failed to initialize touch slots\n");
	ret = input_register_device(ts->input);
	if (ret)
		return dev_err_probe(&spi->dev, ret,
				     "failed to register touch input\n");

	ret = g6ts_power_on(ts);
	if (ret)
		return ret;

	g6ts_clear_last_response(ts);
	schedule_delayed_work(&ts->recovery_work,
			      msecs_to_jiffies(G6TS_RECOVERY_DELAY_MS));
	dev_info(&spi->dev,
		 "touch controller initialization scheduled profile=production-v1\n");
	return 0;
}

static void g6ts_remove(struct spi_device *spi)
{
	struct g6ts *ts = spi_get_drvdata(spi);
	bool was_active = READ_ONCE(ts->mode_enabled);

	WRITE_ONCE(ts->stopping, true);
	WRITE_ONCE(ts->mode_enabled, false);
	disable_irq(ts->interrupt_irq);
	cancel_delayed_work_sync(&ts->recovery_work);
	mutex_lock(&ts->io_lock);
	g6ts_release_contacts(ts);
	if (was_active && !ts->fatal_transport_error)
		(void)g6ts_hidspi_set_power_locked(ts, HIDSPI_OFF);
	mutex_unlock(&ts->io_lock);
	(void)g6ts_power_off(ts);
}

static int g6ts_suspend(struct device *dev)
{
	struct g6ts *ts = dev_get_drvdata(dev);
	bool was_active = READ_ONCE(ts->mode_enabled);
	enum g6ts_pm_mode mode = G6TS_PM_OFF;
	int ret = 0;

	g6ts_parse_pm_mode(g6ts_pm_sleep_mode, &mode);
	WRITE_ONCE(ts->mode_enabled, false);
	disable_irq(ts->interrupt_irq);
	cancel_delayed_work_sync(&ts->recovery_work);

	mutex_lock(&ts->io_lock);
	g6ts_release_contacts(ts);
	ts->suspended_in_sleep = false;

	if (mode == G6TS_PM_SLEEP && was_active && !ts->fatal_transport_error) {
		ret = g6ts_hidspi_set_power_locked(ts, HIDSPI_SLEEP);
		if (!ret) {
			ts->pm_sleep_acks++;
			ts->suspended_in_sleep = true;
		} else {
			ts->pm_sleep_fallbacks++;
			dev_warn(&ts->spi->dev,
				 "SET_POWER(SLEEP) failed (%d); falling back to power off\n",
				 ret);
			ret = g6ts_power_off(ts);
		}
	} else if (mode == G6TS_PM_OFF) {
		if (was_active && !ts->fatal_transport_error) {
			if (!g6ts_hidspi_set_power_locked(ts, HIDSPI_OFF))
				ts->pm_off_acks++;
			else
				ts->pm_sleep_fallbacks++;
		}
		ret = g6ts_power_off(ts);
	} else {
		ret = g6ts_power_off(ts);
	}
	ts->handled_interrupt_edges = atomic64_read(&ts->interrupt_edges);
	mutex_unlock(&ts->io_lock);

	if (ret) {
		enable_irq(ts->interrupt_irq);
		schedule_delayed_work(&ts->recovery_work,
				      msecs_to_jiffies(G6TS_RECOVERY_DELAY_MS));
	}

	return ret;
}

static int g6ts_resume(struct device *dev)
{
	struct g6ts *ts = dev_get_drvdata(dev);
	u64 started_ns = ktime_get_ns();
	enum g6ts_pm_mode mode = G6TS_PM_OFF;
	bool warm_woke = false;
	int ret = 0;

	g6ts_parse_pm_mode(g6ts_pm_sleep_mode, &mode);
	mutex_lock(&ts->io_lock);
	ts->fatal_transport_error = false;
	ts->recovery_fail_streak = 0;

	if (ts->suspended_in_sleep) {
		ts->suspended_in_sleep = false;
		ret = g6ts_hidspi_set_power_locked(ts, HIDSPI_ON);
		if (!ret) {
			ts->pm_warm_wakes++;
			ts->handled_interrupt_edges =
				atomic64_read(&ts->interrupt_edges);
			WRITE_ONCE(ts->mode_enabled, true);
			warm_woke = true;
		} else {
			ts->pm_cold_fallbacks++;
			dev_warn(&ts->spi->dev,
				 "SET_POWER(ON) warm wake failed (%d); scheduling cold recovery\n",
				 ret);
			ret = 0;
		}
	} else if (mode == G6TS_PM_LEGACY) {
		ret = g6ts_power_on(ts);
	}

	ts->pm_last_wake_us = div_u64(ktime_get_ns() - started_ns, 1000);
	mutex_unlock(&ts->io_lock);
	if (ret)
		return ret;

	enable_irq(ts->interrupt_irq);
	if (!warm_woke)
		schedule_delayed_work(&ts->recovery_work,
				      mode == G6TS_PM_LEGACY ?
				      msecs_to_jiffies(G6TS_RECOVERY_DELAY_MS) :
				      0);
	return 0;
}

static DEFINE_SIMPLE_DEV_PM_OPS(g6ts_pm_ops, g6ts_suspend, g6ts_resume);

static const struct acpi_device_id g6ts_acpi_match[] = {
	{ "MSHW0485", 0 },
	{ }
};
MODULE_DEVICE_TABLE(acpi, g6ts_acpi_match);

static const struct of_device_id g6ts_of_match[] = {
	{ .compatible = "microsoft,mshw0485" },
	{ }
};
MODULE_DEVICE_TABLE(of, g6ts_of_match);

static const struct spi_device_id g6ts_spi_id[] = {
	{ "mshw0485" },
	{ }
};
MODULE_DEVICE_TABLE(spi, g6ts_spi_id);

static struct spi_driver g6ts_driver = {
	.driver = {
		.name = G6TS_NAME,
		.acpi_match_table = ACPI_PTR(g6ts_acpi_match),
		.of_match_table = g6ts_of_match,
		.pm = pm_sleep_ptr(&g6ts_pm_ops),
	},
	.id_table = g6ts_spi_id,
	.probe = g6ts_probe,
	.remove = g6ts_remove,
};
module_spi_driver(g6ts_driver);

MODULE_DESCRIPTION("Microsoft Surface G6 MSHW0485 touchscreen driver");
MODULE_AUTHOR("SP11 reverse-engineering project");
MODULE_LICENSE("GPL");
