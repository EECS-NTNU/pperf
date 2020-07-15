CC = gcc
FLAGS = -O3

TARGETS := pperf pperf-lynsyn pperf-rapl-sysfs

DEPDIR := github

LINKING := -lrt

prefix := /usr/local/bin

install: $(TARGETS)
	mkdir -p $(prefix)
	cp $(TARGETS) $(prefix)/

all: $(TARGETS)

pperf: % : %.o pmu/dummy.o
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) $^ -o $@ $(LINKING)

pperf-rapl-sysfs: % : pperf.o pmu/rapl-sysfs.o
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) $^ -o $@ $(LINKING)

pperf-lynsyn: pperf-% : pperf.o pmu/%.o $(DEPDIR)/lynsyn/liblynsyn/lynsyn.o
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) $^ -o $@ $(LINKING) -lusb-1.0

pperf-lynsyn-old: pperf-% : pperf.o pmu/%.o
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) $^ -o $@ $(LINKING) -lusb-1.0

pmu/%.o : pmu/%.c
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

%.o : %.c
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

clean:
	rm -Rf $(DEPDIR)
	rm -Rf pmu/*.o *.o $(TARGETS) pperf-lynsyn-old

$(DEPDIR):
	mkdir $(DEPDIR)

$(DEPDIR)/sthem: $(DEPDIR)
	echo "deprecated" 1>&2; exit 1
	[ -f "$@" ] && rm -Rf "$@" || true
	git clone --depth 1 --branch develop https://github.com/tulipp-eu/sthem $@

$(DEPDIR)/lynsyn: $(DEPDIR)
	[ -f "$@" ] && rm -Rf "$@" || true
	git clone --depth 1 https://github.com/EECS-NTNU/lynsyn-host-software $@

pmu/lynsyn-old.o : %.o : %.c $(DEPDIR)/sthem
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) -I$(DEPDIR)/sthem/power_measurement_utility/mcu/common -I/usr/include/libusb-1.0/ $(DEFINES) -c $< -o $@

pmu/lynsyn.o : %.o : %.c $(DEPDIR)/lynsyn
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) -I$(DEPDIR)/lynsyn/common  -I$(DEPDIR)/lynsyn/liblynsyn $(DEFINES) -c $< -o $@

$(DEPDIR)/lynsyn/liblynsyn/lynsyn.o : %.o : $(DEPDIR)/lynsyn %.c
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) -I$(DEPDIR)/lynsyn/common -I/usr/include/libusb-1.0/ $(DEFINES) -c $(filter %.c,$^) -o $@
