# SPDX-License-Identifier: GPL-2.0
KDIR ?= /lib/modules/$(shell uname -r)/build
EXPECTED_KERNEL_RELEASE := 7.3.0-sp11-unified13
TARGET_KERNEL_RELEASE := $(strip $(shell cat $(KDIR)/include/config/kernel.release 2>/dev/null))

.PHONY: all verify-target clean
all: verify-target
	$(MAKE) -C $(KDIR) M=$(CURDIR) W=1 modules

verify-target:
	@if [ "$(TARGET_KERNEL_RELEASE)" != "$(EXPECTED_KERNEL_RELEASE)" ]; then \
		echo "Expected configured $(EXPECTED_KERNEL_RELEASE) build tree; found '$(TARGET_KERNEL_RELEASE)'" >&2; \
		exit 1; \
	fi

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
