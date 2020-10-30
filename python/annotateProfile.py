#!/usr/bin/env python3

import sys
import argparse
import bz2
import pickle
import numpy
import textwrap
import tabulate
import profileLib
import gc
import pandas
from xopen import xopen

aggregateDefault = [profileLib.SAMPLE.names[profileLib.SAMPLE.binary], profileLib.SAMPLE.names[profileLib.SAMPLE.function]]

parser = argparse.ArgumentParser(description="Annotate profiles on asm and source level.")
parser.add_argument("profiles", help="postprocessed profiles from pperf", nargs="+")
parser.add_argument("--mode", choices=['mean', 'add'], default='mean', help=f"compute mean profiles or accumulated profiles (default: %(default)s)")
parser.add_argument("--annotate", choices=['asm', 'source'], default='asm', help=f"what to annotate (default: %(default)s)")
parser.add_argument("--use-time", action="store_true", help="output time (default)", default=False)
parser.add_argument("--use-energy", action="store_true", help="output energy", default=False)

parser.add_argument("-a", "--aggregate", help=f"aggregate symbols (default: %{', '.join(aggregateDefault)}s)", choices=profileLib.SAMPLE.names, nargs="+", default=[])
parser.add_argument("-d", "--delimiter", help=f"aggregate symbol delimiter (default '%(default)s')", default=":")
parser.add_argument("-ea", "--external-aggregate", help=f"aggregate external symbols (default: %{', '.join(aggregateDefault)}s)", choices=profileLib.SAMPLE.names, nargs="+", default=[])
parser.add_argument("-ed", "--external-delimiter", help=f"delimiter for external symbols (default: ':')", default=None)

parser.add_argument("--label-none", help=f"label none data (default '%(default)s')", default="_unknown")
parser.add_argument("--totals", action="store_true", help="output total numbers", default=False)
parser.add_argument("--limit-time", help="limit output to %% of time", type=float, default=0)
parser.add_argument("--limit-energy", help="limit output to %% of time", type=float, default=0)
parser.add_argument("--time-threshold", help="limit to symbols with time contribution (in percent, e.g. 0.0 - 1.0)", type=float, default=0)
parser.add_argument("--limit-time-top", help="limit to top symbols after time", type=int, default=0)
parser.add_argument("--limit-energy-top", help="limit to top symbols after energy", type=int, default=0)
parser.add_argument("--energy-threshold", help="limit to symbols with energy contribution (in percent, e.g. 0.0 - 1.0)", type=float, default=0)
parser.add_argument("--exclude-binary", help="exclude these binaries", default=[], action="append")
parser.add_argument("--exclude-file", help="exclude these files", default=[], action="append")
parser.add_argument("--exclude-function", help="exclude these functions", default=[], action="append")
parser.add_argument("--exclude-external", help="exclude external binaries", default=False, action="store_true")

parser.add_argument("--less-memory", help="opens only one input profile at a time", action="store_true", default=False)
parser.add_argument("-t", "--table", help="output csv table")
parser.add_argument("-o", "--output", help="output annotated profile")
parser.add_argument("--cut-off-symbols", help="number of characters symbol to insert line break (positive) or cut off (negative)", type=int, default=64)
parser.add_argument("--account-latency", action="store_true", help="substract latency")
parser.add_argument("--use-wall-time", action="store_true", help="use sample wall time")
parser.add_argument("--use-cpu-time", action="store_true", help="use cpu time (default)")
parser.add_argument("-q", "--quiet", help="do not print annotated profile", default=False, action="store_true")


args = parser.parse_args()

if args.annotate == 'source':
    raise Exception('source annotation is currently not supported, coming soon...')

if (args.use_time is False and args.use_energy is False):
    args.use_time = True
    args.use_energy = False

if args.use_time:
    args.use_energy = False

if args.use_energy:
    args.use_time = False

if not args.use_cpu_time and not args.use_wall_time:
    args.use_cpu_time = True

if (args.limit_energy_top and not args.use_energy):
    print("ERROR: limit energy top option can only be used with energy (--use-energy)")
    parser.print_help()
    sys.exit(0)

if (args.limit_time_top and not args.use_time):
    print("ERROR: limit time top option can only be used with time (--use-time)")
    parser.print_help()
    sys.exit(0)

if (args.limit_time != 0 and (args.limit_time < 0 or args.limit_time > 1)):
    print("ERROR: limit_time is out of range")
    parser.print_help()
    sys.exit(0)

if (args.limit_energy != 0 and (args.limit_energy < 0 or args.limit_energy > 1)):
    print("ERROR: limit_energy is out of range")
    parser.print_help()
    sys.exit(0)

if (args.time_threshold != 0 and (args.time_threshold < 0 or args.time_threshold > 1.0)):
    print("ERROR: time threshold out of range")
    parser.print_help()
    sys.exit(0)

if (args.energy_threshold != 0 and (args.energy_threshold < 0 or args.energy_threshold > 1.0)):
    print("ERROR: energy threshold out of range")
    parser.print_help()
    sys.exit(0)

if (args.quiet and not args.table and not args.output):
    print("ERROR: don't know what to do")
    parser.print_help()
    sys.exit(1)

if (not args.profiles) or (len(args.profiles) <= 0):
    print("ERROR: unsufficient amount of profiles passed")
    parser.print_help()
    sys.exit(1)

inputProfiles = []
cacheMap = {}

annotatedProfile = None

for i, fileProfile in enumerate(args.profiles):
    profile = pickle.load(xopen(fileProfile, mode="rb"))

    if i == 0 and len(args.profiles) == 1 and 'version' in profile and profile['version'] == profileLib.annProfileVersion:
        annotatedProfile = profile
        break

    if 'version' not in profile or profile['version'] != profileLib.profileVersion:
        raise Exception(f"Incompatible profile version {'None' if 'version' not in profile else profile['version']} (required: {profileLib.profileVersion})")

    cacheMap = {**profile['cacheMap'], **cacheMap}

    if args.less_memory:
        inputProfiles.append(None)
        del profile
    else:
        inputProfiles.append(profile)

    gc.collect()


if annotatedProfile is None:
    modeFac = 1
    if args.mode == 'mean':
        modeFac /= len(inputProfiles)
   
    # aggregateKeys = [profileLib.SAMPLE.binary, profileLib.SAMPLE.file, profileLib.SAMPLE.function, profileLib.SAMPLE.pc]
    annotatedProfile = {
       'version': profileLib.annProfileVersion,
       'samples': 0,
       'samplingTime': 0,
       'latencyTime': 0,
       'annotate': args.annotate,
       'annotation': {},
       'energy': 0,
       'power': 0,
       'name': None,
       'target': None,
       'toolchain': None,
    }

    elfCache = profileLib.elfCache()
    caches = { binary: elfCache.getRawCache(cacheMap[binary]) for binary in cacheMap }

    # annotation = pandas.DataFrame(columns=['pc', 'binary', 'file', 'function', 'basicblock', 'line', 'instruction', 'meta', 'asm', 'source', 'time', 'energy', 'samples'])
    annotation = pandas.DataFrame()

    print('Reading in assembly', end='', flush=True, file=sys.stderr)
    asm = pandas.concat([pandas.DataFrame(cache['cache'].values(), columns=['pc', 'binary', 'file', 'function', 'basicblock', 'line', 'instruction', 'meta']).drop(['instruction', 'meta'], axis=1) for cache in caches.values()], ignore_index=True)
    asm['asm'] = asm.apply(lambda r: caches[r['binary']]['asm'][r['pc']], axis=1)
    print(', source', flush=True, file=sys.stderr)
    source = pandas.concat([pandas.DataFrame({'binary': b, 'file': f, 'line': range(1, len(caches[b]['source'][f])+1), 'source' : caches[b]['source'][f]}) for b in caches for f in caches[b]['source'] if caches[b]['source'][f] is not None], ignore_index=True)

    aggregate = {}

    for i, profile in enumerate(inputProfiles):
        print(f'\rParsing profile {i+1}/{len(inputProfiles)}... ', end='', flush=True, file=sys.stderr)
        if profile is None:
            profile = pickle.load(xopen(args.profiles[i], mode="rb"))

        if annotatedProfile['toolchain'] is None:
            annotatedProfile['toolchain'] = profile['toolchain']
        elif annotatedProfile['toolchain'] != profile['toolchain']:
            annotatedProfile['toolchain'] = 'various'

        if annotatedProfile['target'] is None:
            annotatedProfile['name'] = profile['name']
            annotatedProfile['target'] = profile['target']

        annotatedProfile['latencyTime'] += profile['latencyTime'] * modeFac
        annotatedProfile['samplingTime'] += profile['samplingTime'] * modeFac
        annotatedProfile['samples'] += profile['samples'] * modeFac
        annotatedProfile['energy'] += profile['energy'] * modeFac

        avgLatencyTime = profile['latencyTime'] / profile['samples']

        profileBinaryMap = profile['maps'][profileLib.SAMPLE.binary]

        prevSampleWallTime = profile['profile'][0][1] if len(profile['profile']) > 0 else 0
        for sample in profile['profile']:
            activeCores = min(len(sample[2]), profile['cpus'])
            sampleWallTime = sample[1] - prevSampleWallTime
            for thread in sample[2]:
                pc = thread[2][profileLib.SAMPLE.pc]
                binary = thread[2][profileLib.SAMPLE.binary]
                binary = binary if binary is None else profileBinaryMap[binary]

                time = thread[1] if args.use_cpu_time else sampleWallTime
                if args.account_latency:
                    time = max(useSampleTime - avgLatencyTime, 0.0)

                energy = sample[0] * time * (time / (sampleWallTime * activeCores)) if sampleWallTime != 0 else 0

                if binary not in aggregate:
                    aggregate[binary] = {}
                if pc not in aggregate[binary]:
                    aggregate[binary][pc] = [0, 0, 0]

                aggregate[binary][pc][0] += time
                aggregate[binary][pc][1] += energy
                aggregate[binary][pc][2] += 1

            prevSampleWallTime = sample[1]
        del profile
        gc.collect()

    print('finished', flush=True, file=sys.stderr)
    print('Correlating data', end='', flush=True, file=sys.stderr)
    asm[['time', 'energy', 'samples']] = asm.apply(lambda r: aggregate[r['binary']][r['pc']] if r['binary'] in aggregate and r['pc'] in aggregate[r['binary']] else [0, 0, 0], axis=1, result_type='expand')
    source = source.join(asm.groupby(['binary', 'file', 'line'], as_index=False)[['time','energy','samples']].sum().set_index(['binary', 'file', 'line']), on=['binary', 'file', 'line'])
    print(', cleaning up', flush=True, file=sys.stderr)

    # Fill in 0 values for time, energy and samples
    asm[['line', 'time', 'energy', 'samples']] = asm[['line', 'time', 'energy', 'samples']].fillna(0)
    source[['time', 'energy', 'samples']] = source[['time', 'energy', 'samples']].fillna(0)

    # Line must be object
    annotatedProfile['asm'] = asm.astype({'pc': 'uint64', 'binary': 'object', 'file': 'object', 'function': 'object', 'basicblock': 'object', 'line': 'uint64', 'time': 'float64', 'energy': 'float64', 'samples': 'uint64'})
    annotatedProfile['source'] = source.astype({'binary': 'object', 'file': 'object', 'line': 'uint64', 'source': 'object', 'time': 'float64', 'energy': 'float64', 'samples': 'uint64'})

    del aggregate
    del inputProfiles

    gc.collect()

if (args.output):
    output = xopen(args.output, "wb")
    pickle.dump(annotatedProfile, output, pickle.HIGHEST_PROTOCOL)
    print(f"Annotated profile saved to {args.output}", flush=True, file=sys.stderr)


exit(0)

# annotatedProfile['profile'][key] = [time, power, energy, samples, executions, label]

# aggregated energy and time, turn it to power
if 'aggregated' not in annotatedProfile or annotatedProfile['aggregated'] is False:
    for key in annotatedProfile['profile']:
        time = annotatedProfile['profile'][key][AGGSAMPLE.time]
        energy = annotatedProfile['profile'][key][AGGSAMPLE.energy]
        annotatedProfile['profile'][key][AGGSAMPLE.power] = energy / time if time != 0 else 0

    annotatedProfile['power'] = annotatedProfile['energy'] / aggregatedProfile['samplingTime']
    annotatedProfile['aggregated'] = True

values = numpy.array(list(annotatedProfile['profile'].values()), dtype=object)
if (args.use_time):
    values = values[values[:, AGGSAMPLE.time].argsort()]
else:
    values = values[values[:, AGGSAMPLE.energy].argsort()]

times = numpy.array(values[:, AGGSAMPLE.time], dtype=float)
powers = numpy.array(values[:, AGGSAMPLE.power], dtype=float)
energies = numpy.array(values[:, AGGSAMPLE.energy], dtype=float)
samples = numpy.array(values[:, AGGSAMPLE.samples], dtype=float)
execs = numpy.array(values[:, AGGSAMPLE.execs], dtype=float)
aggregationLabel = values[:, AGGSAMPLE.label]

if len(args.exclude_binary) > 0 or len(args.exclude_file) > 0 or len(args.exclude_function) > 0 or args.exclude_external:
    mappedSamples = values[:, AGGSAMPLE.mappedSample]
    keep = numpy.ones(aggregationLabel.shape, dtype=bool)
    for i, mappedSample in enumerate(mappedSamples):
        if args.exclude_external and mappedSample[profileLib.SAMPLE.binary] != annotatedProfile['target']:
            keep[i] = False
            continue
        for exclude in args.exclude_binary:
            if mappedSample[profileLib.SAMPLE.binary] == exclude:
                keep[i] = False
                break
        for exclude in args.exclude_file:
            if mappedSample[profileLib.SAMPLE.file] == exclude:
                keep[i] = False
                break
        for exclude in args.exclude_function:
            if mappedSample[profileLib.SAMPLE.function] == exclude:
                keep[i] = False
                break
    times = times[keep]
    execs = execs[keep]
    energies = energies[keep]
    powers = powers[keep]
    samples = samples[keep]
    aggregationLabel = aggregationLabel[keep]

totalTime = numpy.sum(times)
totalEnergy = numpy.sum(energies)
totalPower = totalEnergy / totalTime if totalTime > 0 else 0
totalExec = numpy.sum(execs)
totalSamples = numpy.sum(samples)

if args.time_threshold != 0 or args.energy_threshold != 0:
    keep = numpy.ones(times.shape, dtype=bool)
    for pos, _ in enumerate(times):
        if args.time_threshold != 0:
            if ((args.time_threshold != 0 and (times[pos] / totalTime) < args.time_threshold) or
               (args.energy_threshold != 0 and (energies[pos] / totalEnergy) < args.energy_threshold)):
                keep[pos] = False
    times = times[keep]
    execs = execs[keep]
    energies = energies[keep]
    powers = powers[keep]
    samples = samples[keep]
    aggregationLabel = aggregationLabel[keep]

cutOff = None

if args.limit_time != 0:
    accumulate = 0.0
    accumulateLimit = totalTime * args.limit_time
    for index, value in enumerate(times[::-1]):
        accumulate += value
        if (accumulate >= accumulateLimit):
            timeCutOff = len(times) - (index + 1)
            if cutOff is None or timeCutOff > cutOff:
                cutOff = timeCutOff
            break

if args.limit_energy != 0:
    accumulate = 0.0
    accumulateLimit = totalEnergy * args.limit_energy
    for index, value in enumerate(energies[::-1]):
        accumulate += value
        if (accumulate >= accumulateLimit):
            energyCutOff = len(energies) - (index + 1)
            if cutOff is None or energyCutOff > cutOff:
                cutOff = energyCutOff
            break

if args.limit_time_top != 0 and args.limit_time_top < len(times):
    nCutOff = len(times) - (args.limit_time_top)
    if cutOff is None or nCutOff > cutOff:
        cutOff = nCutOff

if args.limit_energy_top != 0 and args.limit_energ_top < len(energies):
    nCutOff = len(energies) - (args.limit_energy_top)
    if cutOff is None or nCutOff > cutOff:
        cutOff = nCutOff

if cutOff is not None:
    print(f"Limit output to {len(times) - cutOff}/{len(times)}...")
    times = times[cutOff:]
    execs = execs[cutOff:]
    energies = energies[cutOff:]
    powers = powers[cutOff:]
    aggregationLabel = aggregationLabel[cutOff:]
    samples = samples[cutOff:]

if (args.output):
    output = xopen(args.output, "wb")
    pickle.dump(annotatedProfile, output, pickle.HIGHEST_PROTOCOL)
    print(f"Aggregated profile saved to {args.output}")

if (not args.table and args.quiet):
    exit(0)

aggregationLabel = aggregationLabel[::-1]
times = times[::-1]
execs = execs[::-1]
energies = energies[::-1]
powers = powers[::-1]
samples = samples[::-1]

if args.totals:
    aggregationLabel = numpy.insert(aggregationLabel, 0, "_total")
    times = numpy.insert(times, 0, totalTime)
    execs = numpy.insert(execs, 0, totalExec)
    energies = numpy.insert(energies, 0, totalEnergy)
    powers = numpy.insert(powers, 0, totalPower)
    samples = numpy.insert(samples, 0, totalSamples)

if (args.table):
    if args.table.endswith("bz2"):
        table = bz2.BZ2File.open(args.table, "w")
    else:
        table = open(args.table, "w")
    table.write("function;time;executions;power;energy;samples\n")
    for f, t, e, s, m, n in zip(aggregationLabel, times, execs, powers, energies, samples):
        table.write(f"{f};{t};{e};{s};{m};{n}\n")
    table.close()
    print(f"CSV saved to {args.table}")

if (not args.quiet):
    relativeSamples = [f"{x / totalSamples:.3f}" for x in samples]
    if (args.cut_off_symbols > 0):
        pAggregationLabel = [textwrap.fill(x, args.cut_off_symbols) for x in aggregationLabel]
    elif (args.cut_off_symbols < 0):
        pAggregationLabel = [f"{x[0:abs(args.cut_off_symbols)]}..." if len(x) > abs(args.cut_off_symbols) else x for x in aggregationLabel]
    else:
        pAggregationLabel = aggregationLabel
    print(tabulate.tabulate(zip(pAggregationLabel, times, execs, powers, energies, samples, relativeSamples), headers=['Function', 'Time [s]', 'Executions', 'Power [W]', 'Energy [J]', 'Samples', '%']))
