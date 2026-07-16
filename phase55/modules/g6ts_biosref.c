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
#include "g6ts_lifecycle_profile.h"

#define G6TS_NAME			"microsoft-g6ts"
#define G6TS_SPI_HZ			40000000U
#define G6TS_MAX_BODY			8192U
#define G6TS_HEADER_SYNC		0x5a
#define G6TS_HEADER_VERSION		0x03
#define G6TS_FEATURE_RESPONSE_LIMIT	64U
#define G6TS_HEATMAP_REPORT_ID		0x12
#define G6TS_MODE_ATTEMPT_LIMIT		3U
#define G6TS_RECOVERY_DELAY_MS		100U
#define G6TS_RECOVERY_RETRY_MS		500U
#define G6TS_RECOVERY_LIMIT		3U
#define G6TS_HEAT_ROWS			46U
#define G6TS_HEAT_COLS			68U
#define G6TS_HEAT_SAMPLES		(G6TS_HEAT_ROWS * G6TS_HEAT_COLS)
#define G6TS_HEAT_SECTION		0x0100
#define G6TS_METADATA_SECTION		0xff00
#define G6TS_NSR_BINS			16U
#define G6TS_NSR_CUTOFF			655U
/*
 * TouchPenProcessor0C83.dll converts a calibrated byte through a linear
 * lookup whose zero crossing is approximately 180.  The SP11 configuration
 * is inferred to start a candidate at raw <= 171.  Its scan-line union joins
 * only edge-adjacent cells.  One- and two-cell candidates survive only when
 * their peak is stronger than the secondary detector threshold (approximately
 * raw <= 162); all candidates of three or more cells continue downstream.
 */
#define G6TS_HEAT_SIGNAL_ZERO		180U
#define G6TS_HEAT_THRESHOLD		9U
#define G6TS_HEAT_ACTIVE_MAX		(G6TS_HEAT_SIGNAL_ZERO - G6TS_HEAT_THRESHOLD)
#define G6TS_HEAT_STRONG_MAX		162U
#define G6TS_HEAT_MIN_PIXELS		3U
#define G6TS_HEAT_PALM_PIXELS		48U
#define G6TS_HEAT_PALM_SPAN		12U
#define G6TS_MAX_CONTACTS		10U
#define G6TS_LOGICAL_MAX		32767U
#define G6TS_TRACK_MATCH_MAX		4096U
#define G6TS_CONTACT_HOLD_FRAMES	6U
#define G6TS_TRACK_CONFIRM_NORMAL	3U
#define G6TS_TRACK_CONFIRM_WEAK		5U
#define G6TS_TRACK_CONFIRM_SPLIT	8U
#define G6TS_TRACK_SPLIT_RADIUS		2048U
#define G6TS_SMOOTH_STATIONARY_MAX	64U
#define G6TS_SMOOTH_SLOW_MAX		256U
#define G6TS_SIGNAL_INTERCEPT_Q24	6710886
#define G6TS_SIGNAL_STEP_Q24		37251
#define G6TS_SECONDARY_A_Q12		645663
#define G6TS_SECONDARY_NOISE_Q12	36895
#define G6TS_SECONDARY_SEED_Q12		225
#define G6TS_AXIS_SCALE_Q12		18919
#define G6TS_SPREAD_SCALE_Q12		25736
#define G6TS_HALO_RATIO_Q12		614
#define G6TS_HALO_UNAVAILABLE_Q12	(100U << G6TS_CLASSIFIER_SHIFT)
#define G6TS_ASSIGN_MAX			(G6TS_MAX_CONTACTS * 2U)
#define G6TS_ASSIGN_UNMATCHED_COST	1000000
#define G6TS_ASSIGN_INVALID_COST	3000000

/*
 * Phase 70 keeps the hardware-validated Phase 68 policy as the default.  The
 * recovered Windows profile is opt-in until its provider-owned frame flags
 * have live ground truth.  Read-only prevents switching policy under active
 * contacts and mixing two incompatible track coordinate spaces.
 */
static bool g6ts_windows_orchestrator;
module_param_named(windows_orchestrator, g6ts_windows_orchestrator, bool, 0444);
MODULE_PARM_DESC(windows_orchestrator,
		 "Use the experimental recovered Windows frame profile (default: false)");

static const u8 g6ts_header_cmd[8] = {
	0xeb, 0x00, 0x10, 0x00, 0xff, 0xff, 0xff, 0xff,
};

static const u8 g6ts_body_cmd[8] = {
	0xeb, 0x00, 0x10, 0x04, 0xff, 0xff, 0xff, 0xff,
};

/* Windows HID-over-SPI DEVICE_DESCRIPTOR request captured in ETW. */
static const u8 g6ts_device_descriptor_cmd[8] = {
	0xe2, 0x00, 0x20, 0x00, DEVICE_DESCRIPTOR, 0x00, 0x00, 0x00,
};

static const u8 g6ts_report_descriptor_cmd[8] = {
	0xe2, 0x00, 0x20, 0x00, REPORT_DESCRIPTOR, 0x00, 0x00, 0x00,
};

static const u8 g6ts_mode_enable[] = { 0x01 };
static const u8 g6ts_mode_handshake[] = {
	0xbc, 0xe6, 0x4a, 0x2e, 0x86, 0x78, 0x00,
};

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
	u8 peak_value;
	u8 min_col;
	u8 max_col;
	u8 min_row;
	u8 max_row;
	s32 features_q12[G6TS_FEATURE_COUNT];
	s64 scores_q24[G6TS_CLASS_COUNT];
	u8 shape_class;
	bool shape_allowed;
};

struct g6ts_track {
	u32 strength;
	u16 raw_x;
	u16 raw_y;
	u16 output_x;
	u16 output_y;
	u16 pixels;
	u32 sensor_x_q24;
	u32 sensor_y_q24;
	s32 sensor_velocity_x_q24;
	s32 sensor_velocity_y_q24;
	s16 velocity_x;
	s16 velocity_y;
	u16 age;
	s64 score_history_q24[G6TS_WINDOWS_HISTORY_CAPACITY][G6TS_CLASS_COUNT];
	u8 missed;
	u8 evidence;
	u8 required_evidence;
	u8 shape_class;
	u8 windows_class;
	u8 score_history_count;
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
	unsigned long last_reset_jiffies;
	u8 nsr_bin_count;
	u8 initialization_stage;
	u8 recovery_fail_streak;
	bool nsr_valid;
	bool mode_enabled;
	bool fatal_transport_error;
	bool stopping;
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

static int g6ts_extract_nsr_metadata(struct g6ts *ts, const u8 *section,
				     size_t section_len)
{
	size_t position = 7;

	/* Windows starts its nested metadata dispatcher at section byte seven. */
	while (position < section_len) {
		size_t payload_len, record_end;
		const u8 *record;
		unsigned int count, i;

		if (section_len - position < 4)
			return -EPROTO;
		record = section + position;
		payload_len = get_unaligned_le16(record + 2);
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

		memset(ts->heatmap, 0, sizeof(ts->heatmap));
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
		if (written != G6TS_HEAT_SAMPLES)
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
	u32 major_axis, minor_axis;
	unsigned int index;

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
	major_axis = int_sqrt64(((trace + discriminant) / 2) <<
				 G6TS_CLASSIFIER_SHIFT);
	minor_axis = int_sqrt64(max_t(s64, 0, (trace - discriminant) / 2) <<
				 G6TS_CLASSIFIER_SHIFT);
	major_axis = max_t(u32, 1U << G6TS_CLASSIFIER_SHIFT,
			   ((u64)major_axis * G6TS_AXIS_SCALE_Q12) >>
			   G6TS_CLASSIFIER_SHIFT);
	minor_axis = max_t(u32, 1U << G6TS_CLASSIFIER_SHIFT,
			   ((u64)minor_axis * G6TS_AXIS_SCALE_Q12) >>
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
			-9999LL * (1LL << G6TS_WINDOWS_SCORE_SHIFT);
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
				    G6TS_WINDOWS_RUNTIME_OFFSET_Q24;

			contact->scores_q24[class] = score;

			if (score > best_score) {
				best_score = score;
				best_class = class;
			}
		}
	}
	return best_class;
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
		unsigned int head = 0, tail = 0;

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

		if (contact.pixels < G6TS_HEAT_MIN_PIXELS) {
			if (contact.peak_value > G6TS_HEAT_STRONG_MAX)
				continue;
		}
		if (ts->nsr_valid) {
			unsigned int sensor_row = div_u64(contact.weighted_y +
							     contact.strength / 2,
							     contact.strength);

			if (sensor_row < ARRAY_SIZE(g6ts_nsr_row_to_bin)) {
				u8 bin = g6ts_nsr_row_to_bin[sensor_row];

				if (bin < ts->nsr_bin_count &&
				    ts->nsr_bins[bin] > G6TS_NSR_CUTOFF)
					continue;
			}
		}
		if (contact.pixels > G6TS_HEAT_PALM_PIXELS ||
		    contact.max_col - contact.min_col + 1 > G6TS_HEAT_PALM_SPAN ||
		    contact.max_row - contact.min_row + 1 > G6TS_HEAT_PALM_SPAN)
			continue;
		contact.x = div_u64(contact.weighted_x * G6TS_LOGICAL_MAX,
				    (u64)contact.strength * (G6TS_HEAT_COLS - 1));
		contact.y = div_u64(contact.weighted_y * G6TS_LOGICAL_MAX,
				    (u64)contact.strength * (G6TS_HEAT_ROWS - 1));
		contact.sensor_x_q24 = div_u64(contact.weighted_x << 24,
					       contact.strength);
		contact.sensor_y_q24 = div_u64(contact.weighted_y << 24,
					       contact.strength);
		memset(ts->heat_component, 0, sizeof(ts->heat_component));
		while (tail)
			ts->heat_component[ts->heat_queue[--tail]] = 1;
		contact.features_q12[0] =
			contact.pixels << G6TS_CLASSIFIER_SHIFT;
		g6ts_secondary_features(ts, &contact);
		g6ts_geometry_features(ts, &contact);
		contact.features_q12[9] = g6ts_halo_feature(ts, &contact);
		contact.shape_class = g6ts_classify_contact(&contact);
		/* FUN_180049458 permits the classifier's classes zero and two. */
		contact.shape_allowed = contact.shape_class == 0 ||
					contact.shape_class == 2;
		dev_dbg(&ts->spi->dev,
			"candidate class=%u allowed=%u pixels=%u halo_q12=%d\n",
			contact.shape_class, contact.shape_allowed, contact.pixels,
			contact.features_q12[9]);
		memset(ts->heat_component, 0, sizeof(ts->heat_component));
		g6ts_store_contact(ts, &contact, &contact_count);
	}

	return contact_count;
}

static bool
g6ts_transition_current_passes(const struct g6ts_transition_rule *rule,
			       u8 candidate,
			       const s64 scores[G6TS_CLASS_COUNT])
{
	s64 selected = scores[candidate];
	unsigned int class;

	for (class = 0; class < G6TS_CLASS_COUNT; class++) {
		s64 margin;

		if (class == candidate)
			continue;
		margin = (s64)rule->current_margins[class] *
			 (1LL << G6TS_WINDOWS_SCORE_SHIFT);
		if (selected - scores[class] < margin)
			return false;
	}
	return selected >= (s64)rule->absolute_minimum *
			   (1LL << G6TS_WINDOWS_SCORE_SHIFT);
}

static bool
g6ts_transition_history_passes(const struct g6ts_track *track,
			       const struct g6ts_transition_rule *rule,
			       u8 candidate)
{
	unsigned int sample, class;

	if (rule->history_depth > G6TS_WINDOWS_HISTORY_CAPACITY ||
	    track->score_history_count < rule->history_depth)
		return false;
	for (sample = 0; sample < rule->history_depth; sample++) {
		s64 selected = track->score_history_q24[sample][candidate];

		for (class = 0; class < G6TS_CLASS_COUNT; class++) {
			s64 margin;

			if (class == candidate)
				continue;
			margin = (s64)rule->history_margins[class] *
				 (1LL << G6TS_WINDOWS_SCORE_SHIFT);
			if (selected - track->score_history_q24[sample][class] <
			    margin)
				return false;
		}
		if (selected < (s64)rule->absolute_minimum *
			       (1LL << G6TS_WINDOWS_SCORE_SHIFT))
			return false;
	}
	return true;
}

/*
 * Bounded ordinary-finger subset of FUN_180041150.  Context bias, the
 * candidate +0x4d/+0x4e score-three producer, and the later output override
 * remain outside this opt-in path until their live provider fields exist.
 */
static void g6ts_windows_update_class(struct g6ts_track *track,
				      const struct g6ts_contact *contact)
{
	const struct g6ts_transition_rule *rule;
	unsigned int sample, class;
	u8 candidate = 0;
	bool accepted = false;

	for (sample = min_t(unsigned int, track->score_history_count,
			    G6TS_WINDOWS_HISTORY_CAPACITY - 1);
	     sample > 0; sample--)
		memcpy(track->score_history_q24[sample],
		       track->score_history_q24[sample - 1],
		       sizeof(track->score_history_q24[sample]));
	memcpy(track->score_history_q24[0], contact->scores_q24,
	       sizeof(track->score_history_q24[0]));
	if (track->score_history_count < G6TS_WINDOWS_HISTORY_CAPACITY)
		track->score_history_count++;

	for (class = 1; class < G6TS_CLASS_COUNT; class++) {
		if (contact->scores_q24[candidate] < contact->scores_q24[class])
			candidate = class;
	}
	if (track->windows_class == candidate) {
		accepted = true;
	} else {
		rule = &g6ts_transition_rules[track->windows_class *
					      G6TS_CLASS_COUNT + candidate];
		if (track->age == 1 || track->age <= rule->initial_age_limit)
			accepted = g6ts_transition_current_passes(rule, candidate,
								  contact->scores_q24);
		if (!accepted && track->age > 1)
			accepted = g6ts_transition_history_passes(track, rule,
								  candidate);
		if (accepted &&
		    (contact->pixels < g6ts_class_point_minimums[candidate] ||
		     contact->pixels > g6ts_class_point_maximums[candidate]))
			accepted = false;
	}
	if (accepted)
		track->windows_class = candidate;
	track->confirmed = track->windows_class == 0 ||
			   track->windows_class == 2;
}

static u16 g6ts_windows_assignment_coordinate(u32 position_q24, u32 scale_q24)
{
	u64 scaled = (u64)position_q24 * scale_q24;

	return min_t(u64, (scaled + BIT_ULL(47)) >> 48, S16_MAX);
}

static u16 g6ts_filter_coordinate(u16 previous, u16 sample)
{
	unsigned int delta = previous > sample ? previous - sample :
						 sample - previous;

	/*
	 * TouchPenProcessor uses output = alpha * previous +
	 * (1 - alpha) * sample.  The project-tuning table selecting alpha is
	 * not recovered, so these two bands are explicit SP11 fits: suppress
	 * stationary sensor jitter, reduce lag for slow motion, and pass fast
	 * motion through unchanged.
	 */
	if (delta <= G6TS_SMOOTH_STATIONARY_MAX)
		return (3U * previous + sample + 2U) / 4U;
	if (delta <= G6TS_SMOOTH_SLOW_MAX)
		return (previous + 3U * sample + 2U) / 4U;
	return sample;
}

static unsigned int g6ts_track_distance(const struct g6ts_track *track,
					const struct g6ts_contact *contact)
{
	if (g6ts_windows_orchestrator) {
		const u32 x_scale = G6TS_WINDOWS_ASSIGN_X_SCALE_Q24;
		const u32 y_scale = G6TS_WINDOWS_ASSIGN_Y_SCALE_Q24;
		s64 predicted_x = clamp_t(s64,
			(s64)track->sensor_x_q24 + track->sensor_velocity_x_q24,
			0, (s64)(G6TS_HEAT_COLS - 1) << 24);
		s64 predicted_y = clamp_t(s64,
			(s64)track->sensor_y_q24 + track->sensor_velocity_y_q24,
			0, (s64)(G6TS_HEAT_ROWS - 1) << 24);
		s32 track_x = g6ts_windows_assignment_coordinate(predicted_x,
							      x_scale);
		s32 track_y = g6ts_windows_assignment_coordinate(predicted_y,
							      y_scale);
		s32 candidate_x = g6ts_windows_assignment_coordinate(contact->sensor_x_q24,
								  x_scale);
		s32 candidate_y = g6ts_windows_assignment_coordinate(contact->sensor_y_q24,
								  y_scale);
		s32 dx = track_x - candidate_x;
		s32 dy = track_y - candidate_y;
		u32 squared = dx * dx + dy * dy;

		if (squared >= G6TS_WINDOWS_ASSIGN_RADIUS *
			       G6TS_WINDOWS_ASSIGN_RADIUS)
			return G6TS_ASSIGN_INVALID_COST;
		return squared;
	}

	s32 predicted_x = clamp_t(s32, (s32)track->raw_x + track->velocity_x,
				    0, G6TS_LOGICAL_MAX);
	s32 predicted_y = clamp_t(s32, (s32)track->raw_y + track->velocity_y,
				    0, G6TS_LOGICAL_MAX);
	s32 dx = predicted_x - contact->x;
	s32 dy = predicted_y - contact->y;
	u64 squared = (s64)dx * dx + (s64)dy * dy;

	if (squared > (u64)G6TS_TRACK_MATCH_MAX * G6TS_TRACK_MATCH_MAX)
		return G6TS_ASSIGN_INVALID_COST;
	return int_sqrt64(squared);
}

static u8 g6ts_confirmation_requirement(const struct g6ts *ts,
					const struct g6ts_contact *contact)
{
	unsigned int i;
	u8 required = G6TS_TRACK_CONFIRM_NORMAL;

	/*
	 * TouchPenProcessor does not expose a blob immediately.  Its recovered
	 * lifecycle keeps a per-track class history and uses transition-specific
	 * evidence windows.  The proprietary four-class score coefficients are
	 * intentionally not copied here; use observable component quality to
	 * select the same short, medium, and long lifecycle windows instead.
	 */
	if (contact->pixels < G6TS_HEAT_MIN_PIXELS)
		required = G6TS_TRACK_CONFIRM_WEAK;
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
		    work->cost[row][col] < G6TS_ASSIGN_INVALID_COST &&
		    (g6ts_windows_orchestrator ||
		     work->cost[row][col] <= G6TS_TRACK_MATCH_MAX))
			contact_slots[col] = work->active_slots[row];
	}
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
	if (g6ts_windows_orchestrator) {
		/* FUN_18004a330 stores X/Y directly; its alpha blends another scalar. */
		track->output_x = contact->x;
		track->output_y = contact->y;
	} else {
		track->output_x = g6ts_filter_coordinate(track->output_x,
							 contact->x);
		track->output_y = g6ts_filter_coordinate(track->output_y,
							 contact->y);
	}
	track->strength = contact->strength;
	track->pixels = contact->pixels;
	track->shape_class = contact->shape_class;
	if (track->age < U16_MAX)
		track->age++;
	if (g6ts_windows_orchestrator) {
		g6ts_windows_update_class(track, contact);
	} else if (!track->confirmed && contact->shape_allowed &&
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
		track->output_x = contact->x;
		track->output_y = contact->y;
		track->sensor_x_q24 = contact->sensor_x_q24;
		track->sensor_y_q24 = contact->sensor_y_q24;
		track->strength = contact->strength;
		track->pixels = contact->pixels;
		track->shape_class = contact->shape_class;
		track->age = 1;
		if (g6ts_windows_orchestrator) {
			track->windows_class = G6TS_WINDOWS_UNCLASSIFIED;
			g6ts_windows_update_class(track, contact);
		} else {
			track->evidence = contact->shape_allowed ? 1 : 0;
			track->required_evidence =
				g6ts_confirmation_requirement(ts, contact);
			track->confirmed = track->required_evidence <= 1;
		}
		track->active = true;
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
	unsigned int i;

	for (i = 0; i < G6TS_MAX_CONTACTS; i++) {
		struct g6ts_track *track = &ts->tracks[i];

		/* Retained tracks remain assignable but never become ghost contacts. */
		if (!track->active || !track->confirmed ||
		    !(current_slots & BIT(i)))
			continue;
		input_mt_slot(ts->input, i);
		input_mt_report_slot_state(ts->input, MT_TOOL_FINGER, true);
		touchscreen_report_pos(ts->input, &ts->prop, track->output_x,
				       track->output_y, true);
	}
	input_mt_sync_frame(ts->input);
	input_sync(ts->input);
}

static int g6ts_report_heat_contacts(struct g6ts *ts, const u8 *content,
				     size_t content_len)
{
	unsigned long current_slots = 0;
	int contact_slots[G6TS_MAX_CONTACTS];
	unsigned int count, i;
	int ret;

	ret = g6ts_extract_heatmap(ts, content, content_len);
	if (ret)
		return ret;
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

	if (ts->last_content_id == G6TS_HEATMAP_REPORT_ID &&
	    ts->last_content_len + 1 <= G6TS_MAX_BODY) {
		int ret;

		ret = g6ts_report_heat_contacts(ts, payload, ts->last_content_len);
		if (ret) {
			g6ts_release_contacts(ts);
			dev_warn_ratelimited(&ts->spi->dev,
					     "malformed Heat frame: %d\n", ret);
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
	    ts->last_header[3] != G6TS_HEADER_SYNC)
		return -EPROTO;

	words = get_unaligned_le16(&ts->last_header[1]) & 0x3fff;
	body_len = (size_t)words * 4;
	if (body_len < HIDSPI_INPUT_BODY_HEADER_SIZE ||
	    body_len > G6TS_MAX_BODY)
		return -EMSGSIZE;

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
	g6ts_handle_data_report(ts);
	return 0;
}

static irqreturn_t g6ts_interrupt_thread(int irq, void *data)
{
	struct g6ts *ts = data;
	unsigned int i;
	int ret;

	if (!READ_ONCE(ts->mode_enabled))
		return IRQ_HANDLED;

	mutex_lock(&ts->io_lock);
	for (i = 0; i < G6TS_FEATURE_RESPONSE_LIMIT; i++) {
		if (!g6ts_has_unread_response(ts))
			break;
		ret = g6ts_dma_read_response(ts);
		if (ret)
			break;
		if (ts->last_class == RESET_RESPONSE) {
			unsigned long now = jiffies;
			unsigned long interval_ms = 0;

			if (ts->last_reset_jiffies)
				interval_ms = jiffies_to_msecs(now -
							       ts->last_reset_jiffies);
			ts->last_reset_jiffies = now;
			ts->reset_notifications++;
			ts->mode_enabled = false;
			g6ts_release_contacts(ts);
			dev_warn(&ts->spi->dev,
				 "panel reset notification #%llu interval=%lums\n",
				 ts->reset_notifications, interval_ms);
			if (!READ_ONCE(ts->stopping))
				schedule_delayed_work(&ts->recovery_work,
						      msecs_to_jiffies(G6TS_RECOVERY_DELAY_MS));
			break;
		}
	}
	mutex_unlock(&ts->io_lock);
	return IRQ_HANDLED;
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
		if (response_class == DATA &&
		    ts->last_class == RESET_RESPONSE)
			return -EPIPE;

		/* A reset or stale input can precede the solicited reply. */
		if (ts->last_class == RESET_RESPONSE || ts->last_class == DATA ||
		    (ts->last_class == OUTPUT_REPORT_RESPONSE &&
		     ts->last_content_id == 0x09))
			continue;

		return -EPROTO;
	}

	return -EOVERFLOW;
}

/*
 * A class-3 notification terminates the panel's heat session.  Merely
 * replaying the feature reports is not sufficient: the panel waits for a
 * fresh host enumeration.  Reproduce the known-good cold path after a full
 * ACPI/GPIO power cycle, then restore heat mode.
 */
static int g6ts_full_reinitialize_locked(struct g6ts *ts)
{
	int ret;

	ts->mode_enabled = false;
	ts->expected_report_descriptor_len = 0;
	ts->initialization_stage = 0;

	ret = g6ts_power_off(ts);
	if (ret)
		return ret;
	msleep(100);
	ret = g6ts_power_on(ts);
	if (ret)
		return ret;

	ts->initialization_stage = 1;
	ret = g6ts_wait_pending(ts, 1000);
	if (ret)
		goto out;
	ret = g6ts_dma_read_response(ts);
	if (ret)
		goto out;
	ret = g6ts_expect_response(ts, RESET_RESPONSE, 0, 0);
	if (ret)
		goto out;

	ts->initialization_stage = 2;
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
	if (!ts->expected_report_descriptor_len ||
	    ts->expected_report_descriptor_len >
		    G6TS_MAX_BODY - HIDSPI_INPUT_BODY_HEADER_SIZE) {
		ret = -EPROTO;
		goto out;
	}

	ts->initialization_stage = 3;
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

	/*
	 * Enter the panel's streaming personality with the smallest sequence
	 * proven by the Phase 55 through Phase 65 cold boots and reset recoveries.
	 * Reports 0x60, 0x65, 0x06, 0x09, and 0x73 in the Windows ETW capture
	 * belong to collection/application setup. Replaying them here prevented
	 * Heat from starting in both the Phase 66 and Phase 67 hardware trials.
	 */
	ts->initialization_stage = 4;
	ret = g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x05,
					g6ts_mode_enable,
					sizeof(g6ts_mode_enable));
	if (ret)
		goto out;
	ret = g6ts_expect_response(ts, SET_FEATURE_RESPONSE, 0x05, 0);
	if (ret)
		goto out;

	ts->initialization_stage = 5;
	ret = g6ts_dma_feature_exchange(ts, GET_FEATURE, 0x70, NULL, 0);
	if (ret)
		goto out;
	ret = g6ts_expect_response(ts, GET_FEATURE_RESPONSE, 0x70, 1);
	if (ret)
		goto out;

	ts->initialization_stage = 6;
	ret = g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x70,
					g6ts_mode_enable,
					sizeof(g6ts_mode_enable));
	if (ret)
		goto out;
	ret = g6ts_expect_response(ts, SET_FEATURE_RESPONSE, 0x70, 0);
	if (ret)
		goto out;

	ts->initialization_stage = 7;
	ret = g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x56,
					g6ts_mode_handshake,
					sizeof(g6ts_mode_handshake));
	if (ret)
		goto out;
	ret = g6ts_expect_response(ts, SET_FEATURE_RESPONSE, 0x56, 0);
	if (ret)
		goto out;

	ts->mode_enabled = true;
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
			 "touch controller initialization failed stage=%u ret=%d failures=%llu%s\n",
			 ts->initialization_stage, ret, ts->recovery_failures,
			 retry ? "; retrying" : "");
	}
	mutex_unlock(&ts->io_lock);

	if (retry && !READ_ONCE(ts->stopping))
		schedule_delayed_work(&ts->recovery_work,
				      msecs_to_jiffies(G6TS_RECOVERY_RETRY_MS));
}

static int g6ts_probe(struct spi_device *spi)
{
	struct g6ts *ts;
	int ret;

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
	spi->max_speed_hz = G6TS_SPI_HZ;
	spi->bits_per_word = 8;
	spi->mode = SPI_MODE_0 | SPI_TX_QUAD | SPI_RX_QUAD;
	ret = spi_setup(spi);
	if (ret)
		return dev_err_probe(&spi->dev, ret, "spi_setup failed\n");

	ts->input = devm_input_allocate_device(&spi->dev);
	if (!ts->input)
		return -ENOMEM;
	ts->input->name = "Microsoft Surface G6 Touch (DMA)";
	ts->input->id.bustype = BUS_SPI;
	ts->input->dev.parent = &spi->dev;
	input_set_abs_params(ts->input, ABS_MT_POSITION_X, 0,
			     G6TS_LOGICAL_MAX, 0, 0);
	input_set_abs_params(ts->input, ABS_MT_POSITION_Y, 0,
			     G6TS_LOGICAL_MAX, 0, 0);
	touchscreen_parse_properties(ts->input, true, &ts->prop);
	ret = input_mt_init_slots(ts->input, G6TS_MAX_CONTACTS,
				  INPUT_MT_DIRECT | INPUT_MT_DROP_UNUSED |
				  INPUT_MT_TRACK);
	if (ret)
		return dev_err_probe(&spi->dev, ret,
				     "failed to initialize DMA touch slots\n");
	ret = input_register_device(ts->input);
	if (ret)
		return dev_err_probe(&spi->dev, ret,
				     "failed to register DMA touch input\n");

	ret = g6ts_power_on(ts);
	if (ret)
		return ret;

	g6ts_clear_last_response(ts);
	schedule_delayed_work(&ts->recovery_work,
			      msecs_to_jiffies(G6TS_RECOVERY_DELAY_MS));
	dev_info(&spi->dev, "touch controller initialization scheduled\n");
	return 0;
}

static void g6ts_remove(struct spi_device *spi)
{
	struct g6ts *ts = spi_get_drvdata(spi);

	WRITE_ONCE(ts->stopping, true);
	WRITE_ONCE(ts->mode_enabled, false);
	cancel_delayed_work_sync(&ts->recovery_work);
	mutex_lock(&ts->io_lock);
	g6ts_release_contacts(ts);
	mutex_unlock(&ts->io_lock);
	(void)g6ts_power_off(ts);
}

static int g6ts_suspend(struct device *dev)
{
	struct g6ts *ts = dev_get_drvdata(dev);
	int ret;

	WRITE_ONCE(ts->mode_enabled, false);
	disable_irq(ts->interrupt_irq);
	cancel_delayed_work_sync(&ts->recovery_work);

	mutex_lock(&ts->io_lock);
	g6ts_release_contacts(ts);
	ret = g6ts_power_off(ts);
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
	int ret;

	mutex_lock(&ts->io_lock);
	ts->fatal_transport_error = false;
	ts->recovery_fail_streak = 0;
	ret = g6ts_power_on(ts);
	mutex_unlock(&ts->io_lock);
	if (ret)
		return ret;

	enable_irq(ts->interrupt_irq);
	schedule_delayed_work(&ts->recovery_work,
			      msecs_to_jiffies(G6TS_RECOVERY_DELAY_MS));
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
	{ .compatible = "microsoft,mshw0485-biosref" },
	{ }
};
MODULE_DEVICE_TABLE(of, g6ts_of_match);

static const struct spi_device_id g6ts_spi_id[] = {
	{ "mshw0485" },
	{ "mshw0485-biosref" },
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

MODULE_DESCRIPTION("Microsoft Surface G6 touchscreen driver");
MODULE_AUTHOR("SP11 reverse-engineering project");
MODULE_LICENSE("GPL");
