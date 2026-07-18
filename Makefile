KDIR ?= /lib/modules/$(shell uname -r)/build

.PHONY: all production legacy-fifo phase52 phase55 test clean clean-phase52 clean-phase55

all: production

production: phase55

legacy-fifo: phase52

phase52:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules

phase55:
	$(MAKE) -C $(CURDIR)/phase55/modules KDIR=$(KDIR)

test:
	python3 -m unittest discover -s tests -v

clean: clean-phase52 clean-phase55

clean-phase52:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean

clean-phase55:
	$(MAKE) -C $(CURDIR)/phase55/modules KDIR=$(KDIR) clean
