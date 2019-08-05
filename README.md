# Intrusive ELF Profiler

```text
sampler [options] -- <command> [arguments]

Options:
  -o, --output=<file>       write to file
  -p, --pmu-arg=<arg>       pmu argument
  -f, --frequency=<hertz>   sampling frequency
  -d, --debug               output sampling informations at the end
  -h, --help                shows help
```

* profiles contains Wall Time, PMU Data, threads for every sample and TID, PC and CPU Time for every thread
* all profiles contain execution time (wall), time spent in profiler (latency), number of samples and target VMMap
* output file is optional, if not specified no IO is generated
* frequency is a target, actual reached frequency is displayed in verbose output
* threads are fully supported, **though fork, vfork and vclone is not supported**!
* execl, execlp, execle, execv, execvp and execvpe are replacing the current process with new VMMaps and are therefore not supported!

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
    [ 8 bytes / double   ] PMU Value
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

sthem2pbin script converts a csv file exported by the sthem analysis tool to a
pbin file. Cpu time is not available, resulting in skewed results for parallel
benchmarks. Use only if you know how to interpret the data!

All scripts support bzip2 compression for input and output of profiles.
