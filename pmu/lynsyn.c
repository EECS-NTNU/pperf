/******************************************************************************
 *
 *  This file is part of the TULIPP Lynsyn Power Measurement Utilitity
 *
 *  Copyright 2018 Asbjørn Djupdal, NTNU, TULIPP EU Project
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program.  If not, see <http://www.gnu.org/licenses/>.
 *
 *****************************************************************************/
#include <argp.h>
#include <assert.h>
#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#include <lynsyn.h>
#include "pmu.h"

struct LynsynSample sample;

struct PMUData {
  double value;
} __attribute__((packed));

uint32_t pmuDataSize(void) {
  return sizeof(struct PMUData);
}

unsigned int selectedSensor = 0;


const char *pmuAbout(void) {
  return "Lynsyn v3 PMU, measures current in averaging mode";
}

int pmuInit(char *pmuArg) {
  if (pmuArg == NULL)
    goto pmu_arg_error;
  char *endPtr;
  long sensor = 0;
  sensor = strtol(pmuArg, &endPtr, 10);
  if ((endPtr == pmuArg) || (sensor < 1) || (sensor > LYNSYN_MAX_SENSORS))
    goto pmu_arg_error;
  selectedSensor = sensor - 1;

  if (!lynsyn_init())
    goto pmu_init_error;
  return 0;
pmu_arg_error:
  fprintf(stderr, "PMU ERROR: invalid pmu-arg, valid range 1 to %d \n", LYNSYN_MAX_SENSORS);
  return 1;
pmu_init_error:
  fprintf(stderr, "PMU ERROR: could not initialize lynsyn v3 board\n");
  return 1;
}


void pmuRead(struct PMUData *data) {
  if (!lynsyn_getSample(&sample, true, 0)) {
    data->value = 0.0;
  } else {
    data->value = sample.current[selectedSensor] * sample.voltage[selectedSensor];
  }
}

enum PMU_WHAT pmuWhat(void) {
  return PMU_POWER;
}

int pmuRelease(void) {
  lynsyn_release();
  return 0;
}
