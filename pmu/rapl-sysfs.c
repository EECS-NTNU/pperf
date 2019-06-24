#include "pmu.h"
#include <stddef.h>
#include <stdio.h>
#include <unistd.h>
#include <time.h>


struct PMUData {
  double value;
} __attribute__((packed));

uint32_t pmuDataSize(void) {
  return sizeof(struct PMUData);
}

char *standardRapl = "/sys/class/powercap/intel-rapl:0";



FILE *RAPLFile;

unsigned long long maxEnergy = 0;
unsigned long long lastEnergy = 0;
unsigned long long lastTime = 0;


const char *pmuAbout(void) {
   return "RAPL SysFS PMU, reads energy values from sysfs";
}

int pmuInit(char *pmuArg) {
  char filePath[1024];
  if (pmuArg == NULL)
    pmuArg = standardRapl;

  snprintf(filePath, 1024, "%s/max_energy_range_uj", pmuArg);
  if (access(filePath, R_OK) == -1)
    goto pmu_arg_error;
  RAPLFile = fopen(filePath, "r");
  if (fscanf(RAPLFile, "%llu", &maxEnergy) != 1)
    goto pmu_read_error;

  snprintf(filePath, 1024, "%s/energy_uj", pmuArg);
  if (access(filePath, R_OK) == -1)
    goto pmu_arg_error;
  RAPLFile = fopen(filePath, "r");
  if (fscanf(RAPLFile, "%llu", &lastEnergy) != 1)
    goto pmu_read_error;

  struct PMUData dummy;
  pmuRead(&dummy);

  return 0;
 pmu_read_error:
  fprintf(stderr, "PMU ERROR: could not read rapl endpoint '%s'\n", filePath);
  return 1;
 pmu_arg_error:
  fprintf(stderr, "PMU ERROR: rapl endpoint '%s' not found\n", filePath);
  return 1;
}

void pmuRead(struct PMUData *data) {
  struct timespec currentTime;
  unsigned long long energy = 0;
  long long energyDiff = 0;
  unsigned long long time = 0;
  if (freopen(NULL, "r", RAPLFile) == NULL) {
    data->value = 0.0;
    return;
  }
  if (fscanf(RAPLFile, "%llu", &energy) != 1) {
    data->value = 0.0;
    return;
  }
  clock_gettime(CLOCK_REALTIME, &currentTime);
  time = (currentTime.tv_sec * 1000000) + (currentTime.tv_nsec / 1000);

  if (energy < lastEnergy)
    energyDiff = (maxEnergy - lastEnergy) + energy;
  else
    energyDiff = energy - lastEnergy;

  data->value = (double) (energyDiff) / (time - lastTime);

  lastEnergy = energy;
  lastTime = time;
}

enum PMU_WHAT pmuWhat(void) {
  return PMU_POWER;
}

int pmuRelease(void) {
  fclose(RAPLFile);
  return 0;
}
