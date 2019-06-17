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

* Support for full profiles
  * profiles contains pmu data, TID, PC and cpu-time for every sample and thread
* all profiles contain execution time (wall), time spend in profiler (latency), number of samples and target VMMap
* output file is optional, if not specified no IO is generated
* frequency is a target, actual reached frequency is displayed in debug output
* threads are fully supported, **though fork, vfork and vclone is not supported**!
* execl, execlp, execle, execv, execvp and execvpe are replacing the current process with new VMMaps and are therefore not supported!

## Profile Header

* Included in every profile
* Magic number defines profile pmu data 
  * 0 - custom
  * 1 - current
  * 2 - voltage (not supported by python scripts)
  * 3 - power

```
[ 4 bytes / uint32_t ] Magic Number
[ 8 bytes / uint64_t ] Wall Time
[ 8 bytes / uint64_t ] CPU Time (latency)
[ 8 bytes / uint64_t ] Number of Samples

[ 4 bytes / uint32_t ] Number of VMMaps
VMMap{
    [ 8 bytes / uint64_t ] Address
    [ 8 bytes / uint64_t ] Size
    [ 256 bytes / char * ] Label
} // Repeated "Number of VMMaps" times
```

### Full Profile

* big and IO heavy
* is written on every sample, does not add any IO buffer (apart from system file buffers)
* frequency, number of threads and sampling time determines size

```
Sample{
    [ 8 bytes / double   ] Current
    [ 4 bytes / uint32_t ] Number of Threads
    Thread{
        [ 4 bytes / uint32_t ] Thread ID
        [ 8 bytes / uint64_t ] PC
        [ 8 bytes / uint64_t ] cputime
    } // Repeated "Number of Threads" times
} // Repeated "Number of Samples" times
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
