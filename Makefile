CC = gcc
FLAGS = -O3
prefix := /usr/local/bin
build_dir := build

TARGETS := $(build_dir)/pperf $(filter-out $(build_dir)/pperf-dummy,$(patsubst pmu/%.c,$(build_dir)/pperf-%,$(wildcard pmu/*.c)))

LINKING := -lrt
dep_dir := github

all: $(TARGETS)

install: $(TARGETS)
	@mkdir -p $(prefix)
	cp $(TARGETS) $(prefix)/
	chmod +x $(patsubst $(build_dir)/%,$(prefix)/%,$^)

uninstall:
	rm -f $(patsubst $(build_dir)/%,$(prefix)/%,$(TARGETS))

$(build_dir)/pperf: % : %.o $(build_dir)/pmu_dummy.o
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) $^ -o $@ $(LINKING)

$(filter-out $(build_dir)/pperf $(build_dir)/pperf-lynsyn,$(TARGETS)): $(build_dir)/pperf-% : $(build_dir)/pperf.o $(build_dir)/pmu_%.o
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) $^ -o $@ $(LINKING)

$(build_dir)/pperf-lynsyn: $(build_dir)/pperf-% : $(build_dir)/pperf.o $(build_dir)/pmu_%.o $(build_dir)/lynsyn.o
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) $^ -o $@ $(LINKING) -lusb-1.0

$(build_dir)/pmu_%.o : pmu/%.c
	@mkdir -p $(@D)
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

$(build_dir)/%.o : %.c
	@mkdir -p $(@D)
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

$(build_dir)/pmu_lynsyn.o : pmu/lynsyn.c $(dep_dir)/lynsyn/liblynsyn
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) -I$(dep_dir)/lynsyn/common  -I$(dep_dir)/lynsyn/liblynsyn $(DEFINES) -c $(firstword $^) -o $@

$(build_dir)/lynsyn.o : $(dep_dir)/lynsyn/liblynsyn/lynsyn.c
	$(CROSS_COMPILE)$(CC) $(FLAGS) $(INCLUDES) -I$(dep_dir)/lynsyn/common -I/usr/include/libusb-1.0/ $(DEFINES) -c $^ -o $@

$(dep_dir)/lynsyn/liblynsyn $(dep_dir)/lynsyn/liblynsyn/lynsyn.c:
	@mkdir -p $(dep_dir)
	git clone --depth 1 https://github.com/EECS-NTNU/lynsyn-host-software $(dep_dir)/lynsyn

clean:
	rm -Rf $(build_dir)

mrproper: clean
	rm -Rf $(dep_dir)


