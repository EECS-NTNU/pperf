CC = gcc
FLAGS = -O3

TARGETS := dummy lynsyn lynsyn_v3 rapl-sysfs

DEPDIR := github

LINKING := -lrt

all: $(TARGETS)

lynsyn: % : intrusiveProfiler.o pmu/%.o
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) $^ -o $@ $(LINKING) -lusb-1.0

lynsyn_v3: % : intrusiveProfiler.o pmu/%.o $(DEPDIR)/lynsyn/liblynsyn/lynsyn.o
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) $^ -o $@ $(LINKING) -lusb-1.0

dummy rapl-sysfs: % : intrusiveProfiler.o pmu/%.o
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) $^ -o $@ $(LINKING)

pmu/%.o : pmu/%.c
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

%.o : %.c
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

clean:
	rm -Rf $(DEPDIR)
	rm -Rf $(DEPDIR)/sthem
	rm -Rf $(DEPDIR)/tulipp-tool-chain
	rm -Rf pmu/*.o *.o $(TARGETS)

$(DEPDIR):
	mkdir $(DEPDIR)

$(DEPDIR)/sthem: $(DEPDIR)
	[ -f "$@" ] && rm -Rf "$@" || true
	git clone --depth 1 --branch develop https://github.com/tulipp-eu/sthem $@

$(DEPDIR)/lynsyn: $(DEPDIR)
	[ -f "$@" ] && rm -Rf "$@" || true
	git clone --depth 1 https://github.com/EECS-NTNU/lynsyn $@

pmu/lynsyn.o : %.o : %.c $(DEPDIR)/sthem
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) -I$(DEPDIR)/sthem/power_measurement_utility/mcu/common -I/usr/include/libusb-1.0/ $(DEFINES) -c $< -o $@

pmu/lynsyn_v3.o : %.o : %.c $(DEPDIR)/lynsyn
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) -I$(DEPDIR)/lynsyn/mcu/common  -I$(DEPDIR)/lynsyn/liblynsyn $(DEFINES) -c $< -o $@

$(DEPDIR)/lynsyn/liblynsyn/lynsyn.o : %.o : $(DEPDIR)/lynsyn %.c
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) -I$(DEPDIR)/lynsyn/mcu/common -I/usr/include/libusb-1.0/ $(DEFINES) -c $(filter %.c,$^) -o $@
