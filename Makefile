CC = gcc
FLAGS = -O3

TARGETS = lynsyn dummy rapl-sysfs

all: $(TARGETS)

$(TARGETS): % : intrusiveProfiler.o pmu/%.o
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) $^ -o $@ $(LINKING) -lrt -lusb-1.0

pmu/lynsyn.o : %.o : %.c sthem_repository
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) -I/usr/include/libusb-1.0/ $(DEFINES) -c $< -o $@

pmu/%.o : pmu/%.c
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

%.o : %.c
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

sthem_repository:
	[ -d sthem ] && { cd sthem; git pull; } || { git clone git@github.com:tulipp-eu/sthem; cd sthem; git checkout develop; }
	grep -q "sthem" .gitignore || echo sthem >> .gitignore

clean:
	rm -Rf sthem
	rm -Rf pmu/*.o *.o $(TARGETS)
