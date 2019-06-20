#ifndef __INTRUSIVEPROFILER_H_
#define __INTRUSIVEPROFILER_H_

#include <stdio.h>
#include <signal.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <unistd.h>
#include <string.h>
#include <errno.h>
#include <sys/wait.h>
#include <sys/types.h>
#include <sys/user.h>
#include <spawn.h>
#include <getopt.h>
#include <sched.h>

#include <elf.h>
#include <sys/uio.h>
#include <sys/ptrace.h>

#include <time.h>
#include <sys/time.h>

#include "pmu/pmu.h"
#include "vmmap.h"

// Some helper functions to handle time, timespec and frequencies more easily

void timespecAdd(struct timespec *result, struct timespec *x, struct timespec *y) {
    result->tv_sec = x->tv_sec + y->tv_sec;
    result->tv_nsec = x->tv_nsec;
    if (x->tv_nsec + y->tv_nsec > 1000000000) {
        result->tv_sec++;
        result->tv_nsec -= 1000000000;
    }
    result->tv_nsec += y->tv_nsec;
}

void timespecAddStore(struct timespec *result, struct timespec *x) {
    result->tv_sec = result->tv_sec + x->tv_sec;
    if (result->tv_nsec + x->tv_nsec > 1000000000) {
        result->tv_sec++;
        result->tv_nsec -= 1000000000;
    }
    result->tv_nsec += x->tv_nsec;
}

void timespecSub (struct timespec *result, struct timespec *x, struct timespec *y) {
  if (x->tv_nsec < y->tv_nsec) {
    int nsec = (y->tv_nsec - x->tv_nsec) / 1000000000 + 1;
    y->tv_nsec -= 1000000000 * nsec;
    y->tv_sec += nsec;
  }
  if (x->tv_nsec - y->tv_nsec > 1000000000) {
    int nsec = (x->tv_nsec - y->tv_nsec) / 1000000000;
    y->tv_nsec += 1000000000 * nsec;
    y->tv_sec -= nsec;
  }
  result->tv_sec = x->tv_sec - y->tv_sec;
  result->tv_nsec = x->tv_nsec - y->tv_nsec;
}

void timespecSubStore (struct timespec *result, struct timespec *x) {
  if (result->tv_nsec < x->tv_nsec) {
    int nsec = (x->tv_nsec - result->tv_nsec) / 1000000000 + 1;
    x->tv_nsec -= 1000000000 * nsec;
    x->tv_sec += nsec;
  }
  if (result->tv_nsec - x->tv_nsec > 1000000000) {
    int nsec = (result->tv_nsec - x->tv_nsec) / 1000000000;
    x->tv_nsec += 1000000000 * nsec;
    x->tv_sec -= nsec;
  }
  result->tv_sec -= x->tv_sec;
  result->tv_nsec -= x->tv_nsec;
}


struct timespec tsSub(struct timespec x, struct timespec y) {
    struct timespec result;
    timespecSub(&result, &x, &y);
    return result;
}

struct timespec tsAdd(struct timespec x, struct timespec y) {
    struct timespec result;
    timespecAdd(&result, &x, &y);
    return result;
}

unsigned long long timespecToNanoseconds(struct timespec *t) {
    if ((t->tv_sec < 0) || ((t->tv_sec ==0) && (t->tv_nsec < 0)))
       return 0;
    return (t->tv_sec * 1000000000) + t->tv_nsec;
}

unsigned long long timespecToMicroseconds(struct timespec *t) {
    return timespecToNanoseconds(t) / 1000;
}

unsigned long long timepsecToMilliseconds(struct timespec *t) {
    return timespecToMicroseconds(t) / 1000;
}

unsigned long long timespecToSeconds(struct timespec *t) {
    return t->tv_sec;
}

void frequencyToTimespec(struct timespec *t, double freq) {
    if (freq == 0.0) {
        t->tv_sec = 0;
        t->tv_nsec = 0;
    } else {
        t->tv_sec = (time_t) (1.0 / freq);
        t->tv_nsec = ((long) (1000000000.0 / freq)) % 1000000000L;
    }
}

#endif // __INTRUSIVEPROFILER_H_
