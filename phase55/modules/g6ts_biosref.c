// SPDX-License-Identifier: GPL-2.0
/*
 * Microsoft Surface G6 Touch (MSHW0485), SP11 DMA multi-touch driver.
 *
 * This finger-only 7.1.1 variant intentionally never executes the UEFI/PRE-OS
 * FIFO protocol. Probe powers and resets the panel, then schedules the proven
 * GPI-DMA enumeration sequence. Class-3 panel resets use the same bounded
 * power-cycle and re-enumeration path. Suspend/resume callbacks are omitted
 * while platform suspend remains unsafe on the tested system.
 */

#include <linux/acpi.h>
#include <linux/delay.h>
#include <linux/fs.h>
#include <linux/gpio/consumer.h>
#include <linux/hid-over-spi.h>
#include <linux/input.h>
#include <linux/input/mt.h>
#include <linux/interrupt.h>
#include <linux/jiffies.h>
#include <linux/kernel.h>
#include <linux/math.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/spi/spi.h>
#include <linux/unaligned.h>
#include <linux/workqueue.h>

#define G6TS_NAME			"g6ts-dma"
#define G6TS_SPI_HZ			40000000U
#define G6TS_MAX_BODY			8192U
#define G6TS_DIAG_BODY			128U
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
#define G6TS_SMOOTH_STATIONARY_MAX	64U
#define G6TS_SMOOTH_SLOW_MAX		256U
#define G6TS_ASSIGN_MAX			(G6TS_MAX_CONTACTS * 2U)
#define G6TS_ASSIGN_UNMATCHED_COST	1000000
#define G6TS_ASSIGN_INVALID_COST	3000000

static bool enable_lab_controls;
module_param_named(lab_controls, enable_lab_controls, bool, 0400);
MODULE_PARM_DESC(lab_controls,
		 "Expose unsafe manual DMA experiment controls (default: false)");

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
	u16 pixels;
	u16 x;
	u16 y;
	u8 peak_value;
	u8 min_col;
	u8 max_col;
	u8 min_row;
	u8 max_row;
};

struct g6ts_track {
	u16 raw_x;
	u16 raw_y;
	u16 output_x;
	u16 output_y;
	s16 velocity_x;
	s16 velocity_y;
	u16 age;
	u8 missed;
	bool active;
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
	struct mutex io_lock;
	struct gpio_desc *interrupt_gpio;
	struct gpio_desc *power_gpio;
	struct gpio_desc *reset_gpio;
	u8 *body;
	u8 *report_descriptor;
	u8 *captured_report;
	u8 heatmap[G6TS_HEAT_SAMPLES];
	u8 heat_seen[G6TS_HEAT_SAMPLES];
	u16 heat_queue[G6TS_HEAT_SAMPLES];
	u16 heat_histogram[256];
	u16 nsr_bins[G6TS_NSR_BINS];
	struct g6ts_contact contacts[G6TS_MAX_CONTACTS];
	struct g6ts_track tracks[G6TS_MAX_CONTACTS];
	struct g6ts_assignment_workspace assignment;
	struct delayed_work recovery_work;
	u8 last_header[HIDSPI_INPUT_HEADER_SIZE];
	u8 last_body[G6TS_DIAG_BODY];
	size_t last_body_len;
	size_t last_body_total_len;
	size_t report_descriptor_len;
	size_t captured_report_len;
	u8 last_class;
	u16 last_content_len;
	u16 expected_report_descriptor_len;
	u8 last_content_id;
	u8 mode_stage;
	u8 mode_value;
	int probe_pending;
	int pending_before;
	int pending_after;
	int last_ret;
	int last_header_ret;
	int last_body_ret;
	int last_output_ret;
	int interrupt_irq;
	atomic64_t interrupt_edges;
	s64 handled_interrupt_edges;
	u64 dma_pair_count;
	u64 dma_output_count;
	u64 response_count;
	u64 manual_read_runs;
	u64 descriptor_runs;
	u64 report_descriptor_runs;
	u64 mode_sequence_runs;
	u64 next_report_runs;
	u64 interleaved_data_count;
	u64 touch_report_count;
	u64 heatmap_report_count;
	u64 heatmap_decode_errors;
	u64 heatmap_contact_frames;
	u64 heatmap_idle_frames;
	u64 heatmap_palm_rejections;
	u64 heatmap_small_strong_contacts;
	u64 heatmap_weak_rejections;
	u64 heatmap_nsr_rejections;
	u64 heatmap_held_frames;
	u64 tracker_matches;
	u64 tracker_new_tracks;
	u64 tracker_releases;
	u64 tracker_dropped_contacts;
	u64 recovery_requests;
	u64 recovery_successes;
	u64 recovery_failures;
	u16 last_interleaved_len;
	u8 last_interleaved_id;
	u8 last_heat_baseline;
	u8 last_contact_count;
	u8 max_contact_pixels;
	u8 nsr_bin_count;
	u16 last_nsr_max;
	u8 recovery_fail_streak;
	bool heat_debug;
	bool nsr_valid;
	bool reset_seen;
	bool descriptor_seen;
	bool report_descriptor_seen;
	bool post_mode_reset_seen;
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

	return g6ts_acpi_method(&ts->spi->dev, "_RST");
}

static void g6ts_power_off(struct g6ts *ts)
{
	if (ts->power_gpio && ts->reset_gpio) {
		gpiod_set_value_cansleep(ts->reset_gpio, 0);
		usleep_range(10000, 12000);
		gpiod_set_value_cansleep(ts->power_gpio, 0);
		return;
	}

	g6ts_acpi_method(&ts->spi->dev, "_PS3");
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
	ts->dma_pair_count++;
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
	ts->dma_output_count++;
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
	memset(ts->last_header, 0xa5, sizeof(ts->last_header));
	memset(ts->last_body, 0, sizeof(ts->last_body));
	memset(ts->body, 0, G6TS_MAX_BODY);
	ts->last_body_len = 0;
	ts->last_body_total_len = 0;
	ts->last_class = 0xff;
	ts->last_content_len = 0;
	ts->last_content_id = 0xff;
	ts->pending_before = -1;
	ts->pending_after = -1;
	ts->last_header_ret = -EINPROGRESS;
	ts->last_body_ret = -EINPROGRESS;
	ts->last_ret = -EINPROGRESS;
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
			ts->last_nsr_max = 0;
			for (i = 0; i < count; i++) {
				u16 value = get_unaligned_le16(record + 8 + i * 4);

				ts->nsr_bins[i] = value;
				ts->last_nsr_max = max(ts->last_nsr_max, value);
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
	ts->last_nsr_max = 0;

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

static unsigned int g6ts_find_contacts(struct g6ts *ts)
{
	unsigned int baseline_count = 0;
	unsigned int contact_count = 0;
	unsigned int baseline = 0;
	unsigned int start;

	memset(ts->heat_histogram, 0, sizeof(ts->heat_histogram));
	memset(ts->heat_seen, 0, sizeof(ts->heat_seen));
	for (start = 0; start < G6TS_HEAT_SAMPLES; start++)
		ts->heat_histogram[ts->heatmap[start]]++;
	for (start = 0; start < ARRAY_SIZE(ts->heat_histogram); start++) {
		if (ts->heat_histogram[start] > baseline_count) {
			baseline = start;
			baseline_count = ts->heat_histogram[start];
		}
	}
	ts->last_heat_baseline = baseline;

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

		ts->max_contact_pixels = max_t(unsigned int,
					       ts->max_contact_pixels,
					       min_t(unsigned int, contact.pixels,
						     U8_MAX));
		if (contact.pixels < G6TS_HEAT_MIN_PIXELS) {
			if (contact.peak_value > G6TS_HEAT_STRONG_MAX) {
				ts->heatmap_weak_rejections++;
				continue;
			}
			ts->heatmap_small_strong_contacts++;
		}
		if (ts->nsr_valid) {
			unsigned int sensor_row = div_u64(contact.weighted_y +
							     contact.strength / 2,
							     contact.strength);

			if (sensor_row < ARRAY_SIZE(g6ts_nsr_row_to_bin)) {
				u8 bin = g6ts_nsr_row_to_bin[sensor_row];

				if (bin < ts->nsr_bin_count &&
				    ts->nsr_bins[bin] > G6TS_NSR_CUTOFF) {
					ts->heatmap_nsr_rejections++;
					continue;
				}
			}
		}
		if (contact.pixels > G6TS_HEAT_PALM_PIXELS ||
		    contact.max_col - contact.min_col + 1 > G6TS_HEAT_PALM_SPAN ||
		    contact.max_row - contact.min_row + 1 > G6TS_HEAT_PALM_SPAN) {
			ts->heatmap_palm_rejections++;
			continue;
		}
		contact.x = div_u64(contact.weighted_x * G6TS_LOGICAL_MAX,
				    (u64)contact.strength * (G6TS_HEAT_COLS - 1));
		contact.y = div_u64(contact.weighted_y * G6TS_LOGICAL_MAX,
				    (u64)contact.strength * (G6TS_HEAT_ROWS - 1));
		if (ts->heat_debug)
			dev_info(&ts->spi->dev,
				 "blob: col=%u..%u row=%u..%u px=%u peak=%u str=%u -> x=%u y=%u\n",
				 contact.min_col, contact.max_col,
				 contact.min_row, contact.max_row,
				 contact.pixels, contact.peak_value,
				 contact.strength,
				 contact.x, contact.y);
		g6ts_store_contact(ts, &contact, &contact_count);
	}

	return contact_count;
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

	for (i = 0; i < G6TS_MAX_CONTACTS; i++) {
		contact_slots[i] = -1;
		if (ts->tracks[i].active)
			work->active_slots[active_count++] = i;
	}
	if (!active_count || !count)
		return;

	n = active_count + count;
	for (row = 0; row < n; row++) {
		for (col = 0; col < n; col++) {
			if (row < active_count && col < count)
				work->cost[row][col] = g6ts_track_distance(
					&ts->tracks[work->active_slots[row]],
					&ts->contacts[col]);
			else if (row < active_count || col < count)
				work->cost[row][col] = G6TS_ASSIGN_UNMATCHED_COST;
			else
				work->cost[row][col] = 0;
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
		    work->cost[row][col] <= G6TS_TRACK_MATCH_MAX)
			contact_slots[col] = work->active_slots[row];
	}
}

static void g6ts_update_track(struct g6ts_track *track,
			      const struct g6ts_contact *contact)
{
	u16 old_x = track->raw_x;
	u16 old_y = track->raw_y;

	track->raw_x = contact->x;
	track->raw_y = contact->y;
	track->velocity_x = (s32)contact->x - old_x;
	track->velocity_y = (s32)contact->y - old_y;
	track->output_x = g6ts_filter_coordinate(track->output_x, contact->x);
	track->output_y = g6ts_filter_coordinate(track->output_y, contact->y);
	if (track->age < U16_MAX)
		track->age++;
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
		track->age = 1;
		track->active = true;
		ts->tracker_new_tracks++;
		return slot;
	}
	return -ENOSPC;
}

static int g6ts_report_heat_contacts(struct g6ts *ts, const u8 *content,
				      size_t content_len)
{
	unsigned long current_slots = 0;
	int contact_slots[G6TS_MAX_CONTACTS];
	unsigned int count, i;
	bool held = false;
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
		ts->tracker_matches++;
		current_slots |= BIT(slot);
	}
	/* Age unmatched old tracks before allocating unmatched new blobs. */
	for (i = 0; i < G6TS_MAX_CONTACTS; i++) {
		struct g6ts_track *track = &ts->tracks[i];

		if (!track->active || (current_slots & BIT(i)))
			continue;
		if (track->missed < G6TS_CONTACT_HOLD_FRAMES) {
			track->missed++;
			track->velocity_x /= 2;
			track->velocity_y /= 2;
			held = true;
		} else {
			memset(track, 0, sizeof(*track));
			ts->tracker_releases++;
		}
	}
	for (i = 0; i < count; i++) {
		int slot;

		if (contact_slots[i] >= 0)
			continue;
		slot = g6ts_new_track(ts, &ts->contacts[i]);
		if (slot < 0) {
			ts->tracker_dropped_contacts++;
			continue;
		}
		current_slots |= BIT(slot);
	}
	for (i = 0; i < G6TS_MAX_CONTACTS; i++) {
		struct g6ts_track *track = &ts->tracks[i];

		if (!track->active)
			continue;
		input_mt_slot(ts->input, i);
		input_mt_report_slot_state(ts->input, MT_TOOL_FINGER, true);
		input_report_abs(ts->input, ABS_MT_POSITION_X, track->output_x);
		input_report_abs(ts->input, ABS_MT_POSITION_Y, track->output_y);
	}
	input_mt_sync_frame(ts->input);
	input_sync(ts->input);
	if (held)
		ts->heatmap_held_frames++;
	ts->last_contact_count = count;
	if (count)
		ts->heatmap_contact_frames++;
	else
		ts->heatmap_idle_frames++;

	return 0;
}

static void g6ts_release_contacts(struct g6ts *ts)
{
	input_mt_sync_frame(ts->input);
	input_sync(ts->input);
	memset(ts->tracks, 0, sizeof(ts->tracks));
	ts->last_contact_count = 0;
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
		if (active) {
			input_report_abs(ts->input, ABS_X, x);
			input_report_abs(ts->input, ABS_Y, y);
		}
		input_sync(ts->input);
		ts->touch_report_count++;
		return;
	}

	if (ts->last_content_id == G6TS_HEATMAP_REPORT_ID &&
	    ts->last_content_len + 1 <= G6TS_MAX_BODY) {
		int ret;

		ts->heatmap_report_count++;
		ret = g6ts_report_heat_contacts(ts, payload, ts->last_content_len);
		if (ret) {
			ts->heatmap_decode_errors++;
			g6ts_release_contacts(ts);
			dev_warn_ratelimited(&ts->spi->dev, "malformed Heat frame: %d\n", ret);
		}
		if (enable_lab_controls && !ts->captured_report_len) {
			ts->captured_report[0] = ts->last_content_id;
			memcpy(&ts->captured_report[1], payload,
			       ts->last_content_len);
			ts->captured_report_len = ts->last_content_len + 1;
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
	int ret;

	g6ts_clear_last_response(ts);
	ts->pending_before = g6ts_pending(ts);
	interrupt_edges = atomic64_read(&ts->interrupt_edges);
	if (ts->pending_before <= 0 &&
	    interrupt_edges <= ts->handled_interrupt_edges) {
		ret = ts->pending_before < 0 ? ts->pending_before : -EAGAIN;
		goto out;
	}
	ts->handled_interrupt_edges = interrupt_edges;

	ret = g6ts_dma_read_pair(ts, g6ts_header_cmd, ts->last_header,
				 sizeof(ts->last_header));
	ts->last_header_ret = ret;
	if (ret) {
		ts->fatal_transport_error = true;
		goto out;
	}

	if ((ts->last_header[0] & 0x0f) != G6TS_HEADER_VERSION ||
	    ts->last_header[3] != G6TS_HEADER_SYNC) {
		ret = -EPROTO;
		goto out;
	}

	words = get_unaligned_le16(&ts->last_header[1]) & 0x3fff;
	body_len = (size_t)words * 4;
	if (body_len < HIDSPI_INPUT_BODY_HEADER_SIZE ||
	    body_len > G6TS_MAX_BODY) {
		ret = -EMSGSIZE;
		goto out;
	}

	ret = g6ts_dma_read_pair(ts, g6ts_body_cmd, ts->body, body_len);
	ts->last_body_ret = ret;
	if (ret) {
		ts->fatal_transport_error = true;
		goto out;
	}

	ts->last_body_total_len = body_len;
	ts->last_body_len = min_t(size_t, body_len, sizeof(ts->last_body));
	memcpy(ts->last_body, ts->body, ts->last_body_len);
	ts->last_class = ts->body[0];
	ts->last_content_len = get_unaligned_le16(&ts->body[1]);
	ts->last_content_id = ts->body[3];
	if (ts->last_content_len > body_len - HIDSPI_INPUT_BODY_HEADER_SIZE) {
		ret = -EPROTO;
		goto out;
	}
	ts->response_count++;

	if (ts->last_class == RESET_RESPONSE)
		ts->reset_seen = true;
	if (ts->last_class == DEVICE_DESCRIPTOR_RESPONSE &&
	    ts->last_content_len == HIDSPI_DEVICE_DESCRIPTOR_SIZE) {
		descriptor = (const struct hidspi_dev_descriptor *)
			     (ts->body + HIDSPI_INPUT_BODY_HEADER_SIZE);
		ts->expected_report_descriptor_len =
			le16_to_cpu(descriptor->rep_desc_len);
		ts->descriptor_seen = true;
	}
	if (ts->last_class == REPORT_DESCRIPTOR_RESPONSE &&
	    ts->last_content_len <= G6TS_MAX_BODY) {
		memcpy(ts->report_descriptor,
		       ts->body + HIDSPI_INPUT_BODY_HEADER_SIZE,
		       ts->last_content_len);
		ts->report_descriptor_len = ts->last_content_len;
		ts->report_descriptor_seen = true;
	}
	g6ts_handle_data_report(ts);
	ret = 0;
out:
	ts->pending_after = g6ts_pending(ts);
	ts->last_ret = ret;
	return ret;
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
			ts->post_mode_reset_seen = true;
			ts->mode_enabled = false;
			g6ts_release_contacts(ts);
			if (!READ_ONCE(ts->stopping)) {
				ts->recovery_requests++;
				schedule_delayed_work(&ts->recovery_work,
					msecs_to_jiffies(G6TS_RECOVERY_DELAY_MS));
			}
			break;
		}
	}
	mutex_unlock(&ts->io_lock);
	return IRQ_HANDLED;
}

static int g6ts_dma_feature_exchange(struct g6ts *ts, u8 report_type,
				     u8 content_id, const u8 *content,
				     size_t content_len, const char *stage)
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

	ts->last_output_ret = g6ts_dma_hidspi_output(ts, report_type,
						     content_id, content,
						     content_len);
	ret = ts->last_output_ret;
	if (ret) {
		ts->fatal_transport_error = true;
		ts->last_ret = ret;
		return ret;
	}

	for (response_index = 0;
	     response_index < G6TS_FEATURE_RESPONSE_LIMIT;
	     response_index++) {
		ret = g6ts_wait_pending(ts, 1000);
		if (ret) {
			ts->last_ret = ret;
			return ret;
		}

		ret = g6ts_dma_read_response(ts);
		dev_dbg(&ts->spi->dev,
			"G6TS DMA mode stage=%s response=%u ret=%d class=%u id=%#02x content_len=%u body=%*ph\n",
			stage, response_index, ret, ts->last_class,
			ts->last_content_id, ts->last_content_len,
			(int)ts->last_body_len, ts->last_body);
		if (ret)
			return ret;

		if (ts->last_class == expected_class &&
		    ts->last_content_id == content_id)
			return 0;

		/*
		 * Once report 05 enables streaming, DATA packets can precede a
		 * solicited feature response.  Windows tolerates that ordering.  Keep
		 * their identity in diagnostics and continue to the matching reply.
		 */
		if (ts->last_class == DATA) {
			ts->interleaved_data_count++;
			ts->last_interleaved_id = ts->last_content_id;
			ts->last_interleaved_len = ts->last_content_len;
			dev_dbg(&ts->spi->dev,
				"G6TS DMA mode stage=%s skipping interleaved DATA id=%#02x len=%u count=%llu\n",
				stage, ts->last_content_id, ts->last_content_len,
				ts->interleaved_data_count);
			continue;
		}
		if (ts->last_class == OUTPUT_REPORT_RESPONSE &&
		    ts->last_content_id == 0x09) {
			dev_dbg(&ts->spi->dev,
				"G6TS DMA mode stage=%s skipping report-09 output acknowledgment\n",
				stage);
			continue;
		}

		ts->last_ret = -EPROTO;
		return -EPROTO;
	}

	ts->last_ret = -EOVERFLOW;
	return -EOVERFLOW;
}

static ssize_t state_show(struct device *dev,
			  struct device_attribute *attr, char *buf)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(dev));
	int pending = g6ts_pending(ts);

	return sysfs_emit(buf,
		"mode=dma-multitouch initial_bus_io=automatic automatic_reset_recovery=1 lab_controls=%u current_pending=%d probe_pending=%d fatal_transport_error=%u interrupt_irq=%d interrupt_edges=%lld handled_edges=%lld\n"
		"manual_read_runs=%llu descriptor_runs=%llu report_descriptor_runs=%llu mode_sequence_runs=%llu next_report_runs=%llu dma_pairs=%llu dma_outputs=%llu responses=%llu reset_seen=%u descriptor_seen=%u report_descriptor_seen=%u\n"
		"expected_report_descriptor_len=%u report_descriptor_len=%zu\n"
		"mode_stage=%u mode_value=%#02x mode_enabled=%u post_mode_reset_seen=%u captured_report_len=%zu interleaved_data=%llu touch_reports=%llu heatmap_reports=%llu last_interleaved_id=%#02x last_interleaved_len=%u\n"
		"heat_decode_errors=%llu contact_frames=%llu idle_frames=%llu last_contacts=%u heat_baseline=%#02x active_max=%u strong_max=%u palm_rejections=%llu small_strong=%llu weak_rejections=%llu held_frames=%llu max_contact_pixels=%u\n"
		"nsr_valid=%u nsr_bins=%u nsr_max=%u nsr_cutoff=%u nsr_rejections=%llu\n"
		"tracker_match_gate=%u tracker_hold_frames=%u tracker_matches=%llu tracker_new=%llu tracker_releases=%llu tracker_dropped=%llu\n"
		"recovery_requests=%llu recovery_successes=%llu recovery_failures=%llu recovery_fail_streak=%u\n"
		"last_ret=%d header_ret=%d body_ret=%d output_ret=%d pending_before=%d pending_after=%d\n"
		"last_header=%*ph body_total_len=%zu class=%u content_len=%u content_id=%u last_body=%*ph\n",
		enable_lab_controls, pending, ts->probe_pending,
		ts->fatal_transport_error,
		ts->interrupt_irq, atomic64_read(&ts->interrupt_edges),
		ts->handled_interrupt_edges,
		ts->manual_read_runs, ts->descriptor_runs,
		ts->report_descriptor_runs, ts->mode_sequence_runs,
		ts->next_report_runs, ts->dma_pair_count,
		ts->dma_output_count, ts->response_count, ts->reset_seen,
		ts->descriptor_seen, ts->report_descriptor_seen,
		ts->expected_report_descriptor_len, ts->report_descriptor_len,
		ts->mode_stage, ts->mode_value, ts->mode_enabled,
		ts->post_mode_reset_seen, ts->captured_report_len,
		ts->interleaved_data_count,
		ts->touch_report_count, ts->heatmap_report_count,
		ts->last_interleaved_id, ts->last_interleaved_len,
		ts->heatmap_decode_errors, ts->heatmap_contact_frames,
		ts->heatmap_idle_frames, ts->last_contact_count,
		ts->last_heat_baseline, G6TS_HEAT_ACTIVE_MAX,
		G6TS_HEAT_STRONG_MAX, ts->heatmap_palm_rejections,
		ts->heatmap_small_strong_contacts,
		ts->heatmap_weak_rejections,
		ts->heatmap_held_frames, ts->max_contact_pixels,
		ts->nsr_valid, ts->nsr_bin_count, ts->last_nsr_max,
		G6TS_NSR_CUTOFF, ts->heatmap_nsr_rejections,
		G6TS_TRACK_MATCH_MAX, G6TS_CONTACT_HOLD_FRAMES,
		ts->tracker_matches, ts->tracker_new_tracks,
		ts->tracker_releases, ts->tracker_dropped_contacts,
		ts->recovery_requests, ts->recovery_successes,
		ts->recovery_failures, ts->recovery_fail_streak,
		ts->last_ret, ts->last_header_ret,
		ts->last_body_ret, ts->last_output_ret, ts->pending_before,
		ts->pending_after, (int)sizeof(ts->last_header), ts->last_header,
		ts->last_body_total_len, ts->last_class, ts->last_content_len,
		ts->last_content_id, (int)ts->last_body_len, ts->last_body);
}
static DEVICE_ATTR_RO(state);

static ssize_t heat_debug_store(struct device *dev,
				struct device_attribute *attr,
				const char *buf, size_t count)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(dev));
	bool v;
	int ret = kstrtobool(buf, &v);

	if (ret)
		return ret;
	ts->heat_debug = v;
	return count;
}
static DEVICE_ATTR_WO(heat_debug);

/* First clean-boot experiment: consume only the spontaneous reset response. */
static ssize_t dma_read_store(struct device *dev,
			      struct device_attribute *attr,
			      const char *buf, size_t count)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(dev));
	bool run;
	int ret;

	ret = kstrtobool(buf, &run);
	if (ret)
		return ret;
	if (!run)
		return -EINVAL;

	mutex_lock(&ts->io_lock);
	if (ts->manual_read_runs || ts->fatal_transport_error) {
		ts->last_ret = -EBUSY;
		goto out;
	}
	ts->manual_read_runs++;
	ret = g6ts_dma_read_response(ts);
	dev_dbg(&ts->spi->dev,
		"G6TS DMA reset-read ret=%d pending=%d/%d header=%*ph class=%u len=%zu body=%*ph\n",
		ret, ts->pending_before, ts->pending_after,
		(int)sizeof(ts->last_header), ts->last_header,
		ts->last_class, ts->last_body_total_len,
		(int)ts->last_body_len, ts->last_body);
out:
	mutex_unlock(&ts->io_lock);
	return count;
}
static DEVICE_ATTR_WO(dma_read);

/*
 * Second staged experiment. It is unavailable until a valid class-3 reset
 * response has been read, so it cannot blindly alter an unknown panel state.
 */
static ssize_t dma_device_descriptor_store(struct device *dev,
					   struct device_attribute *attr,
					   const char *buf, size_t count)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(dev));
	bool run;
	int ret;

	ret = kstrtobool(buf, &run);
	if (ret)
		return ret;
	if (!run)
		return -EINVAL;

	mutex_lock(&ts->io_lock);
	if (!ts->reset_seen || ts->descriptor_runs ||
	    ts->fatal_transport_error) {
		ts->last_ret = -EAGAIN;
		goto out;
	}

	ts->descriptor_runs++;
	ts->last_output_ret = g6ts_dma_output(ts,
					      g6ts_device_descriptor_cmd,
					      sizeof(g6ts_device_descriptor_cmd));
	ret = ts->last_output_ret;
	if (ret) {
		ts->fatal_transport_error = true;
		ts->last_ret = ret;
		goto log;
	}

	ret = g6ts_wait_pending(ts, 1000);
	if (ret) {
		ts->last_ret = ret;
		goto log;
	}
	ret = g6ts_dma_read_response(ts);
log:
	dev_dbg(&ts->spi->dev,
		"G6TS DMA device-descriptor ret=%d output=%d header=%*ph class=%u content_len=%u body=%*ph\n",
		ret, ts->last_output_ret, (int)sizeof(ts->last_header),
		ts->last_header, ts->last_class, ts->last_content_len,
		(int)ts->last_body_len, ts->last_body);
out:
	mutex_unlock(&ts->io_lock);
	return count;
}
static DEVICE_ATTR_WO(dma_device_descriptor);

/* Third staged experiment: retrieve the HID report map advertised above. */
static ssize_t dma_report_descriptor_store(struct device *dev,
					   struct device_attribute *attr,
					   const char *buf, size_t count)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(dev));
	bool run;
	int ret;

	ret = kstrtobool(buf, &run);
	if (ret)
		return ret;
	if (!run)
		return -EINVAL;

	mutex_lock(&ts->io_lock);
	if (!ts->descriptor_seen || ts->report_descriptor_runs ||
	    ts->fatal_transport_error) {
		ts->last_ret = -EAGAIN;
		goto out;
	}

	ts->report_descriptor_runs++;
	ts->last_output_ret = g6ts_dma_output(ts,
					      g6ts_report_descriptor_cmd,
					      sizeof(g6ts_report_descriptor_cmd));
	ret = ts->last_output_ret;
	if (ret) {
		ts->fatal_transport_error = true;
		ts->last_ret = ret;
		goto log;
	}

	ret = g6ts_wait_pending(ts, 1000);
	if (ret) {
		ts->last_ret = ret;
		goto log;
	}
	ret = g6ts_dma_read_response(ts);
	if (!ret && (!ts->report_descriptor_seen ||
		     ts->report_descriptor_len !=
		     ts->expected_report_descriptor_len)) {
		ret = -EPROTO;
		ts->last_ret = ret;
	}
log:
	dev_dbg(&ts->spi->dev,
		"G6TS DMA report-descriptor ret=%d output=%d class=%u content_len=%u expected=%u stored=%zu\n",
		ret, ts->last_output_ret, ts->last_class,
		ts->last_content_len, ts->expected_report_descriptor_len,
		ts->report_descriptor_len);
out:
	mutex_unlock(&ts->io_lock);
	return count;
}
static DEVICE_ATTR_WO(dma_report_descriptor);

static ssize_t report_descriptor_show(struct device *dev,
				      struct device_attribute *attr, char *buf)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(dev));
	ssize_t len = 0;
	size_t i;

	mutex_lock(&ts->io_lock);
	for (i = 0; i < ts->report_descriptor_len && len < PAGE_SIZE - 3; i++)
		len += sysfs_emit_at(buf, len, "%02x", ts->report_descriptor[i]);
	len += sysfs_emit_at(buf, len, "\n");
	mutex_unlock(&ts->io_lock);
	return len;
}
static DEVICE_ATTR_RO(report_descriptor);

static int g6ts_expect_response(struct g6ts *ts, u8 response_class,
				u8 content_id, size_t min_content_len)
{
	if (ts->last_class != response_class ||
	    ts->last_content_id != content_id ||
	    ts->last_content_len < min_content_len) {
		ts->last_ret = -EPROTO;
		return -EPROTO;
	}

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
		if (ret) {
			ts->last_ret = ret;
			return ret;
		}

		ret = g6ts_dma_read_response(ts);
		if (ret)
			return ret;
		if (ts->last_class == response_class &&
		    ts->last_content_id == content_id &&
		    ts->last_content_len >= min_content_len)
			return 0;

		/* A reset or stale input can precede the solicited reply. */
		if (ts->last_class == RESET_RESPONSE || ts->last_class == DATA ||
		    (ts->last_class == OUTPUT_REPORT_RESPONSE &&
		     ts->last_content_id == 0x09))
			continue;

		ts->last_ret = -EPROTO;
		return -EPROTO;
	}

	ts->last_ret = -EOVERFLOW;
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
	ts->post_mode_reset_seen = false;
	ts->reset_seen = false;
	ts->descriptor_seen = false;
	ts->report_descriptor_seen = false;
	ts->report_descriptor_len = 0;
	ts->expected_report_descriptor_len = 0;
	ts->mode_stage = 0;

	g6ts_power_off(ts);
	msleep(100);
	ret = g6ts_power_on(ts);
	if (ret)
		return ret;

	ret = g6ts_wait_pending(ts, 1000);
	if (ret)
		goto out;
	ret = g6ts_dma_read_response(ts);
	if (ret)
		goto out;
	ret = g6ts_expect_response(ts, RESET_RESPONSE, 0, 0);
	if (ret)
		goto out;

	ts->last_output_ret = g6ts_dma_output(ts,
					      g6ts_device_descriptor_cmd,
					      sizeof(g6ts_device_descriptor_cmd));
	ret = ts->last_output_ret;
	if (ret) {
		ts->fatal_transport_error = true;
		goto out;
	}
	ret = g6ts_recovery_read_expected(ts, DEVICE_DESCRIPTOR_RESPONSE, 0,
					  HIDSPI_DEVICE_DESCRIPTOR_SIZE);
	if (ret)
		goto out;

	ts->last_output_ret = g6ts_dma_output(ts,
					      g6ts_report_descriptor_cmd,
					      sizeof(g6ts_report_descriptor_cmd));
	ret = ts->last_output_ret;
	if (ret) {
		ts->fatal_transport_error = true;
		goto out;
	}
	ret = g6ts_recovery_read_expected(ts, REPORT_DESCRIPTOR_RESPONSE, 0,
					  ts->expected_report_descriptor_len);
	if (ret || ts->report_descriptor_len !=
		   ts->expected_report_descriptor_len) {
		if (!ret)
			ret = -EPROTO;
		goto out;
	}

	ts->mode_stage = 1;
	ret = g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x05,
					g6ts_mode_enable,
					sizeof(g6ts_mode_enable), "recover-set-05");
	if (ret)
		goto out;
	ret = g6ts_expect_response(ts, SET_FEATURE_RESPONSE, 0x05, 0);
	if (ret)
		goto out;

	ts->mode_stage = 2;
	ret = g6ts_dma_feature_exchange(ts, GET_FEATURE, 0x70, NULL, 0,
					"recover-get-70");
	if (ret)
		goto out;
	ret = g6ts_expect_response(ts, GET_FEATURE_RESPONSE, 0x70, 1);
	if (ret)
		goto out;
	ts->mode_value = ts->body[HIDSPI_INPUT_BODY_HEADER_SIZE];

	ts->mode_stage = 3;
	ret = g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x70,
					g6ts_mode_enable,
					sizeof(g6ts_mode_enable), "recover-set-70");
	if (ret)
		goto out;
	ret = g6ts_expect_response(ts, SET_FEATURE_RESPONSE, 0x70, 0);
	if (ret)
		goto out;

	ts->mode_stage = 4;
	ret = g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x56,
					g6ts_mode_handshake,
					sizeof(g6ts_mode_handshake),
					"recover-set-56");
	if (ret)
		goto out;
	ret = g6ts_expect_response(ts, SET_FEATURE_RESPONSE, 0x56, 0);
	if (ret)
		goto out;

	ts->mode_enabled = true;
	ts->last_ret = 0;
	return 0;

out:
	ts->mode_enabled = false;
	ts->last_ret = ret;
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
		ts->recovery_successes++;
		ts->recovery_fail_streak = 0;
	} else {
		ts->recovery_failures++;
		ts->recovery_fail_streak++;
		retry = !ts->fatal_transport_error &&
			ts->recovery_fail_streak < G6TS_RECOVERY_LIMIT;
	}
	dev_info(&ts->spi->dev,
		 "G6TS DMA recovery ret=%d success=%llu failures=%llu retry=%u\n",
		 ret, ts->recovery_successes, ts->recovery_failures, retry);
	mutex_unlock(&ts->io_lock);

	if (retry && !READ_ONCE(ts->stopping))
		schedule_delayed_work(&ts->recovery_work,
			msecs_to_jiffies(G6TS_RECOVERY_RETRY_MS));
}

static ssize_t dma_recover_store(struct device *dev,
				 struct device_attribute *attr,
				 const char *buf, size_t count)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(dev));
	bool run;
	int ret;

	ret = kstrtobool(buf, &run);
	if (ret)
		return ret;
	if (!run)
		return -EINVAL;
	if (READ_ONCE(ts->stopping))
		return -ESHUTDOWN;

	mutex_lock(&ts->io_lock);
	ts->recovery_requests++;
	mutex_unlock(&ts->io_lock);
	mod_delayed_work(system_wq, &ts->recovery_work, 0);
	return count;
}
static DEVICE_ATTR_WO(dma_recover);

static ssize_t dma_mode_sequence_store(struct device *dev,
				       struct device_attribute *attr,
				       const char *buf, size_t count)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(dev));
	bool run;
	int ret;

	ret = kstrtobool(buf, &run);
	if (ret)
		return ret;
	if (!run)
		return -EINVAL;

	mutex_lock(&ts->io_lock);
	if (!ts->report_descriptor_seen ||
	    ts->mode_sequence_runs >= G6TS_MODE_ATTEMPT_LIMIT ||
	    (ts->mode_sequence_runs && !ts->post_mode_reset_seen) ||
	    ts->fatal_transport_error) {
		ts->last_ret = -EAGAIN;
		goto out;
	}

	ts->mode_sequence_runs++;
	ts->mode_enabled = false;
	ts->post_mode_reset_seen = false;
	ts->mode_stage = 1;
	ret = g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x05,
					g6ts_mode_enable,
					sizeof(g6ts_mode_enable), "set-05");
	if (ret || g6ts_expect_response(ts, SET_FEATURE_RESPONSE, 0x05, 0))
		goto log;

	ts->mode_stage = 2;
	ret = g6ts_dma_feature_exchange(ts, GET_FEATURE, 0x70, NULL, 0,
					"get-70");
	if (ret || g6ts_expect_response(ts, GET_FEATURE_RESPONSE, 0x70, 1))
		goto log;
	ts->mode_value = ts->body[HIDSPI_INPUT_BODY_HEADER_SIZE];

	ts->mode_stage = 3;
	ret = g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x70,
					g6ts_mode_enable,
					sizeof(g6ts_mode_enable), "set-70");
	if (ret || g6ts_expect_response(ts, SET_FEATURE_RESPONSE, 0x70, 0))
		goto log;

	ts->mode_stage = 4;
	ret = g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x56,
					g6ts_mode_handshake,
					sizeof(g6ts_mode_handshake), "set-56");
	if (ret || g6ts_expect_response(ts, SET_FEATURE_RESPONSE, 0x56, 0))
		goto log;

	/*
	 * A RESET_RESPONSE or a short burst of vendor DATA can follow report 56,
	 * depending on panel state.  Neither is part of the synchronous feature
	 * acknowledgement, so leave it queued for the bounded capture loop.
	 */
	ts->mode_enabled = true;
	ts->last_ret = 0;
log:
	dev_dbg(&ts->spi->dev,
		"G6TS DMA mode-sequence stage=%u ret=%d prior_mode=%#02x enabled=%u fatal=%u\n",
		ts->mode_stage, ts->last_ret, ts->mode_value,
		ts->mode_enabled, ts->fatal_transport_error);
out:
	mutex_unlock(&ts->io_lock);
	return count;
}
static DEVICE_ATTR_WO(dma_mode_sequence);

static ssize_t dma_next_report_store(struct device *dev,
				     struct device_attribute *attr,
				     const char *buf, size_t count)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(dev));
	unsigned int response_index;
	bool run;
	int ret;

	ret = kstrtobool(buf, &run);
	if (ret)
		return ret;
	if (!run)
		return -EINVAL;

	mutex_lock(&ts->io_lock);
	if (!ts->mode_enabled ||
	    ts->next_report_runs >= G6TS_MODE_ATTEMPT_LIMIT ||
	    ts->captured_report_len ||
	    ts->fatal_transport_error || !g6ts_has_unread_response(ts)) {
		ts->last_ret = -EAGAIN;
		goto out;
	}

	ts->next_report_runs++;
	for (response_index = 0;
	     response_index < G6TS_FEATURE_RESPONSE_LIMIT;
	     response_index++) {
		ret = g6ts_wait_pending(ts, 1000);
		if (ret) {
			ts->last_ret = ret;
			break;
		}

		ret = g6ts_dma_read_response(ts);
		if (ret)
			break;
		if (ts->last_class == DATA &&
		    ts->last_content_id == G6TS_HEATMAP_REPORT_ID &&
		    ts->last_content_len + 1 <= G6TS_MAX_BODY) {
			ts->captured_report[0] = ts->last_content_id;
			memcpy(&ts->captured_report[1],
			       ts->body + HIDSPI_INPUT_BODY_HEADER_SIZE,
			       ts->last_content_len);
			ts->captured_report_len = ts->last_content_len + 1;
			ts->last_ret = 0;
			break;
		}
		if (ts->last_class == DATA) {
			ts->interleaved_data_count++;
			ts->last_interleaved_id = ts->last_content_id;
			ts->last_interleaved_len = ts->last_content_len;
			dev_dbg(&ts->spi->dev,
				"G6TS DMA capture skipping DATA id=%#02x len=%u count=%llu\n",
				ts->last_content_id, ts->last_content_len,
				ts->interleaved_data_count);
			continue;
		}
		if (ts->last_class == OUTPUT_REPORT_RESPONSE &&
		    ts->last_content_id == 0x09) {
			dev_dbg(&ts->spi->dev,
				"G6TS DMA capture skipping report-09 output acknowledgment\n");
			continue;
		}
		if (ts->last_class == RESET_RESPONSE) {
			ts->post_mode_reset_seen = true;
			ts->mode_enabled = false;
			dev_dbg(&ts->spi->dev,
				"G6TS DMA capture saw post-mode reset; mode sequence must be retried\n");
			ret = -EAGAIN;
			ts->last_ret = ret;
			break;
		}

		ret = -EPROTO;
		ts->last_ret = ret;
		break;
	}
	if (response_index == G6TS_FEATURE_RESPONSE_LIMIT) {
		ret = -EOVERFLOW;
		ts->last_ret = ret;
	}

	dev_dbg(&ts->spi->dev,
		"G6TS DMA next-report ret=%d class=%u id=%#02x content_len=%u captured=%zu\n",
		ret, ts->last_class, ts->last_content_id,
		ts->last_content_len, ts->captured_report_len);
out:
	mutex_unlock(&ts->io_lock);
	return count;
}
static DEVICE_ATTR_WO(dma_next_report);

static ssize_t captured_report_read(struct file *filp, struct kobject *kobj,
				    const struct bin_attribute *attr,
				    char *buf, loff_t off, size_t count)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(kobj_to_dev(kobj)));
	ssize_t ret;

	mutex_lock(&ts->io_lock);
	ret = memory_read_from_buffer(buf, count, &off, ts->captured_report,
				      ts->captured_report_len);
	mutex_unlock(&ts->io_lock);
	return ret;
}
static BIN_ATTR_RO(captured_report, G6TS_MAX_BODY);

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
	ts->report_descriptor = devm_kmalloc(&spi->dev, G6TS_MAX_BODY,
					      GFP_KERNEL);
	if (!ts->report_descriptor)
		return -ENOMEM;
	if (enable_lab_controls) {
		ts->captured_report = devm_kmalloc(&spi->dev, G6TS_MAX_BODY,
						   GFP_KERNEL);
		if (!ts->captured_report)
			return -ENOMEM;
	}

	ts->spi = spi;
	ts->interrupt_irq = -1;
	ts->interrupt_gpio = devm_gpiod_get(&spi->dev, "interrupt", GPIOD_IN);
	if (IS_ERR(ts->interrupt_gpio))
		return dev_err_probe(&spi->dev, PTR_ERR(ts->interrupt_gpio),
				     "failed to get GPIO51 pending input\n");
	ts->interrupt_irq = gpiod_to_irq(ts->interrupt_gpio);
	if (ts->interrupt_irq > 0) {
		ret = devm_request_threaded_irq(&spi->dev, ts->interrupt_irq,
					g6ts_interrupt_edge,
					g6ts_interrupt_thread,
					IRQF_TRIGGER_FALLING | IRQF_ONESHOT,
					G6TS_NAME, ts);
		if (ret) {
			dev_warn(&spi->dev,
				 "could not instrument GPIO51 edges: %d\n", ret);
			ts->interrupt_irq = -1;
		}
	}
	ts->power_gpio = devm_gpiod_get_optional(&spi->dev, "power",
						  GPIOD_OUT_LOW);
	if (IS_ERR(ts->power_gpio))
		return dev_err_probe(&spi->dev, PTR_ERR(ts->power_gpio),
				     "failed to get power GPIO\n");
	ts->reset_gpio = devm_gpiod_get_optional(&spi->dev, "reset",
						  GPIOD_OUT_LOW);
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

	/* Critical invariant: no SPI transfer of any kind occurs during probe. */
	ts->probe_pending = g6ts_pending(ts);
	g6ts_clear_last_response(ts);
	ts->last_output_ret = -EINPROGRESS;
	ts->mode_value = 0xff;
	ts->last_interleaved_id = 0xff;

	ret = device_create_file(&spi->dev, &dev_attr_state);
	if (ret)
		goto err_power;
	(void)device_create_file(&spi->dev, &dev_attr_heat_debug);
	if (!enable_lab_controls)
		goto start;
	ret = device_create_file(&spi->dev, &dev_attr_dma_read);
	if (ret)
		goto err_state;
	ret = device_create_file(&spi->dev, &dev_attr_dma_device_descriptor);
	if (ret)
		goto err_read;
	ret = device_create_file(&spi->dev, &dev_attr_dma_report_descriptor);
	if (ret)
		goto err_device_descriptor;
	ret = device_create_file(&spi->dev, &dev_attr_report_descriptor);
	if (ret)
		goto err_report_request;
	ret = device_create_file(&spi->dev, &dev_attr_dma_mode_sequence);
	if (ret)
		goto err_report_descriptor;
	ret = device_create_file(&spi->dev, &dev_attr_dma_recover);
	if (ret)
		goto err_mode_sequence;
	ret = device_create_file(&spi->dev, &dev_attr_dma_next_report);
	if (ret)
		goto err_recover;
	ret = device_create_bin_file(&spi->dev, &bin_attr_captured_report);
	if (ret)
		goto err_next_report;

start:
	ts->recovery_requests++;
	schedule_delayed_work(&ts->recovery_work,
		msecs_to_jiffies(G6TS_RECOVERY_DELAY_MS));
	dev_info(&spi->dev,
		 "DMA touch probe complete: pending=%d, automatic enumeration scheduled\n",
		 ts->probe_pending);
	return 0;

err_next_report:
	device_remove_file(&spi->dev, &dev_attr_dma_next_report);
err_recover:
	device_remove_file(&spi->dev, &dev_attr_dma_recover);
err_mode_sequence:
	device_remove_file(&spi->dev, &dev_attr_dma_mode_sequence);
err_report_descriptor:
	device_remove_file(&spi->dev, &dev_attr_report_descriptor);
err_report_request:
	device_remove_file(&spi->dev, &dev_attr_dma_report_descriptor);
err_device_descriptor:
	device_remove_file(&spi->dev, &dev_attr_dma_device_descriptor);
err_read:
	device_remove_file(&spi->dev, &dev_attr_dma_read);
err_state:
	device_remove_file(&spi->dev, &dev_attr_state);
err_power:
	g6ts_power_off(ts);
	return ret;
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
	if (enable_lab_controls) {
		device_remove_bin_file(&spi->dev, &bin_attr_captured_report);
		device_remove_file(&spi->dev, &dev_attr_dma_next_report);
		device_remove_file(&spi->dev, &dev_attr_dma_recover);
		device_remove_file(&spi->dev, &dev_attr_dma_mode_sequence);
		device_remove_file(&spi->dev, &dev_attr_report_descriptor);
		device_remove_file(&spi->dev, &dev_attr_dma_report_descriptor);
		device_remove_file(&spi->dev, &dev_attr_dma_device_descriptor);
		device_remove_file(&spi->dev, &dev_attr_dma_read);
	}
	device_remove_file(&spi->dev, &dev_attr_heat_debug);
	device_remove_file(&spi->dev, &dev_attr_state);
	g6ts_power_off(ts);
}

static const struct acpi_device_id g6ts_acpi_match[] = {
	{ "MSHW0485", 0 },
	{ }
};
MODULE_DEVICE_TABLE(acpi, g6ts_acpi_match);

static const struct of_device_id g6ts_of_match[] = {
	{ .compatible = "microsoft,mshw0485-biosref" },
	{ }
};
MODULE_DEVICE_TABLE(of, g6ts_of_match);

static const struct spi_device_id g6ts_spi_id[] = {
	{ "mshw0485-biosref" },
	{ }
};
MODULE_DEVICE_TABLE(spi, g6ts_spi_id);

static struct spi_driver g6ts_driver = {
	.driver = {
		.name = G6TS_NAME,
		.acpi_match_table = ACPI_PTR(g6ts_acpi_match),
		.of_match_table = g6ts_of_match,
	},
	.id_table = g6ts_spi_id,
	.probe = g6ts_probe,
	.remove = g6ts_remove,
};
module_spi_driver(g6ts_driver);

MODULE_DESCRIPTION("Surface G6 Touch DMA multi-touch driver");
MODULE_AUTHOR("SP11 reverse-engineering project");
MODULE_LICENSE("GPL");
