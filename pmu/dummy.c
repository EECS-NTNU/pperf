#include "pmu.h"


struct PMUData {
  double value;
} __attribute__((packed));

 const char *pmuAbout(void) {
   return "Dummy PMU, always reports 0.0 as PMU_POWER";
 }

int pmuInit(char *pmuArg) {
  (void) pmuArg;
  return 0;
}

void pmuRead(struct PMUData *data) {
  data->value = 0.0;
}

uint32_t pmuDataSize(void) {
  return sizeof(struct PMUData);
}

enum PMU_WHAT pmuWhat(void) {
  return PMU_POWER;
}

int pmuRelease(void) {
  return 0;
}
