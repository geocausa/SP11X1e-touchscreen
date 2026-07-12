// SPDX-License-Identifier: GPL-2.0
/*
 * Microsoft Surface G6 Touch (MSHW0485), BIOS-reference Linux driver.
 *
 * This driver deliberately implements only normal touchscreen input.
 * It contains no Windows DMA/GPI path, no CFU, no FRU unlock, no pen path,
 * no storage-protect GPIO writes, and no generic SPI fallback.
 */

#include <linux/acpi.h>
#include <linux/unaligned.h>
#include <linux/bitfield.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/hrtimer.h>
#include <linux/input.h>
#include <linux/interrupt.h>
#include <linux/irq.h>
#include <linux/jiffies.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/pm.h>
#include <linux/slab.h>
#include <linux/spi/spi.h>
#include <linux/spi/spi-geni-qcom-biosref.h>
#include <linux/workqueue.h>

#define G6TS_NAME                       "g6ts-biosref"
#define G6TS_SPI_HZ                     40000000U
#define G6TS_TIMER_US                   5300U
#define G6TS_MAX_BODY                   4096U
#define G6TS_DIAG_BODY                  64U
#define G6TS_HEADER_SYNC                0x5a
#define G6TS_CONTENT_TOUCH              0x40
#define G6TS_NORMAL_COPY_LEN_MINUS_ONE  5
#define G6TS_CLASS_TOUCH                1
#define G6TS_CLASS_SERVICE              3
#define G6TS_CLASS_READY                7

static const u8 g6ts_header_cmd[8] = {
	0xeb, 0x00, 0x10, 0x00, 0xff, 0xff, 0xff, 0xff,
};
static const u8 g6ts_body_cmd[8] = {
	0xeb, 0x00, 0x10, 0x04, 0xff, 0xff, 0xff, 0xff,
};
/*
 * Descriptor/readiness command, EFI helper RVA 0x5B88 ("must not be
 * ignored"): mode byte 0xE2 (config[0x15] == 1) written over template
 * 00 00 20 00 01 00 00 00, sent via ExecuteXfr before normal polling.
 */
static const u8 g6ts_ready_cmd[8] = {
	0xe2, 0x00, 0x20, 0x00, 0x01, 0x00, 0x00, 0x00,
};

struct g6ts {
	struct spi_device *spi;
	struct input_dev *input;
	struct hrtimer timer;
	struct work_struct work;
	struct mutex io_lock;
	struct gpio_desc *interrupt_gpio;
	struct gpio_desc *power_gpio;
	struct gpio_desc *reset_gpio;
	bool running;
	u8 *body;
	u8 last_header[4];
	u8 last_body[G6TS_DIAG_BODY];
	size_t last_body_len;
	size_t last_body_total_len;
	u64 reads;
	u64 touches;
	u64 transport_errors;
	u64 protocol_errors;
	bool ready;
	u64 ready_attempts;
	u64 ready_gpio_timeouts;
	u64 gpio_errors;
	u64 class1_events;
	u64 class3_events;
	u64 class7_events;
	u64 other_class_events;
	u8 last_ready_body[G6TS_DIAG_BODY];
	size_t last_ready_len;
	size_t last_ready_total_len;
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

	/* Manufacturer-defined sequence: GPIO64 high, 500 ms, GPIO48 high. */
	ret = g6ts_acpi_method(&ts->spi->dev, "_PS0");
	if (ret)
		return dev_err_probe(&ts->spi->dev, ret,
				     "ACPI _PS0 failed\n");

	/* Manufacturer-defined reset: GPIO48 low 300 ms, then high. */
	ret = g6ts_acpi_method(&ts->spi->dev, "_RST");
	if (ret)
		return dev_err_probe(&ts->spi->dev, ret,
				     "ACPI _RST failed\n");
	return 0;
}

static void g6ts_power_off(struct g6ts *ts)
{
	if (ts->power_gpio && ts->reset_gpio) {
		gpiod_set_value_cansleep(ts->reset_gpio, 0);
		msleep(10);
		gpiod_set_value_cansleep(ts->power_gpio, 0);
		return;
	}

	/* _PS3: reset low, 10 ms, local power-enable low. */
	g6ts_acpi_method(&ts->spi->dev, "_PS3");
}

static int g6ts_transfer(struct g6ts *ts, const u8 cmd[8],
			 void *rx, size_t rx_len)
{
	return qcom_geni_spi_biosref_xfer(ts->spi, cmd, 8, rx, rx_len,
					 G6TS_SPI_HZ, 1000);
}

/*
 * One header+body read using confirmed E0-modified framing.
 * On success *cls holds response-body class byte (prefix[0]) and
 * *out_len the body length.
 */
static int g6ts_read_raw(struct g6ts *ts, u8 *cls, size_t *out_len)
{
	u8 header[4];
	u32 h;
	size_t body_len;
	int ret;

	ret = g6ts_transfer(ts, g6ts_header_cmd, header, sizeof(header));
	if (ret)
		return ret;

	memcpy(ts->last_header, header, sizeof(header));
	if (header[3] != G6TS_HEADER_SYNC)
		return -ENODATA;

	h = get_unaligned_le32(header);
	body_len = (h >> 6) & 0xfffc;
	if (body_len < 4 || body_len > G6TS_MAX_BODY)
		return -EPROTO;

	ret = g6ts_transfer(ts, g6ts_body_cmd, ts->body, body_len);
	if (ret)
		return ret;

	ts->last_body_total_len = body_len;
	ts->last_body_len = min_t(size_t, body_len, sizeof(ts->last_body));
	memcpy(ts->last_body, ts->body, ts->last_body_len);

	*cls = ts->body[0];
	if (out_len)
		*out_len = body_len;
	return 0;
}

static int g6ts_send_ready_cmd(struct g6ts *ts)
{
	u8 scratch[4];

	return g6ts_transfer(ts, g6ts_ready_cmd, scratch, sizeof(scratch));
}

static int g6ts_wait_pending(struct g6ts *ts, bool pending,
			     unsigned int timeout_ms)
{
	unsigned long deadline = jiffies + msecs_to_jiffies(timeout_ms);
	int value;

	do {
		value = gpiod_get_value_cansleep(ts->interrupt_gpio);
		if (value < 0) {
			ts->gpio_errors++;
			return value;
		}
		if (!!value == pending)
			return 0;
		usleep_range(1000, 2000);
	} while (time_before(jiffies, deadline));

	return -ETIMEDOUT;
}

static void g6ts_account_class(struct g6ts *ts, u8 cls)
{
	switch (cls) {
	case G6TS_CLASS_TOUCH:
		ts->class1_events++;
		break;
	case G6TS_CLASS_SERVICE:
		ts->class3_events++;
		break;
	case G6TS_CLASS_READY:
		ts->class7_events++;
		break;
	default:
		ts->other_class_events++;
		break;
	}
}

/*
 * EFI readiness flow (RVA 0x5B88 + 0x5964): send 0xE2 command, wait for
 * the response, accept class 7.  Class 3 responses are acknowledged by
 * re-sending the command.  INT-pin wait is replaced by a bounded read
 * poll since the response read itself is authoritative.
 */
static int g6ts_readiness(struct g6ts *ts)
{
	unsigned int attempt;
	size_t body_len;
	u8 cls;
	int ret;

	for (attempt = 0; attempt < 5; attempt++) {
		ts->ready_attempts++;
		ret = g6ts_send_ready_cmd(ts);
		if (ret)
			return ret;

		ret = g6ts_wait_pending(ts, true, 1000);
		if (ret) {
			if (ret == -ETIMEDOUT)
				ts->ready_gpio_timeouts++;
			break;
		}

		ret = g6ts_read_raw(ts, &cls, &body_len);
		if (ret)
			break;
		g6ts_account_class(ts, cls);
		if (cls == G6TS_CLASS_READY) {
			ts->last_ready_total_len = body_len;
			ts->last_ready_len =
				min_t(size_t, body_len,
				      sizeof(ts->last_ready_body));
			memcpy(ts->last_ready_body, ts->body,
			       ts->last_ready_len);
			ts->ready = true;
			dev_info(&ts->spi->dev,
				 "readiness OK on attempt %u: body_len=%zu body=%*ph\n",
				 attempt + 1, body_len,
				 (int)ts->last_ready_len,
				 ts->last_ready_body);
			return 0;
		}
		if (cls == G6TS_CLASS_SERVICE)
			continue; /* firmware responds by re-sending 0xE2 */

		dev_info(&ts->spi->dev,
			 "readiness: unexpected class %u body=%*ph\n",
			 cls, (int)ts->last_body_len, ts->last_body);
	}
	dev_warn(&ts->spi->dev,
		 "readiness failed after %u attempts, last_header=%*ph\n",
		 attempt, 4, ts->last_header);
	return -ETIMEDOUT;
}

/*
 * EFI ResetHidSpiDeviceController (RVA 0x6398): assert reset, stall,
 * then run the power-up/readiness helper path again.  The EFI driver
 * calls this after the first readiness and right before starting the
 * async polling loop.
 */
static int g6ts_reset_controller(struct g6ts *ts)
{
	int ret;

	if (ts->power_gpio && ts->reset_gpio) {
		gpiod_set_value_cansleep(ts->reset_gpio, 0);
		msleep(300);
		gpiod_set_value_cansleep(ts->reset_gpio, 1);
		msleep(300);
	} else {
		ret = g6ts_acpi_method(&ts->spi->dev, "_RST");
		if (ret)
			return ret;
	}
	return g6ts_readiness(ts);
}

static int g6ts_read_report(struct g6ts *ts)
{
	size_t body_len;
	u16 payload_len;
	u16 raw_x, raw_y;
	u8 flags;
	u8 cls;
	int ret;

	ret = g6ts_read_raw(ts, &cls, &body_len);
	if (ret)
		return ret;
	g6ts_account_class(ts, cls);

	if (cls == G6TS_CLASS_SERVICE) {
		/* EFI acks service class via the full readiness helper. */
		ret = g6ts_readiness(ts);
		if (ret)
			return ret;
		return -EAGAIN;
	}
	if (cls != G6TS_CLASS_TOUCH)
		return -EAGAIN; /* service/readiness class, not normal input */

	payload_len = get_unaligned_le16(&ts->body[1]);
	if (body_len < 9 || payload_len != G6TS_NORMAL_COPY_LEN_MINUS_ONE ||
	    ts->body[3] != G6TS_CONTENT_TOUCH)
		return -EPROTO;

	flags = ts->body[4];
	raw_x = get_unaligned_le16(&ts->body[5]);
	raw_y = get_unaligned_le16(&ts->body[7]);

	input_report_key(ts->input, BTN_TOUCH, !!(flags & BIT(0)));
	if (flags & BIT(0)) {
		input_report_abs(ts->input, ABS_X, raw_x >> 5);
		input_report_abs(ts->input, ABS_Y, raw_y >> 5);
		ts->touches++;
	}
	input_sync(ts->input);
	return 0;
}

static void g6ts_work(struct work_struct *work)
{
	struct g6ts *ts = container_of(work, struct g6ts, work);
	int ret;

	mutex_lock(&ts->io_lock);
	if (!ts->running)
		goto out;

	ts->reads++;
	ret = g6ts_read_report(ts);
	if (ret == -ENODATA || ret == -EAGAIN)
		goto out;
	if (ret == -EPROTO)
		ts->protocol_errors++;
	else if (ret)
		ts->transport_errors++;
out:
	mutex_unlock(&ts->io_lock);
}

static bool g6ts_int_asserted(struct g6ts *ts)
{
	int value = gpiod_get_value(ts->interrupt_gpio);

	if (value < 0) {
		ts->gpio_errors++;
		return false;
	}
	return value;
}

static enum hrtimer_restart g6ts_timer(struct hrtimer *timer)
{
	struct g6ts *ts = container_of(timer, struct g6ts, timer);

	if (READ_ONCE(ts->running)) {
		/* UEFI polls every 5.3 ms and reads only when GPIO51 asserts. */
		if (g6ts_int_asserted(ts))
			schedule_work(&ts->work);
		hrtimer_forward_now(timer, ns_to_ktime(G6TS_TIMER_US * NSEC_PER_USEC));
		return HRTIMER_RESTART;
	}
	return HRTIMER_NORESTART;
}

static void g6ts_start(struct g6ts *ts)
{
	WRITE_ONCE(ts->running, true);
	hrtimer_start(&ts->timer, ns_to_ktime(G6TS_TIMER_US * NSEC_PER_USEC),
		      HRTIMER_MODE_REL);
}

static void g6ts_stop(struct g6ts *ts)
{
	WRITE_ONCE(ts->running, false);
	hrtimer_cancel(&ts->timer);
	cancel_work_sync(&ts->work);
}

static ssize_t state_show(struct device *dev,
			  struct device_attribute *attr, char *buf)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(dev));
	int pending = gpiod_get_value_cansleep(ts->interrupt_gpio);

	return sysfs_emit(buf,
		"running=%u ready=%u gpio51_pending=%d reads=%llu touches=%llu transport_errors=%llu protocol_errors=%llu\n"
		"ready_attempts=%llu ready_gpio_timeouts=%llu gpio_errors=%llu class1=%llu class3=%llu class7=%llu class_other=%llu\n"
		"last_ready_total_len=%zu last_ready=%*ph\n"
		"last_header=%*ph last_body_total_len=%zu last_body=%*ph\n",
		ts->running, ts->ready, pending, ts->reads, ts->touches,
		ts->transport_errors, ts->protocol_errors,
		ts->ready_attempts, ts->ready_gpio_timeouts, ts->gpio_errors,
		ts->class1_events, ts->class3_events, ts->class7_events,
		ts->other_class_events,
		ts->last_ready_total_len,
		(int)ts->last_ready_len, ts->last_ready_body,
		4, ts->last_header, ts->last_body_total_len,
		(int)ts->last_body_len, ts->last_body);
}
static DEVICE_ATTR_RO(state);

static int g6ts_probe(struct spi_device *spi)
{
	struct g6ts *ts;
	struct input_dev *input;
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
				     "failed to get GPIO51 pending input\n");
	if (gpiod_cansleep(ts->interrupt_gpio))
		return dev_err_probe(&spi->dev, -EOPNOTSUPP,
				     "GPIO51 cannot be sampled from the UEFI-rate timer\n");
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
				     "power and reset GPIOs must be provided together\n");
	mutex_init(&ts->io_lock);
	INIT_WORK(&ts->work, g6ts_work);
	hrtimer_setup(&ts->timer, g6ts_timer, CLOCK_MONOTONIC,
		      HRTIMER_MODE_REL);
	spi_set_drvdata(spi, ts);

	spi->max_speed_hz = G6TS_SPI_HZ;
	spi->bits_per_word = 8;
	spi->mode = SPI_MODE_0;
	ret = spi_setup(spi);
	if (ret)
		return dev_err_probe(&spi->dev, ret, "spi_setup failed\n");

	ret = g6ts_power_on(ts);
	if (ret)
		return ret;

	ret = g6ts_readiness(ts);
	if (ret)
		dev_warn(&spi->dev,
			 "continuing without readiness handshake (%d)\n", ret);

	/* EFI: reset controller (reset pulse + readiness) before polling. */
	ret = g6ts_reset_controller(ts);
	if (ret)
		dev_warn(&spi->dev,
			 "reset-controller sequence incomplete (%d)\n", ret);

	input = devm_input_allocate_device(&spi->dev);
	if (!input) {
		ret = -ENOMEM;
		goto err_power;
	}
	ts->input = input;
	input->name = "Surface G6 Touch (UEFI BIOS reference)";
	input->id.bustype = BUS_SPI;
	__set_bit(INPUT_PROP_DIRECT, input->propbit);
	input_set_capability(input, EV_KEY, BTN_TOUCH);
	input_set_abs_params(input, ABS_X, 0, 1023, 0, 0);
	input_set_abs_params(input, ABS_Y, 0, 1023, 0, 0);

	ret = input_register_device(input);
	if (ret)
		goto err_power;

	ret = device_create_file(&spi->dev, &dev_attr_state);
	if (ret)
		goto err_power;

	g6ts_start(ts);
	dev_info(&spi->dev,
		 "started BIOS-reference polled path: active-low GPIO51 descriptor, 40MHz, 5.3ms timer\n");
	return 0;

err_power:
	g6ts_power_off(ts);
	return ret;
}

static void g6ts_remove(struct spi_device *spi)
{
	struct g6ts *ts = spi_get_drvdata(spi);

	device_remove_file(&spi->dev, &dev_attr_state);
	g6ts_stop(ts);
	g6ts_power_off(ts);
}

static int g6ts_suspend(struct device *dev)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(dev));

	g6ts_stop(ts);
	g6ts_power_off(ts);
	return 0;
}

static int g6ts_resume(struct device *dev)
{
	struct g6ts *ts = spi_get_drvdata(to_spi_device(dev));
	int ret;

	ret = g6ts_power_on(ts);
	if (!ret) {
		g6ts_readiness(ts);
		g6ts_reset_controller(ts);
		g6ts_start(ts);
	}
	return ret;
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

static struct spi_driver g6ts_driver = {
	.driver = {
		.name = G6TS_NAME,
		.acpi_match_table = ACPI_PTR(g6ts_acpi_match),
		.of_match_table = g6ts_of_match,
		.pm = pm_sleep_ptr(&g6ts_pm_ops),
	},
	.probe = g6ts_probe,
	.remove = g6ts_remove,
};
module_spi_driver(g6ts_driver);

MODULE_DESCRIPTION("Surface G6 Touch BIOS-reference polled driver");
MODULE_AUTHOR("Reverse-engineered from Surface UEFI primary sources");
MODULE_LICENSE("GPL");
