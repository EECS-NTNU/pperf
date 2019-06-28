#include "intrusiveProfiler.h"

//#define ESTIMATE_LATENCY
//#define PC_ONLY


#ifdef DEBUG
#define debug_printf(...) fprintf(stderr, __VA_ARGS__);
#else
#define debug_printf(...)
#endif

#if !defined(__amd64__) && !defined(__aarch64__)
#error "Architecture not supported!"
#endif

#define PTRACE_WAIT(target, status) do { \
    do { \
        target = waitpid(-1, &status, __WALL);   \
    } while(target == -1 && errno == EAGAIN)

#define PTRACE_OTHER_CONTINUE(target, signal) do { \
        _ptrace_return = ptrace(PTRACE_CONT, target, NULL, signal); \
    } while (_ptrace_return == -1L && (errno == EBUSY || errno == EFAULT || errno == ESRCH)) 

#define PTRACE_CONTINUE(target, signal) \
        _ptrace_return = ptrace(PTRACE_CONT, target, NULL, signal) 


unsigned int getOnlineCPUIds(unsigned int **onlineCPUs) {
    char *buf = NULL;
    size_t n = 0;
    unsigned int c = 0;
    unsigned int id = 0;
    FILE *fd = fopen("/proc/cpuinfo","r");
    if (fd == NULL)
        return 0;
    while (getline(&buf, &n, fd) != -1) {
        if (strstr(buf, "processor") == buf) {
            if (sscanf(buf, "processor%s%u", buf, &id) == 2) {
                if (*onlineCPUs == NULL) {
                    *onlineCPUs = malloc(c * sizeof(unsigned int));
                } else {
                    *onlineCPUs = realloc(*onlineCPUs, c * sizeof(unsigned int));
                }
                if (*onlineCPUs == NULL) {
                    return 0;
                }
                (*onlineCPUs)[c++] = id;
            }
        }
    }
    if (buf != NULL) {
        free(buf);
    }
    return c;
}

struct task {
    uint32_t tid;
    uint64_t pc;
    uint64_t cputime;
} __attribute__((packed));

int getCPUTimeFromSchedstat(FILE *schedstat, uint64_t *cputime) {
#ifdef PC_ONLY
    return 0;
#endif
    if (freopen(NULL, "r", schedstat) == NULL)
        return 1;
    if (fscanf(schedstat, "%lu", cputime) == 1)
        return 0;
    return 1;
}

struct taskList {
    pid_t root;
    uint32_t count;
    uint32_t allocCount;
    struct task *list;
    FILE **schedstats;
};

struct taskList tasks = {};

int addTask(pid_t const task) {
    static char schedfile[1024] = {};
    if (tasks.allocCount == 0) {
        tasks.count = 0;
        tasks.allocCount = 1;
        tasks.list = (struct task *) malloc(sizeof(struct task));
        tasks.schedstats = (FILE **) malloc(sizeof(FILE *));
        if (tasks.list == NULL || tasks.schedstats == NULL)
            return 1;
    } else if (tasks.count == tasks.allocCount) {
        tasks.allocCount *= 2;
        tasks.list = (struct task *) realloc(tasks.list, tasks.allocCount * sizeof(struct task));
        tasks.schedstats = (FILE **) realloc(tasks.schedstats, tasks.allocCount * sizeof(FILE *));
        if (tasks.list == NULL || tasks.schedstats == NULL)
            return 1;
    }
    snprintf(schedfile, 1024, "/proc/%d/task/%d/schedstat", tasks.root, task);
    tasks.schedstats[tasks.count] = fopen(schedfile, "r");
    if (tasks.schedstats[tasks.count] == NULL) {
        debug_printf("[DEBUG] Could not open %s\n", schedfile);
        return 1;
    }
    tasks.list[tasks.count].tid = task;
    tasks.list[tasks.count].pc = 0;
    tasks.count++;
    return 0;
}

int removeTaskIndex(uint32_t const i) {
    if (i < tasks.count) {
        tasks.count--;
        fclose(tasks.schedstats[i]);
        for (unsigned int j = i; j < tasks.count; j++) {
            tasks.list[j].tid = tasks.list[j+1].tid;
            tasks.schedstats[j] = tasks.schedstats[j+1];
        }
        return 0;
    }
    return 1;
}

int removeTask(pid_t const task) {
    for (unsigned int i = 0; i < tasks.count; i++) {
        if ((pid_t) tasks.list[i].tid == task) {
            tasks.count--;
            fclose(tasks.schedstats[i]);
            for (unsigned int j = i; j < tasks.count; j++) {
                tasks.list[j].tid = tasks.list[j+1].tid;
                tasks.schedstats[j] = tasks.schedstats[j+1];
            }
            return 0;
        }
    }
    return 1;
}

int taskExists(pid_t const task) {
    for (unsigned int i = 0; i < tasks.count; i++) {
        if ((pid_t) tasks.list[i].tid == task)
            return 1;
    }
    return 0;
}

struct task *getTask(pid_t const task) {
    for (unsigned int i = 0; i < tasks.count; i++) {
        if ((pid_t) tasks.list[i].tid == task)
            return &tasks.list[i];
    }
    return NULL;
}

void help(char const *exec, char const opt, char const *optarg) {
    FILE *out = stdout;
    if (opt != 0) {
        out = stderr;
        if (optarg) {
            fprintf(out, "Invalid parameter - %c %s\n", opt, optarg);
        } else {
            fprintf(out, "Invalid parameter - %c\n", opt);
        }
    }
    fprintf(out, "%s [options] -- <command> [arguments]\n", exec);
    fprintf(out, "\n");
    fprintf(out, "Compiled with PMU\n");
    fprintf(out, "%s\n", pmuAbout());
    fprintf(out, "\n");
    fprintf(out, "Options:\n");
    fprintf(out, "  -o, --output <file>       write to file\n");
    fprintf(out, "  -p, --pmu-arg <pmu>       pmu argument\n");
    fprintf(out, "  -f, --frequency <hertz>   sampling frequency\n");
    fprintf(out, "  -r, --randomize           randomize start sample\n");
    fprintf(out, "  --core-isolation          sample on isolated core\n");
    fprintf(out, "  --fifo <priority>         set fifo scheduler with priority\n");
    fprintf(out, "  --rr <priority>           set rr scheduler with priority\n");
    fprintf(out, "  -v, --verbose             verbsoe output at the end\n");
    fprintf(out, "  -h, --help                shows help\n");
    fprintf(out, "\n");
    fprintf(out, "Example: %s -o /tmp/map -f 1000 -v -- sleep 10\n", exec);
}


struct timerData {
    int               active; 
    timer_t           timer;
    struct itimerspec time;
    struct timespec   samplingInterval;
    struct sigaction  signalOldAction;
    struct sigaction  signalAction;
};

struct callbackData {
    pid_t tid;
    struct timespec lastInterrupt;
};

static struct callbackData _callback_data;

#define TRACEE_INTERRUPT_SIGNAL SIGUSR2

void timerCallback(int sig) {
    (void) sig;
    int r;
    do {
        r = kill(_callback_data.tid, TRACEE_INTERRUPT_SIGNAL);
    } while (r == -1 && errno == EAGAIN);
    debug_printf("[%d] send %d\n", _callback_data.tid, TRACEE_INTERRUPT_SIGNAL);
    clock_gettime(CLOCK_REALTIME, &_callback_data.lastInterrupt);
}

int pauseTimer(struct timerData *timer) {
    if (timer->active == 0)
        return 0;
    
    timer->time.it_value.tv_sec = 0;
    timer->time.it_value.tv_nsec = 0;
    
    debug_printf("[DEBUG] timer paused\n");
    
    if (timer_settime(timer->timer, 0, &timer->time, NULL) != 0)
        return 1;
    return 0;
}
    
int scheduleInterruptNow(struct timerData *timer) {
    if (timer->active == 0)
        return 0;
    
    timer->time.it_value.tv_sec = 0;
    timer->time.it_value.tv_nsec = 1;

    debug_printf("[DEBUG] next timer now\n");

    if (timer_settime(timer->timer, 0, &timer->time, NULL) != 0)
        return 1;
    return 0;
}

int scheduleInterruptIn(struct timerData *timer, struct timespec interrupt) {
    if (timer->active == 0)
        return 0;

    timer->time.it_value.tv_nsec = interrupt.tv_nsec;
    timer->time.it_value.tv_sec = interrupt.tv_sec;
    debug_printf("[DEBUG] next timer in %llu us\n", timespecToMicroseconds(&timer->time.it_value));

    if (timespecToNanoseconds(&timer->time.it_value) == 0)
        return scheduleInterruptNow(timer);

    if (timer_settime(timer->timer, 0, &timer->time, NULL) != 0)
        return 1;
    return 0;
}

int scheduleNextInterrupt(struct timerData *timer) {
    static struct timespec nextPlannedInterrupt;
    static struct timespec currentTime;
    if (timer->active == 0) 
        return 0;
    
    clock_gettime(CLOCK_REALTIME, &currentTime);
    timespecAdd(&nextPlannedInterrupt, &_callback_data.lastInterrupt, &timer->samplingInterval);
    timespecSub(&timer->time.it_value, &nextPlannedInterrupt, &currentTime);
    debug_printf("[DEBUG] next timer in %llu ns\n", timespecToNanoseconds(&timer->time.it_value));

    if (timespecToNanoseconds(&timer->time.it_value) == 0)
        return scheduleInterruptNow(timer);
    
    if (timer_settime(timer->timer, 0, &timer->time, NULL) != 0)
        return 1;
    return 0;
}

int startTimer(struct timerData *timer) {
    //If sampling interval is 0, no need for a timer
    if (timer->samplingInterval.tv_sec == 0 && timer->samplingInterval.tv_nsec == 0)
        return 0;
    
    //If already active, abort
    if (timer->active)
        goto start_error;

    //Setup SIGNAL action
    if (sigfillset(&timer->signalAction.sa_mask) != 0)
        goto start_error;
    timer->signalAction.sa_flags = SA_RESTART;
    timer->signalAction.sa_handler = &timerCallback;
    
    if (sigaction(SIGALRM, &timer->signalAction, &timer->signalOldAction) != 0)
        goto start_error;
    if (timer_create(CLOCK_REALTIME, NULL, &timer->timer) != 0)
        goto start_error;
    
    timer->active = 1;
    return 0;
start_error:
    return -1;
    
}

int stopTimer(struct timerData *timer) {
    if (timer->active == 0)
        return 0;
    if (timer_delete(timer->timer) != 0)
        goto stop_error;
    if (sigaction(SIGALRM, &timer->signalOldAction, NULL) != 0)
        goto stop_error;

    timer->active = 0;
    return 0;
 stop_error:
    return -1;
}

int main(int const argc, char **argv) {
    FILE *output = NULL;
    char **argsStart = NULL;
    char *pmuArg = NULL;
    bool verboseOutput = 0;
    bool coreIsolation = 0;
    bool randomize = 0;
    unsigned int *onlineCPUs = NULL;
    unsigned int nCPUs = 0;
    double samplingFrequency = 1000;
    int rr = 0;
    int fifo = 0;
    
    static struct option const long_options[] =  {
        {"help",           no_argument,       0, 'h'},
        {"verbose",        no_argument,       0, 'v'},
        {"randomize",      no_argument,       0, 'r'},
        {"core-isolation", no_argument,       0, 'i'},
        {"pmu-arg",        required_argument, 0, 'p'},
        {"fifo",           required_argument, 0, 'x'},
        {"rr",             required_argument, 0, 'y'},
        {"frequency",      required_argument, 0, 'f'},
        {"output",         required_argument, 0, 'o'},
        {0, 0, 0, 0}
    };

    static char const * short_options = "hvf:o:p:r";

    while (1) {
        char *endptr;
        int c;
        int option_index = 0;
        size_t len = 0;
        unsigned int aLen;

        c = getopt_long (argc, argv, short_options, long_options, &option_index);
        if (c == -1) {
            break;
        }

        switch (c) {
        case 0:
            break;
        case 'h':
            help(argv[0],0, NULL);
            return 0;
        case 'p':
            aLen = strlen(optarg);
            pmuArg = malloc((aLen + 1) * sizeof(char));
            memset(pmuArg, '\0', aLen + 1);
            strncpy(pmuArg, optarg, aLen);
            break;
        case 'x':
            fifo = strtol(optarg, &endptr, 10);
            if (endptr == optarg || fifo < 1 || fifo > 99) {
                help(argv[0], c, optarg);
                return 1;
            }
            break;
        case 'y':
            rr = strtol(optarg, &endptr, 10);
            if (endptr == optarg || rr < 1 || rr > 99) {
                help(argv[0], c, optarg);
                return 1;
            }
            break;
        case 'f':
            samplingFrequency = strtod(optarg, &endptr);
            if (endptr == optarg) {
                help(argv[0], c, optarg);
                return 1;
            }

            break;
        case 'o':
            len = strlen(optarg);
            if (strlen(optarg) == 0) {
                help(argv[0], c ,optarg);
                return 1;
            }
            output = fopen(optarg, "w+");
            if (output == NULL) {
                help(argv[0], c, optarg);
                return 1;
            }
            break;
        case 'r':
            randomize = true;
            break;
        case 'i':
            coreIsolation = true;
            break;
        case 'v':
            verboseOutput = true;
            break;
        default:
            abort();
        }
    }


    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0 && (i + 1) < argc) {
            argsStart = &argv[i + 1];
        }
    }

    if (argsStart == NULL) {
        help(argv[0], ' ', "no command specified");
        return 1;
    }

    if (rr != 0)
        fifo = 0;

    int prio = rr + fifo;
    struct sched_param param = {};
    int useSched = SCHED_RR;
    param.sched_priority = prio;
    if (fifo != 0) {
        useSched = SCHED_FIFO;
    }

    int ret = 0; // this application return code
    long rp = 0; // ptrace return code

    //Init PMU
    if (pmuInit(pmuArg) != 0) {
        goto pmuError;
    }
    if (pmuArg != NULL) {
        free(pmuArg);
    }

    pid_t samplingTarget = 0;
    pid_t intrTarget = 0;
    int intrStatus = 0;
    struct VMMaps processMap = {};

    //Set scheduler if one was chosen
    if (prio != 0) {
        if (sched_setscheduler(0, useSched, &param) != 0) {
            fprintf(stderr, "ERROR: (%d) could not set scheduler %d with priority %d\n", errno, useSched, prio);
            ret = 1; goto exit;
        }
    }
    //Core isolation feature
    if (coreIsolation) {
       nCPUs = getOnlineCPUIds(&onlineCPUs);
       if (nCPUs == 1 && verboseOutput) {
           fprintf(stdout, "[VERBOSE] CPU isolation does not work on a single core system\n");
       }
       if (nCPUs > 0) {
           cpu_set_t  mask;
           CPU_ZERO(&mask);
           CPU_SET(onlineCPUs[nCPUs -1], &mask);
           if (sched_setaffinity(0, sizeof(mask), &mask) == -1) {
               fprintf(stderr, "ERROR: could not set cpu mask for sampler\n");
               ret = 1; goto exit;
           }
       } else {
           fprintf(stderr, "ERROR: no online cpu cores were detected\n");
           ret = 1; goto exit;
       }
    }

    //Fork Process
    do {
        samplingTarget = fork();
    } while (samplingTarget == -1 && errno == EAGAIN);

    if (samplingTarget == -1) {
        fprintf(stderr, "ERROR: could not fork!\n");
        ret = 1; goto exit;
    }

    //Enable PTRACE of forked process and replace it with target application
    if (samplingTarget == 0) {
        //Set scheduler for sampling target
        if (prio != 0) {
            if (sched_setscheduler(0, useSched, &param) != 0) {
                fprintf(stderr, "ERROR: (%d) could not set scheduler %d with priority %d\n", errno, useSched, prio);
                return 1;
            }
        }
        //Core isolation feature
        if (coreIsolation) {
            if (nCPUs > 1) {
                cpu_set_t  mask;
                CPU_ZERO(&mask);
                for (long i = 0; i < nCPUs - 1; i++) {
                    CPU_SET(onlineCPUs[i], &mask);
                }
                if (sched_setaffinity(0, sizeof(mask), &mask) == -1) {
                    fprintf(stderr, "ERROR: could not set cpu mask for target\n");
                    return 1;
                }
            }
        }

        if (ptrace(PTRACE_TRACEME, NULL, NULL, NULL) == -1) {
            fprintf(stderr,"ERROR: ptrace traceme failed!\n");
            return 1;
        }
        if (execvp(argsStart[0], argsStart) != 0) {
            fprintf(stderr, "ERROR: failed to execute");
            for (unsigned int i = 0; argsStart[i] != NULL; i++) {
                fprintf(stderr, " %s", argsStart[i]);
            }
            fprintf(stderr,"\n");
            return 1;
        }
    }

    //Saving the sampling target as root process
    tasks.root = samplingTarget;

    //PTRACE sends SIGTRACE to a newly ptraced process (in this case our target),
    //which we are waiting for
    do {
        intrTarget = waitpid(samplingTarget, &intrStatus, __WALL);
    } while (intrTarget == -1 && errno == EINTR);

    //If something went wrong, break here
    if (WIFEXITED(intrStatus)) {
        fprintf(stderr,"ERROR: unexpected process termination\n");
        ret = 2; goto exit;
    }

    //The PID of the target must matched with that one which we waited for
    if (samplingTarget != intrTarget) {
        fprintf(stderr, "ERROR: unexpected pid stopped\n");
        ret = 2; goto exitWithTarget;
    }

    //Set PTRACE options to trace thread creation, target kills and exits
    if (ptrace(PTRACE_SETOPTIONS, samplingTarget, NULL, PTRACE_O_TRACECLONE | PTRACE_O_TRACEEXIT | PTRACE_O_EXITKILL) == -1) {
        fprintf(stderr, "ERROR: Could not set ptrace options!\n");
        ret = 1; goto exitWithTarget;
    }

    //Check if we can read the process virtual memory maps
    struct VMMaps targetMap = {};
    targetMap = getProcessVMMaps(samplingTarget, 1);
    if (targetMap.count == 0) {
       fprintf(stderr, "ERROR: could not detect process vmmap\n");
       ret = 1; goto exitWithTarget;
    }
   
#ifdef DEBUG
    for (unsigned int i = 0; i < targetMap.count; i ++) {
        printf("[DEBUG] VMMap %u: 0x%014lx, 0x%014lx, %s\n", i, targetMap.maps[i].addr, targetMap.maps[i].size, targetMap.maps[i].label);
    }
#endif

    //Leave space for the profile header
    if (output != NULL) {
        // Leave place for Magic Number, Wall Time, Latency Time, Samples, PMU Data Size, VMMap Count
        fseek(output, 3 * sizeof(uint32_t) + 3 * sizeof(uint64_t), SEEK_SET);
    }

    //Necessary structs for reading out the programm counter
    static struct user_regs_struct regs = {};
    static struct iovec rvec = { .iov_base = &regs, .iov_len = sizeof(regs) };

    //Setting the target pid for the timer callback to send signals to
    _callback_data.tid = samplingTarget;
    //Add the target in our task structure, which will keep track of it and its threads
    if (addTask(samplingTarget)) {
        fprintf(stderr, "ERROR: could not add %d internal task structure\n", samplingTarget);
        ret = 1; goto exitWithTarget;
    }


    //statistics
    uint64_t samples = 0;
    uint64_t interrupts = 0;
    //timer data
    struct timerData timer = {};
    struct timespec timeDiff = {};
    struct timespec currentTime = {};

    frequencyToTimespec(&timer.samplingInterval, samplingFrequency);

    struct timespec samplerStartTime = {};
    clock_gettime(CLOCK_REALTIME, &samplerStartTime);

#ifndef ESTIMATE_LATENCY
    struct timespec latencyStartTime = {};
    struct timespec totalLatencyWallTime = {};
#else
    clock_t latencyCpuStartTime = clock();
#endif
    struct timespec sampleWallTime = {};

    uint32_t const sizePMUData = pmuDataSize();
    struct PMUData *samplePMUData = malloc(sizePMUData);
    pmuRead(samplePMUData);

    uint64_t sampleTime = 0;
   
    if (startTimer(&timer) != 0) {
        fprintf(stderr, "ERROR: could not start sampling timer\n");
        ret = 1; goto exitWithTarget;
    }

    // first sample as soon as possible
    if (randomize) {
        srandom(time(NULL));
        scheduleInterruptIn(&timer, NanosecondsToTimespec(timespecToNanoseconds(&timer.samplingInterval) * ((double) random() / RAND_MAX)));
    } else {
        scheduleInterruptNow(&timer);
    }

    long r;
    do {
        r = ptrace(PTRACE_CONT, samplingTarget, NULL, NULL);
    } while (r == -1L && (errno == EBUSY || errno == EFAULT || errno == ESRCH));

    do {
        bool groupStop = false;
        unsigned int stopCount = 0;

        
        while(tasks.count > 0) {
            int status;
            int signal;
            pid_t intrTarget;
            do {
                intrTarget = waitpid(-1, &status, __WALL);
            } while (intrTarget == -1 && errno == EAGAIN);
            //pauseTimer(&timer);
            
                                              
            if (WIFEXITED(status)) {
                if (tasks.count == 1 || intrTarget == samplingTarget) {
                    debug_printf("[%d] root tracee died\n", intrTarget);
                    goto exitSampler;
                } else {
                    if (removeTask(intrTarget)) {
                        fprintf(stderr, "ERROR: could not remove task %d from internal structure\n", intrTarget);
                        ret = 1; goto exitWithTarget;
                    }
                    debug_printf("[%d] tracee died\n", intrTarget);
                    if (groupStop && stopCount >= tasks.count) {
                        // We waited for this thread to stop
                        // but it died, so grab that sample
                        break;
                    } 
                    continue;
               }
            }

            if (!WIFSTOPPED(status)) {
                fprintf(stderr, "unexpected process state of tid %d\n", intrTarget);
                ret = 1; goto exitWithTarget;
            }

            signal = WSTOPSIG(status);

            if (signal == TRACEE_INTERRUPT_SIGNAL && !groupStop) {
                debug_printf("[%d] initiate group stop\n", intrTarget);
                signal = SIGSTOP;
                groupStop = true;
                stopCount = 0;
#ifndef ESTIMATE_LATENCY
                clock_gettime(CLOCK_REALTIME, &latencyStartTime);
#endif

            } else if (signal == SIGSTOP) {
                signal = 0;
                if (!taskExists(intrTarget)) {
                    debug_printf("[%d] new child detected\n", intrTarget);
                    if (addTask(intrTarget)) {
                        fprintf(stderr, "ERROR: could not add task %d to internal structure\n", intrTarget);
                        ret = 1; goto exitWithTarget;
                    }
                }
                if (groupStop) {
                    debug_printf("[%d] group stop\n", intrTarget);
                    if (++stopCount == tasks.count) {
                        break;
                    } else {
                        continue;
                    }
                }
            } else {
                if (intrTarget == samplingTarget && signal == SIGTRAP && (status >> 16) == PTRACE_EVENT_EXIT) {
                    signal = 0;
                    processMap = getProcessVMMaps(intrTarget, 0);
                    debug_printf("[%d] exit traced of root target\n", intrTarget)
                } else if (signal == SIGTRAP && (status >> 16) == PTRACE_EVENT_CLONE) {
                    signal = 0;
               } else {
                    debug_printf("[%d] untraced signal %d\n", intrTarget, signal);
                    interrupts++;
                }
            }
            
            rp = ptrace(PTRACE_CONT, intrTarget, NULL, signal);
            if (rp == -1 && errno == ESRCH) {
                debug_printf("[%d] death on ptrace cont\n", intrTarget);
                if (removeTask(intrTarget)) {
                    fprintf(stderr, "ERROR: could not remove task %d from internal structure\n", intrTarget);
                    ret = 1; goto exitWithTarget;
                }
            } else {
                debug_printf("[%d] continued with signal %d\n", intrTarget, signal);
            }
            
        }
        clock_gettime(CLOCK_REALTIME, &sampleWallTime);
#ifndef PC_ONLY
        pmuRead(samplePMUData);
        debug_printf("[sample] PMU Data Read\n");
#endif

        unsigned int i = 0;
        while (i < tasks.count) {
            rp = ptrace(PTRACE_GETREGSET, tasks.list[i].tid, NT_PRSTATUS, &rvec);
            //rp = ptrace(PTRACE_GETREGS, tasks.list[i].tid, NULL, &regs);
            if (rp == -1 && errno == ESRCH) {
                debug_printf("[%d] death on ptrace regs\n", tasks.list[i].tid);
                if (removeTaskIndex(i)) {
                    fprintf(stderr, "ERROR: could not remove task %d from internal structure\n", tasks.list[i].tid);
                    ret = 1; goto exitWithTarget;
                }
                continue;
            }
#ifdef __aarch64__
            tasks.list[i].pc = regs.pc;
#else
            tasks.list[i].pc = regs.rip;
#endif
            if (getCPUTimeFromSchedstat(tasks.schedstats[i], &tasks.list[i].cputime)) {
                fprintf(stderr, "ERROR: could not read cputime of tid %d\n", tasks.list[i].tid);
                ret = 1; goto exitWithTarget;
            }
            debug_printf("[%d] pc: 0x%lx, cputime: %lu\n", tasks.list[i].tid, tasks.list[i].pc, tasks.list[i].cputime);
            i++;
        }

        if (output != NULL ) {
            sampleTime = timespecToMicroseconds(&sampleWallTime);
            fwrite((void *) &sampleTime, sizeof(uint64_t), 1, output);
            fwrite((void *) samplePMUData, sizePMUData, 1, output);
            fwrite((void *) &tasks.count, sizeof(uint32_t), 1, output);
            fwrite((void *) tasks.list, sizeof(struct task), tasks.count, output);
        }
       
        samples++;
        groupStop = false;
        
        scheduleNextInterrupt(&timer);

#ifndef ESTIMATE_LATENCY
        clock_gettime(CLOCK_REALTIME, &currentTime);
        timespecSub(&timeDiff, &currentTime, &latencyStartTime);
        timespecAddStore(&totalLatencyWallTime, &timeDiff);
#endif
        i = 0;
        while(i < tasks.count) {
            rp = ptrace(PTRACE_CONT, tasks.list[i].tid, NULL, NULL);
            if (rp == -1 && errno == ESRCH) {
                debug_printf("[%d] death on ptrace cont after sample\n", tasks.list[i].tid);
                if (removeTaskIndex(i)) {
                    fprintf(stderr, "ERROR: could not remove task %d from internal structure\n", tasks.list[i].tid);
                    ret = 1; goto exitWithTarget;
                }
            }
            i++;
        }
     } while(tasks.count > 0);

 exitSampler: ; 
#ifndef ESTIMATE_LATENCY
    uint64_t totalWallLatencyUs = timespecToMicroseconds(&totalLatencyWallTime);
#else
    uint64_t totalWallLatencyUs = (clock() - latencyCpuStartTime) * 1000000 / CLOCKS_PER_SEC;
#endif

    clock_gettime(CLOCK_REALTIME, &currentTime);
    timespecSub(&timeDiff, &currentTime, &samplerStartTime);
    uint64_t totalWallTimeUs = timespecToMicroseconds(&timeDiff);
    
    if (stopTimer(&timer) != 0) {
        fprintf(stderr, "Could not stop sampling timer\n");
        ret = 1; goto exit;
    }

    if (processMap.count == 0) {
        fprintf(stderr, "No process map was read, process exit was not reported!\n");
        ret = 1; goto exit;
    }

    if (output != NULL) {
        //Write VMMap
        fwrite((void *) processMap.maps, sizeof(struct VMMap), processMap.count, output);
        //HEADER
        uint32_t const magic = (uint32_t) pmuWhat();
        fseek(output, 0, SEEK_SET);
        fwrite((void *) &magic, sizeof(uint32_t), 1, output);
        fwrite((void *) &totalWallTimeUs, sizeof(uint64_t), 1, output);
        fwrite((void *) &totalWallLatencyUs, sizeof(uint64_t), 1, output);
        fwrite((void *) &samples, sizeof(uint64_t), 1, output);
        fwrite((void *) &sizePMUData, sizeof(uint32_t), 1, output);
        fwrite((void *) &processMap.count, sizeof(uint32_t), 1, output);
    }

    if (verboseOutput) {
        printf("[VERBOSE] time       : %10lu us (ideal), %10lu us (actual)\n", totalWallTimeUs - totalWallLatencyUs, totalWallTimeUs);
        printf("[VERBOSE] interrupts : %10lu    (total), %10lu    (foreign) \n", interrupts + samples, interrupts );
        printf("[VERBOSE] samples    : %10llu    (ideal), %10lu    (actual)  \n", (timespecToMicroseconds(&timer.samplingInterval) > 0) ? totalWallTimeUs / timespecToMicroseconds(&timer.samplingInterval) : 0, samples);
        printf("[VERBOSE] latency    : %10lu us (total), %10lu us (sample)\n", totalWallLatencyUs, (samples > 0) ? totalWallLatencyUs / samples : 0);
        printf("[VERBOSE] frequency  : %10.2f Hz (ideal), %10.2f Hz (actual)\n", samplingFrequency, (samples > 0) ? 1000000.0 / ((double) totalWallTimeUs / samples) : 0);
    }
    ret = 0; goto exit;

exitWithTarget:
    kill(samplingTarget, SIGKILL);
    ptrace(PTRACE_DETACH, samplingTarget, NULL, NULL, NULL);
exit:
    pmuRelease();
pmuError:
    if (output != NULL) {
        fclose(output);
    }
    return ret;
}
