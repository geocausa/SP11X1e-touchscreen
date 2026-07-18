KDIR ?= /lib/modules/$(shell uname -r)/build
EXPECTED_KERNEL_RELEASE ?= 7.1.3-sp11-baseline1+
TARGET_KERNEL_RELEASE := $(strip $(shell cat $(KDIR)/include/config/kernel.release 2>/dev/null))

.PHONY: all clean verify-target

all: verify-target
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules

verify-target:
	@if [ -z "$(TARGET_KERNEL_RELEASE)" ]; then \
		echo "Cannot determine the configured kernel release under $(KDIR)" >&2; \
		exit 1; \
	fi
	@if [ "$(TARGET_KERNEL_RELEASE)" != "$(EXPECTED_KERNEL_RELEASE)" ] && \
	   [ "$(ALLOW_UNTESTED_KERNEL)" != "1" ]; then \
		echo "Refusing an unreviewed MSHW0485 DMA build for $(TARGET_KERNEL_RELEASE)" >&2; \
		echo "Expected $(EXPECTED_KERNEL_RELEASE). Rebase the matched sources first." >&2; \
		echo "Use ALLOW_UNTESTED_KERNEL=1 only for an intentional porting build." >&2; \
		exit 1; \
	fi

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
