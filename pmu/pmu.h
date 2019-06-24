#ifndef __PMU_H_
#define __PMU_H_

#include <stdint.h>

/* PMU Data Structure */
struct PMUData; //__attribute__((packed));

enum PMU_WHAT { PMU_CUSTOM = 0, PMU_CURRENT, PMU_VOLTAGE, PMU_POWER };

/*
  Short PMU Description
 */
const char *pmuAbout(void);

/*
  Will be called once before sampling Process
  @Return: 0 on success, 1 on error
 */
int pmuInit(char *pmuArg);

/*
  Read out PMU value
 */
void pmuRead(struct PMUData *data);

/*
  returns size of PMUData struct
 */
uint32_t pmuDataSize(void);

/*
  What does the PMU module read, will be the magic number of th resulting binary profile
 */
enum PMU_WHAT pmuWhat(void);

/*
  Will be called once after sampling or on error
 */
int pmuRelease(void);

#endif // __PMU_H_
