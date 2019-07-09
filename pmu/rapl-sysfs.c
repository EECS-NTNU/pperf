#include "pmu.h"
#include <stddef.h>
#include <stdio.h>
#include <unistd.h>
#include <time.h>
#include <string.h>
#include <stdlib.h>

struct PMUData {
  double value;
} __attribute__((packed));

uint32_t pmuDataSize(void) {
  return sizeof(struct PMUData);
}

struct raplEndpoint {
  FILE *fEnergy;
  unsigned long long maxEnergy;
  unsigned long long lastEnergy;
  unsigned long long lastTime;
};

char const *raplPath = "/sys/class/powercap/intel-rapl:";


unsigned int endpoints;
struct raplEndpoint *raplEndpoints;

const char *pmuAbout(void) {
   return "RAPL SysFS PMU, reads energy values from sysfs";
}

int pmuInit(char *pmuArg) {
  if (pmuArg == NULL)
    goto pmu_no_arg;
  char filePath[1024];
  char *nEndpoint = strtok(pmuArg, ",");
  endpoints = 0;
  raplEndpoints = NULL;
  FILE *fd;

  while(nEndpoint) {
    if (raplEndpoints == NULL)
      raplEndpoints = malloc((endpoints + 1) * sizeof(struct raplEndpoint));
    else
      raplEndpoints = realloc(raplEndpoints, (endpoints + 1) * sizeof(struct raplEndpoint));
    if (raplEndpoints == NULL)
      goto pmu_init_error;

    snprintf(filePath, 1024, "%s%s/max_energy_range_uj", raplPath, nEndpoint);
    if (access(filePath, R_OK) == -1)
      goto pmu_arg_error;
    fd = fopen(filePath, "r");
    if (fd == NULL)
      goto pmu_arg_error;
    if (fscanf(fd, "%llu", &raplEndpoints[endpoints].maxEnergy) != 1)
      goto pmu_read_error;
    fclose(fd);
   
    snprintf(filePath, 1024, "%s%s/energy_uj", raplPath, nEndpoint);
    if (access(filePath, R_OK) == -1)
      goto pmu_arg_error;
    fd = fopen(filePath, "r");
    if (fd == NULL)
      goto pmu_arg_error;
    if (fscanf(fd, "%llu", &raplEndpoints[endpoints].lastEnergy) != 1)
      goto pmu_read_error;

    raplEndpoints[endpoints].fEnergy = fd;
    raplEndpoints[endpoints].lastTime = 0;
    endpoints++;
    nEndpoint = strtok(NULL, ",");
  }

  if (endpoints == 0)
    goto pmu_no_arg;


  struct PMUData dummy;
  pmuRead(&dummy);

  return 0;
 pmu_no_arg:
  fprintf(stderr, "PMU ERROR: invalid or no argument was passed\n");
  return 1;
 pmu_init_error:
  fprintf(stderr, "PMU ERROR: could init rapl pmu\n");
  return 1;
 pmu_read_error:
  fprintf(stderr, "PMU ERROR: could not read rapl endpoint '%s'\n", filePath);
  return 1;
 pmu_arg_error:
  fprintf(stderr, "PMU ERROR: rapl endpoint '%s' not found\n", filePath);
  return 1;
}

void pmuRead(struct PMUData *data) {
  unsigned long long energy;
  long long energyDiff;
  struct timespec currentTime;
  data->value = 0;
  clock_gettime(CLOCK_REALTIME, &currentTime);
  unsigned long long  time = (currentTime.tv_sec * 1000000) + (currentTime.tv_nsec / 1000);
  for (unsigned int i = 0; i < endpoints; i++) {
    if (freopen(NULL, "r", raplEndpoints[i].fEnergy) == NULL) {
      continue;
    }
    if (fscanf(raplEndpoints[i].fEnergy, "%llu", &energy) != 1) {
      continue;
    }

    if (energy < raplEndpoints[i].lastEnergy)
      energyDiff = (raplEndpoints[i].maxEnergy - raplEndpoints[i].lastEnergy) + energy;
    else
      energyDiff = energy - raplEndpoints[i].lastEnergy;

    data->value += (double) (energyDiff) / (time - raplEndpoints[i].lastTime);
    raplEndpoints[i].lastEnergy = energy;
    raplEndpoints[i].lastTime = time;
  }
}

enum PMU_WHAT pmuWhat(void) {
  return PMU_POWER;
}

int pmuRelease(void) {
  if (endpoints == 0)
    return 0;
  for (unsigned int i = 0; i < endpoints; i++) {
    fclose(raplEndpoints[i].fEnergy);
  }
  free(raplEndpoints);
  return 0;
}
