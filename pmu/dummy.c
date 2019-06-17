#include "pmu.h"


 const char *pmuAbout(void) {
   return "Dummy PMU, always reports 1.0 as PMU_POWER";
 }

int pmuInit(char *pmuArg) {
  (void) pmuArg;
  return 0;
}

double pmuRead(void) {
  return 1.0;
}

enum PMU_WHAT pmuWhat(void) {
  return PMU_POWER;
}

int pmuRelease(void) {
  return 0;
}
