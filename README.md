# PPerf - Intrusive ELF Profiler

```text
sampler [options] -- <command> [arguments]

Options:
  -o, --output=<file>       write to file
  -p, --pmu-arg=<arg>       pmu argument
  -f, --frequency=<hertz>   sampling frequency
  -d, --debug               output sampling informations at the end
  -h, --help                shows help
```

* profiling any ELF file on Linux, without any instrumentation or required
  privileges
* offline analyzing, aggregating, comparing and visualizing of created profiles
* sampling of internal or external PMU data (e.g. energy profiling with external
  equipment or rapl)
* every sample contains the wall time, PMU data and the TID, PC and CPU time for
  every thread of the application
* uses ptrace group-stops to synchronously sample all threads in a application
* all profiles contain execution time (wall), time spent in profiler (latency,
  estimation), number of samples and the target virtual memory map
* output file is optional, if not specified no IO is generated
* frequency is a target, actual reached frequency is displayed in verbose output
* threads are fully supported, **though fork, vfork and vclone is not
  supported**!
* execl, execlp, execle, execv, execvp and execvpe are replacing the current
  process with new VMMaps and are therefore not supported!
  

## Binary Profile Description

* Included in every profile
* Magic number defines profile pmu data 
  * 0 - custom
  * 1 - current
  * 2 - voltage (not supported by python scripts)
  * 3 - power

```
[ 4 bytes / uint32_t ] Magic Number
[ 8 bytes / uint64_t ] Total Wall Time
[ 8 bytes / uint64_t ] CPU Time of Sampler (latency)
[ 8 bytes / uint64_t ] Number of Samples
[ 4 bytes / uint32_t ] PMU Sample Size in bytes
[ 4 bytes / uint32_t ] Number of VMMaps

Sample{
    [ 8 bytes / uint64_t ] Wall Time (ms)
    [ x bytes / x        ] PMU Value (defined by sampler)
    [ 4 bytes / uint32_t ] Number of Threads
    Thread{
        [ 4 bytes / uint32_t ] Thread ID
        [ 8 bytes / uint64_t ] PC
        [ 8 bytes / uint64_t ] CPU Time (ns)
    } // Repeated "Number of Threads" times
} // Repeated "Number of Samples" times

VMMap{
    [ 8 bytes / uint64_t ] Address
    [ 8 bytes / uint64_t ] Size
    [ 256 bytes / char * ] Label
} // Repeated "Number of VMMaps" times
```

## Python Scripts

Profiler creates binary profiles to reduce processing and IO during sampling
process. Those binary profiles must be postprocessed to create a pbin file which
then can be plotted, aggregated and compared with the respective scripts. All
scripts have a help page for further usage.

Profiles from the Lynsyn viewer can be exported as CSV and converted and
postprocessed with the csv2pbin.py script.

All scripts support bzip2 compression for input and output of profiles.
