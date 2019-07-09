CC = gcc
FLAGS = -O3

TARGETS = lynsyn dummy rapl-sysfs

LINKING := -lrt

all: $(TARGETS)

lynsyn: % : intrusiveProfiler.o pmu/%.o
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) $^ -o $@ $(LINKING) -lusb-1.0

dummy rapl-sysfs: % : intrusiveProfiler.o pmu/%.o
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) $^ -o $@ $(LINKING)

pmu/lynsyn.o : %.o : %.c sthem_repository
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) -I/usr/include/libusb-1.0/ $(DEFINES) -c $< -o $@

pmu/%.o : pmu/%.c
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

%.o : %.c
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

sthem_repository:
	[ -d sthem ] && { cd sthem; git pull; } || { git clone https://github.com/tulipp-eu/sthem; cd sthem; git checkout develop; }
	grep -q "sthem" .gitignore || echo sthem >> .gitignore

clean:
	rm -Rf sthem
	rm -Rf pmu/*.o *.o $(TARGETS)
