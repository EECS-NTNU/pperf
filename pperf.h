#ifndef __INTRUSIVEPROFILER_H_
#define __INTRUSIVEPROFILER_H_

#define _GNU_SOURCE


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
#include <spawn.h>
#include <getopt.h>
#include <sched.h>

#include <elf.h>
#include <sys/uio.h>
#include <sys/ptrace.h>
#include <sys/sysinfo.h>

#include <time.h>
#include <sys/time.h>

#include "pmu/pmu.h"
#include "vmmap.h"

#ifndef __riscv
// RISC-V does not expose user_regs_struc yet here
#include <sys/user.h>
#else
struct user_regs_struct {
	unsigned long pc;
	unsigned long ra;
	unsigned long sp;
	unsigned long gp;
	unsigned long tp;
	unsigned long t0;
	unsigned long t1;
	unsigned long t2;
	unsigned long s0;
	unsigned long s1;
	unsigned long a0;
	unsigned long a1;
	unsigned long a2;
	unsigned long a3;
	unsigned long a4;
	unsigned long a5;
	unsigned long a6;
	unsigned long a7;
	unsigned long s2;
	unsigned long s3;
	unsigned long s4;
	unsigned long s5;
	unsigned long s6;
	unsigned long s7;
	unsigned long s8;
	unsigned long s9;
	unsigned long s10;
	unsigned long s11;
	unsigned long t3;
	unsigned long t4;
	unsigned long t5;
	unsigned long t6;
};
#endif

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

struct timespec NanosecondsToTimespec(unsigned long long x) {
     struct timespec result = {
                               .tv_nsec = x % 1000000000,
                               .tv_sec = x / 1000000000
     };
     return result;
}

struct timespec MicrosecondsToTimespec(unsigned long long x) {
     struct timespec result = {
                               .tv_nsec = (x % 1000000) * 1000,
                               .tv_sec = x / 1000000
     };
     return result;
}

struct timespec MillisecondsToTimespec(unsigned long long x) {
     struct timespec result = {
                               .tv_nsec = (x % 1000) * 1000000,
                               .tv_sec = x / 1000
     };
     return result;
}

struct timespec SecondsToTimespec(unsigned long long x) {
     struct timespec result = {
                               .tv_nsec = 0,
                               .tv_sec = x
     };
     return result;
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
