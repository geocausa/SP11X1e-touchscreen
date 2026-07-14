// SPDX-License-Identifier: GPL-2.0
/*
 * Microsoft Surface G6 Touch (MSHW0485), SP11 DMA laboratory driver.
 *
 * This disposable 7.1.1 variant intentionally never executes the UEFI/PRE-OS
 * FIFO protocol. Probe powers and resets the panel, then schedules the proven
 * GPI-DMA enumeration sequence. Class-3 panel resets use the same bounded
 * power-cycle and re-enumeration path.
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
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/pm.h>
#include <linux/slab.h>
#include <linux/spi/spi.h>
#include <linux/unaligned.h>
#include <linux/workqueue.h>

#define G6TS_NAME			"g6ts-dma-lab"
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
#define G6TS_HEAT_THRESHOLD		8U
#define G6TS_HEAT_MIN_PIXELS		2U
#define G6TS_MAX_CONTACTS		10U
#define G6TS_LOGICAL_MAX		32767U

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

/*
 * Two 63-byte report-09 payloads captured from the Windows HidWriteReport
 * path.  The deep ETL contains each complete 0x48-byte padded transaction,
 * confirming the final seven content bytes and pad byte are zero.  The ETL
 * profile uses 0x1a03; a later KD session uses the alternate 0x1403 profile.
 */
static const u8 g6ts_output09_a1[63] = {
	[0] = 0x8e, [1] = 0xa1, [2] = 0x01,
	[4] = 0x90, [5] = 0x01,
	[40] = 0x1a, [41] = 0x03,
};

static const u8 g6ts_output09_a5[63] = {
	[0] = 0x8e, [1] = 0xa5, [3] = 0x02,
	[39] = 0x1a, [40] = 0x03, [46] = 0x40,
};

struct g6ts_contact {
	u64 weighted_x;
	u64 weighted_y;
	u32 strength;
	u16 pixels;
	u16 x;
	u16 y;
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
	struct g6ts_contact contacts[G6TS_MAX_CONTACTS];
	struct input_mt_pos contact_positions[G6TS_MAX_CONTACTS];
	int contact_slots[G6TS_MAX_CONTACTS];
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
	u64 windows_output_runs;
	u64 next_report_runs;
	u64 interleaved_data_count;
	u64 touch_report_count;
	u64 heatmap_report_count;
	u64 heatmap_decode_errors;
	u64 heatmap_contact_frames;
	u64 heatmap_idle_frames;
	u64 recovery_requests;
	u64 recovery_successes;
	u64 recovery_failures;
	u16 last_interleaved_len;
	u8 last_interleaved_id;
	u8 last_heat_baseline;
	u8 last_contact_count;
	u8 recovery_fail_streak;
	bool reset_seen;
	bool descriptor_seen;
	bool report_descriptor_seen;
	bool post_mode_reset_seen;
	bool mode_enabled;
	bool fatal_transport_error;
	bool stopping;
	bool suspended;
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
		msleep(10);
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

	dev_info(&ts->spi->dev,
		 "DMA-LAB HIDSPI output type=%u id=%#02x content_len=%zu wire=%*ph\n",
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

static bool g6ts_heat_active(const struct g6ts *ts, unsigned int index,
			      u8 baseline)
{
	return ts->heatmap[index] <= baseline &&
	       baseline - ts->heatmap[index] >= G6TS_HEAT_THRESHOLD;
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
		struct g6ts_contact contact = { };
		unsigned int head = 0, tail = 0;

		if (ts->heat_seen[start] ||
		    !g6ts_heat_active(ts, start, baseline))
			continue;
		ts->heat_seen[start] = 1;
		ts->heat_queue[tail++] = start;

		while (head < tail) {
			unsigned int index = ts->heat_queue[head++];
			unsigned int row = index / G6TS_HEAT_COLS;
			unsigned int col = index % G6TS_HEAT_COLS;
			unsigned int strength = baseline - ts->heatmap[index];
			int dr, dc;

			contact.pixels++;
			contact.strength += strength;
			contact.weighted_x += (u64)col * strength;
			contact.weighted_y += (u64)row * strength;

			for (dr = -1; dr <= 1; dr++) {
				for (dc = -1; dc <= 1; dc++) {
					int neighbour_row = row + dr;
					int neighbour_col = col + dc;
					unsigned int neighbour;

					if ((!dr && !dc) || neighbour_row < 0 ||
					    neighbour_row >= G6TS_HEAT_ROWS ||
					    neighbour_col < 0 ||
					    neighbour_col >= G6TS_HEAT_COLS)
						continue;
					neighbour = neighbour_row * G6TS_HEAT_COLS +
						    neighbour_col;
					if (ts->heat_seen[neighbour] ||
					    !g6ts_heat_active(ts, neighbour,
							      baseline))
						continue;
					ts->heat_seen[neighbour] = 1;
					ts->heat_queue[tail++] = neighbour;
				}
			}
		}

		if (contact.pixels < G6TS_HEAT_MIN_PIXELS || !contact.strength)
			continue;
		contact.x = div_u64(contact.weighted_x * G6TS_LOGICAL_MAX,
				    (u64)contact.strength * (G6TS_HEAT_COLS - 1));
		contact.y = div_u64(contact.weighted_y * G6TS_LOGICAL_MAX,
				    (u64)contact.strength * (G6TS_HEAT_ROWS - 1));
		g6ts_store_contact(ts, &contact, &contact_count);
	}

	return contact_count;
}

static int g6ts_report_heat_contacts(struct g6ts *ts, const u8 *content,
				      size_t content_len)
{
	unsigned int count, i;
	int ret;

	ret = g6ts_extract_heatmap(ts, content, content_len);
	if (ret)
		return ret;
	count = g6ts_find_contacts(ts);

	for (i = 0; i < count; i++) {
		ts->contact_positions[i].x = ts->contacts[i].x;
		ts->contact_positions[i].y = ts->contacts[i].y;
	}
	ret = input_mt_assign_slots(ts->input, ts->contact_slots,
				    ts->contact_positions, count, 0);
	if (ret)
		return ret;

	for (i = 0; i < count; i++) {
		input_mt_slot(ts->input, ts->contact_slots[i]);
		input_mt_report_slot_state(ts->input, MT_TOOL_FINGER, true);
		input_report_abs(ts->input, ABS_MT_POSITION_X,
				 ts->contact_positions[i].x);
		input_report_abs(ts->input, ABS_MT_POSITION_Y,
				 ts->contact_positions[i].y);
	}
	input_mt_sync_frame(ts->input);
	input_sync(ts->input);
	ts->last_contact_count = count;
	if (count)
		ts->heatmap_contact_frames++;
	else
		ts->heatmap_idle_frames++;

	return 0;
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
		ts->heatmap_report_count++;
		if (g6ts_report_heat_contacts(ts, payload,
					      ts->last_content_len))
			ts->heatmap_decode_errors++;
		if (!ts->captured_report_len) {
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
			input_mt_sync_frame(ts->input);
			input_sync(ts->input);
			ts->last_contact_count = 0;
			if (!READ_ONCE(ts->stopping) &&
			    !READ_ONCE(ts->suspended)) {
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
		dev_info(&ts->spi->dev,
			 "DMA-LAB mode stage=%s response=%u ret=%d class=%u id=%#02x content_len=%u body=%*ph\n",
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
			dev_info(&ts->spi->dev,
				 "DMA-LAB mode stage=%s skipping interleaved DATA id=%#02x len=%u count=%llu\n",
				 stage, ts->last_content_id, ts->last_content_len,
				 ts->interleaved_data_count);
			continue;
		}
		if (ts->last_class == OUTPUT_REPORT_RESPONSE &&
		    ts->last_content_id == 0x09) {
			dev_info(&ts->spi->dev,
				 "DMA-LAB mode stage=%s skipping report-09 output acknowledgement\n",
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
		"mode=dma-only-lab initial_bus_io=automatic automatic_reset_recovery=1 current_pending=%d probe_pending=%d fatal_transport_error=%u interrupt_irq=%d interrupt_edges=%lld handled_edges=%lld\n"
		"manual_read_runs=%llu descriptor_runs=%llu report_descriptor_runs=%llu mode_sequence_runs=%llu windows_output_runs=%llu next_report_runs=%llu dma_pairs=%llu dma_outputs=%llu responses=%llu reset_seen=%u descriptor_seen=%u report_descriptor_seen=%u\n"
		"expected_report_descriptor_len=%u report_descriptor_len=%zu\n"
		"mode_stage=%u mode_value=%#02x mode_enabled=%u post_mode_reset_seen=%u captured_report_len=%zu interleaved_data=%llu touch_reports=%llu heatmap_reports=%llu last_interleaved_id=%#02x last_interleaved_len=%u\n"
		"heat_decode_errors=%llu contact_frames=%llu idle_frames=%llu last_contacts=%u heat_baseline=%#02x\n"
		"recovery_requests=%llu recovery_successes=%llu recovery_failures=%llu recovery_fail_streak=%u\n"
		"last_ret=%d header_ret=%d body_ret=%d output_ret=%d pending_before=%d pending_after=%d\n"
		"last_header=%*ph body_total_len=%zu class=%u content_len=%u content_id=%u last_body=%*ph\n",
		pending, ts->probe_pending, ts->fatal_transport_error,
		ts->interrupt_irq, atomic64_read(&ts->interrupt_edges),
		ts->handled_interrupt_edges,
		ts->manual_read_runs, ts->descriptor_runs,
		ts->report_descriptor_runs, ts->mode_sequence_runs,
		ts->windows_output_runs, ts->next_report_runs, ts->dma_pair_count,
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
		ts->last_heat_baseline,
		ts->recovery_requests, ts->recovery_successes,
		ts->recovery_failures, ts->recovery_fail_streak,
		ts->last_ret, ts->last_header_ret,
		ts->last_body_ret, ts->last_output_ret, ts->pending_before,
		ts->pending_after, (int)sizeof(ts->last_header), ts->last_header,
		ts->last_body_total_len, ts->last_class, ts->last_content_len,
		ts->last_content_id, (int)ts->last_body_len, ts->last_body);
}
static DEVICE_ATTR_RO(state);

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
	dev_info(&ts->spi->dev,
		 "DMA-LAB reset-read ret=%d pending=%d/%d header=%*ph class=%u len=%zu body=%*ph\n",
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
	dev_info(&ts->spi->dev,
		 "DMA-LAB device-descriptor ret=%d output=%d header=%*ph class=%u content_len=%u body=%*ph\n",
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
	dev_info(&ts->spi->dev,
		 "DMA-LAB report-descriptor ret=%d output=%d class=%u content_len=%u expected=%u stored=%zu\n",
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
	if (ts->stopping || ts->suspended) {
		mutex_unlock(&ts->io_lock);
		return;
	}

	ts->mode_enabled = false;
	input_mt_sync_frame(ts->input);
	input_sync(ts->input);
	ts->last_contact_count = 0;
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
		 "DMA-LAB full recovery ret=%d success=%llu failures=%llu retry=%u\n",
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
	dev_info(&ts->spi->dev,
		 "DMA-LAB mode-sequence stage=%u ret=%d prior_mode=%#02x enabled=%u fatal=%u\n",
		 ts->mode_stage, ts->last_ret, ts->mode_value,
		 ts->mode_enabled, ts->fatal_transport_error);
out:
	mutex_unlock(&ts->io_lock);
	return count;
}
static DEVICE_ATTR_WO(dma_mode_sequence);

static int g6ts_dma_report09_output(struct g6ts *ts, const u8 *content,
				    const char *stage)
{
	int ret;

	ts->last_output_ret = g6ts_dma_hidspi_output(ts, OUTPUT_REPORT, 0x09,
						    content, 63);
	ret = ts->last_output_ret;
	if (ret) {
		ts->fatal_transport_error = true;
		ts->last_ret = ret;
		return ret;
	}

	dev_info(&ts->spi->dev, "DMA-LAB Windows sequence sent %s\n", stage);
	usleep_range(1000, 2000);
	return 0;
}

/*
 * Exact ordering recovered from the Windows KD trace:
 *
 *   report09-A1, report09-A5, SetFeature05, report09-A1, report09-A5
 *
 * Report-09 acknowledgements are asynchronous.  The feature exchange and
 * capture loop drain them while searching for their own expected response.
 */
static ssize_t dma_windows_output_sequence_store(struct device *dev,
					  struct device_attribute *attr,
					  const char *buf, size_t count)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(dev));
	unsigned int response_index;
	bool cold_transition;
	bool descriptor_queued = false;
	bool recovery;
	bool run;
	int ret;

	ret = kstrtobool(buf, &run);
	if (ret)
		return ret;
	if (!run)
		return -EINVAL;

	mutex_lock(&ts->io_lock);
	if (!ts->report_descriptor_seen ||
	    ts->windows_output_runs >= G6TS_MODE_ATTEMPT_LIMIT ||
	    (ts->windows_output_runs && !ts->post_mode_reset_seen) ||
	    ts->fatal_transport_error) {
		ts->last_ret = -EAGAIN;
		goto out;
	}

	cold_transition = ts->mode_sequence_runs && !ts->windows_output_runs &&
			  ts->mode_enabled && !ts->post_mode_reset_seen;
	recovery = ts->post_mode_reset_seen || cold_transition;
	ts->windows_output_runs++;
	ts->mode_enabled = false;

	/*
	 * In the KD trace DEVICE_DESCRIPTOR is queued while heatmap streaming is
	 * still active.  RESET is consumed first; the descriptor reply remains
	 * queued and is consumed only after A1.  This overlap is stateful and must
	 * not be flattened into two synchronous transactions.
	 */
	if (cold_transition) {
		ts->mode_stage = 0;
		ts->last_output_ret = g6ts_dma_output(ts,
						      g6ts_device_descriptor_cmd,
						      sizeof(g6ts_device_descriptor_cmd));
		ret = ts->last_output_ret;
		if (ret) {
			ts->fatal_transport_error = true;
			ts->last_ret = ret;
			goto log;
		}
		descriptor_queued = true;

		for (response_index = 0;
		     response_index < G6TS_FEATURE_RESPONSE_LIMIT;
		     response_index++) {
			ret = g6ts_wait_pending(ts, 1000);
			if (ret) {
				ts->last_ret = ret;
				goto log;
			}
			ret = g6ts_dma_read_response(ts);
			if (ret)
				goto log;
			if (ts->last_class == RESET_RESPONSE) {
				ts->post_mode_reset_seen = true;
				break;
			}
			if (ts->last_class == DEVICE_DESCRIPTOR_RESPONSE &&
			    ts->last_content_id == 0 &&
			    ts->last_content_len == HIDSPI_DEVICE_DESCRIPTOR_SIZE) {
				/* Cold Linux state can return the descriptor before RESET. */
				descriptor_queued = false;
				continue;
			}
			if (ts->last_class == DATA) {
				ts->interleaved_data_count++;
				ts->last_interleaved_id = ts->last_content_id;
				ts->last_interleaved_len = ts->last_content_len;
				continue;
			}
			ts->last_ret = -EPROTO;
			goto log;
		}
		if (response_index == G6TS_FEATURE_RESPONSE_LIMIT) {
			ts->last_ret = -EOVERFLOW;
			goto log;
		}
	}

	ts->post_mode_reset_seen = false;

	/*
	 * Windows recovery deliberately has two transactions in flight: it sends
	 * DEVICE_DESCRIPTOR, sends A1, and only then consumes the descriptor
	 * response.  Preserve that ordering rather than serialising the request.
	 */
	if (recovery && !descriptor_queued) {
		ts->mode_stage = 1;
		ts->last_output_ret = g6ts_dma_output(ts,
						      g6ts_device_descriptor_cmd,
						      sizeof(g6ts_device_descriptor_cmd));
		ret = ts->last_output_ret;
		if (ret) {
			ts->fatal_transport_error = true;
			ts->last_ret = ret;
			goto log;
		}
	}

	ts->mode_stage = 1;
	ret = g6ts_dma_report09_output(ts, g6ts_output09_a1, "report09-A1-pre");
	if (ret)
		goto log;
	if (recovery) {
		ret = g6ts_wait_pending(ts, 1000);
		if (ret) {
			ts->last_ret = ret;
			goto log;
		}
		ret = g6ts_dma_read_response(ts);
		if (ret || g6ts_expect_response(ts, DEVICE_DESCRIPTOR_RESPONSE,
						0, HIDSPI_DEVICE_DESCRIPTOR_SIZE))
			goto log;
	}

	ts->mode_stage = 2;
	ret = g6ts_dma_report09_output(ts, g6ts_output09_a5, "report09-A5-pre");
	if (ret)
		goto log;

	ts->mode_stage = 3;
	ret = g6ts_dma_feature_exchange(ts, SET_FEATURE, 0x05,
					g6ts_mode_enable,
					sizeof(g6ts_mode_enable), "windows-set-05");
	if (ret || g6ts_expect_response(ts, SET_FEATURE_RESPONSE, 0x05, 0))
		goto log;

	/* The KD trace sends A1 while the following vendor packet is pending. */
	ret = g6ts_wait_pending(ts, 1000);
	if (ret) {
		ts->last_ret = ret;
		goto log;
	}

	ts->mode_stage = 4;
	ret = g6ts_dma_report09_output(ts, g6ts_output09_a1, "report09-A1-post");
	if (ret)
		goto log;

	/* Windows consumes one vendor DATA packet here before issuing A5. */
	ret = g6ts_wait_pending(ts, 1000);
	if (ret) {
		ts->last_ret = ret;
		goto log;
	}
	ret = g6ts_dma_read_response(ts);
	if (ret)
		goto log;
	if (ts->last_class == RESET_RESPONSE) {
		ts->post_mode_reset_seen = true;
		ts->last_ret = -EAGAIN;
		goto log;
	}
	if (ts->last_class != DATA) {
		ts->last_ret = -EPROTO;
		goto log;
	}
	ts->interleaved_data_count++;
	ts->last_interleaved_id = ts->last_content_id;
	ts->last_interleaved_len = ts->last_content_len;
	dev_info(&ts->spi->dev,
		 "DMA-LAB Windows sequence drained post-A1 DATA id=%#02x len=%u\n",
		 ts->last_content_id, ts->last_content_len);

	/* Windows sends A5 only after the following input interrupt is asserted. */
	ret = g6ts_wait_pending(ts, 1000);
	if (ret) {
		ts->last_ret = ret;
		goto log;
	}

	ts->mode_stage = 5;
	ret = g6ts_dma_report09_output(ts, g6ts_output09_a5, "report09-A5-post");
	if (ret)
		goto log;

	ts->mode_enabled = true;
	ts->last_ret = 0;
log:
	dev_info(&ts->spi->dev,
		 "DMA-LAB Windows-output-sequence stage=%u ret=%d enabled=%u fatal=%u\n",
		 ts->mode_stage, ts->last_ret, ts->mode_enabled,
		 ts->fatal_transport_error);
out:
	mutex_unlock(&ts->io_lock);
	return count;
}
static DEVICE_ATTR_WO(dma_windows_output_sequence);

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
			dev_info(&ts->spi->dev,
				 "DMA-LAB capture skipping DATA id=%#02x len=%u count=%llu\n",
				 ts->last_content_id, ts->last_content_len,
				 ts->interleaved_data_count);
			continue;
		}
		if (ts->last_class == OUTPUT_REPORT_RESPONSE &&
		    ts->last_content_id == 0x09) {
			dev_info(&ts->spi->dev,
				 "DMA-LAB capture skipping report-09 output acknowledgement\n");
			continue;
		}
		if (ts->last_class == RESET_RESPONSE) {
			ts->post_mode_reset_seen = true;
			ts->mode_enabled = false;
			dev_info(&ts->spi->dev,
				 "DMA-LAB capture saw post-mode reset; mode sequence must be retried\n");
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

	dev_info(&ts->spi->dev,
		 "DMA-LAB next-report ret=%d class=%u id=%#02x content_len=%u captured=%zu\n",
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
	ts->captured_report = devm_kmalloc(&spi->dev, G6TS_MAX_BODY,
					   GFP_KERNEL);
	if (!ts->captured_report)
		return -ENOMEM;

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
	ret = device_create_file(&spi->dev,
				 &dev_attr_dma_windows_output_sequence);
	if (ret)
		goto err_recover;
	ret = device_create_file(&spi->dev, &dev_attr_dma_next_report);
	if (ret)
		goto err_windows_output_sequence;
	ret = device_create_bin_file(&spi->dev, &bin_attr_captured_report);
	if (ret)
		goto err_next_report;

	ts->recovery_requests++;
	schedule_delayed_work(&ts->recovery_work,
		msecs_to_jiffies(G6TS_RECOVERY_DELAY_MS));
	dev_info(&spi->dev,
		 "DMA touch probe complete: pending=%d, automatic enumeration scheduled\n",
		 ts->probe_pending);
	return 0;

err_next_report:
	device_remove_file(&spi->dev, &dev_attr_dma_next_report);
err_windows_output_sequence:
	device_remove_file(&spi->dev,
			   &dev_attr_dma_windows_output_sequence);
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
	device_remove_bin_file(&spi->dev, &bin_attr_captured_report);
	device_remove_file(&spi->dev, &dev_attr_dma_next_report);
	device_remove_file(&spi->dev,
			   &dev_attr_dma_windows_output_sequence);
	device_remove_file(&spi->dev, &dev_attr_dma_recover);
	device_remove_file(&spi->dev, &dev_attr_dma_mode_sequence);
	device_remove_file(&spi->dev, &dev_attr_report_descriptor);
	device_remove_file(&spi->dev, &dev_attr_dma_report_descriptor);
	device_remove_file(&spi->dev, &dev_attr_dma_device_descriptor);
	device_remove_file(&spi->dev, &dev_attr_dma_read);
	device_remove_file(&spi->dev, &dev_attr_state);
	g6ts_power_off(ts);
}

static int g6ts_suspend(struct device *dev)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(dev));

	WRITE_ONCE(ts->suspended, true);
	WRITE_ONCE(ts->mode_enabled, false);
	cancel_delayed_work_sync(&ts->recovery_work);
	mutex_lock(&ts->io_lock);
	input_mt_sync_frame(ts->input);
	input_sync(ts->input);
	ts->last_contact_count = 0;
	g6ts_power_off(ts);
	mutex_unlock(&ts->io_lock);
	return 0;
}

static int g6ts_resume(struct device *dev)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(dev));

	WRITE_ONCE(ts->suspended, false);
	mutex_lock(&ts->io_lock);
	ts->recovery_requests++;
	mutex_unlock(&ts->io_lock);
	schedule_delayed_work(&ts->recovery_work, 0);
	return 0;
}
static DEFINE_SIMPLE_DEV_PM_OPS(g6ts_pm_ops, g6ts_suspend, g6ts_resume);

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
		.pm = pm_sleep_ptr(&g6ts_pm_ops),
	},
	.id_table = g6ts_spi_id,
	.probe = g6ts_probe,
	.remove = g6ts_remove,
};
module_spi_driver(g6ts_driver);

MODULE_DESCRIPTION("Surface G6 Touch DMA-only laboratory driver");
MODULE_AUTHOR("SP11 reverse-engineering project");
MODULE_LICENSE("GPL");
