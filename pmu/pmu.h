#ifndef __PMU_H_
#define __PMU_H_

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
double pmuRead(void);

/*
  What does the PMU module read, will be the magic number of th resulting binary profile
 */
enum PMU_WHAT pmuWhat(void);

/*
  Will be called once after sampling or on error
 */
int pmuRelease(void);

#endif // __PMU_H_
