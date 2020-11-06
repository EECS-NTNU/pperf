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
from xopen import xopen

aggregateDefault = [profileLib.SAMPLE.names[profileLib.SAMPLE.binary], profileLib.SAMPLE.names[profileLib.SAMPLE.function]]

parser = argparse.ArgumentParser(description="Aggregate full profiles, accumulate or average multiple profiles.")
parser.add_argument("profiles", help="postprocessed profiles from pperf", nargs="+")
parser.add_argument("--mode", choices=['mean', 'add'], default='mean', help=f"compute mean or accumulated profiles (%(default)s)")
parser.add_argument("-a", "--aggregate", help=f"aggregate symbols (default: %{', '.join(aggregateDefault)}s)", choices=profileLib.SAMPLE.names, nargs="+", default=[])
parser.add_argument("-d", "--delimiter", help=f"aggregate symbol delimiter (default '%(default)s')", default=":")
parser.add_argument("-ea", "--external-aggregate", help=f"aggregate external symbols (default: %{', '.join(aggregateDefault)}s)", choices=profileLib.SAMPLE.names, nargs="+", default=[])
parser.add_argument("-ed", "--external-delimiter", help=f"delimiter for external symbols (default: ':')", default=None)

parser.add_argument("--label-none", help=f"label none data (default '%(default)s')", default="_unknown")
parser.add_argument("--use-time", action="store_true", help="sort based on time (default)", default=False)
parser.add_argument("--use-energy", action="store_true", help="sort based on energy", default=False)
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

parser.add_argument("-t", "--table", help="output csv table")
parser.add_argument("-o", "--output", help="output aggregated profile")
parser.add_argument("-q", "--quiet", action="store_true", help="do not automatically open output file", default=False)
parser.add_argument("--cut-off-symbols", help="number of characters symbol to insert line break (positive) or cut off (negative)", type=int, default=64)
parser.add_argument("--account-latency", action="store_true", help="substract latency")
parser.add_argument("--use-wall-time", action="store_true", help="use sample wall time")
parser.add_argument("--use-cpu-time", action="store_true", help="use cpu time (default)")


args = parser.parse_args()

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

if len(args.aggregate) == 0:
    args.aggregate = aggregateDefault

if len(args.external_aggregate) == 0:
    args.external_aggregate = args.aggregate

if args.external_delimiter is None:
    args.external_delimiter = args.delimiter


aggregatedProfile = {
    'version': profileLib.aggProfileVersion,
    'samples': 0,
    'samplingTime': 0,
    'latencyTime': 0,
    'profile': {},
    'energy': 0,
    'power': 0,
    'volts': 0,
    'name': False,
    'target': False,
    'mean': len(args.profiles),
    'aggregated': False,
    'toolchain': 'various',
}

if args.mode == 'add':
    modeFac = 1
else:
    modeFac = 1 / aggregatedProfile['mean']

i = 1
for fileProfile in args.profiles:
    try:
        profile = pickle.load(xopen(fileProfile, mode="rb"))
    except:
        raise Exception(f'Could not read file {fileProfile}')

    if i == 1 and 'version' in profile and profile['version'] == profileLib.aggProfileVersion and len(args.profiles) == 1:
        aggregatedProfile = profile
        break

    if i == 1:
        aggregatedProfile['toolchain'] = profile['toolchain']
    elif aggregatedProfile['toolchain'] != profile['toolchain']:
        aggregatedProfile['toolchain'] = 'various'

    print(f"Aggregate profile {i}/{len(args.profiles)}")
    i += 1

    if 'version' not in profile or profile['version'] != profileLib.profileVersion:
        raise Exception(f"Incompatible profile version (required: {profileLib.profileVersion})")

    if not aggregatedProfile['target']:
        aggregatedProfile['name'] = profile['name']
        aggregatedProfile['target'] = profile['target']
        aggregatedProfile['volts'] = profile['volts']

    if (profile['volts'] != aggregatedProfile['volts']):
        print("ERROR: profile voltages don't match!")

    sampleFormatter = profileLib.sampleFormatter(profile['maps'])

    aggregatedProfile['latencyTime'] += profile['latencyTime'] * modeFac
    aggregatedProfile['samplingTime'] += profile['samplingTime'] * modeFac
    aggregatedProfile['samples'] += profile['samples'] * modeFac
    if ('energy' in profile):
        aggregatedProfile['energy'] += profile['energy'] * modeFac
    avgLatencyTime = profile['latencyTime'] / profile['samples']

    subAggregate = {}
    threadLocations = {}
    prevSampleWallTime = None
    for sample in profile['profile']:
        activeCores = min(len(sample[2]), profile['cpus'])

        if prevSampleWallTime is None:
            prevSampleWallTime = sample[1]

        sampleWallTime = sample[1] - prevSampleWallTime
        prevSampleWallTime = sample[1]
        for thread in sample[2]:
            threadId = thread[0]
            if args.use_cpu_time:
                # Thread CPU Time
                useSampleTime = thread[1]
            else:
                # Sample Wall Time
                useSampleTime = sampleWallTime

            if args.account_latency:
                useSampleTime = max(useSampleTime - avgLatencyTime, 0.0)

            cpuShare = (useSampleTime / (sampleWallTime * activeCores)) if sampleWallTime != 0 else 0

            mappedSample = sampleFormatter.remapSample(thread[2])
            if mappedSample[profileLib.SAMPLE.binary] == profile['target']:
                aggregateIndex = sampleFormatter.formatSample(mappedSample, displayKeys=args.aggregate, delimiter=args.delimiter, labelNone=args.label_none)
            else:
                aggregateIndex = sampleFormatter.formatSample(mappedSample, displayKeys=args.external_aggregate, delimiter=args.external_delimiter, labelNone=args.label_none)

            if threadId not in threadLocations:
                threadLocations[threadId] = None

            if aggregateIndex not in subAggregate:
                subAggregate[aggregateIndex] = [
                    useSampleTime,  # total execution time
                    sample[0] * cpuShare * useSampleTime,  # energy (later power)
                    1,
                    1,
                    aggregateIndex,
                    mappedSample
                ]
            else:
                subAggregate[aggregateIndex][0] += useSampleTime
                subAggregate[aggregateIndex][1] += sample[0] * cpuShare * useSampleTime
                subAggregate[aggregateIndex][2] += 1
                if threadLocations[threadId] != aggregateIndex:
                    subAggregate[aggregateIndex][3] += 1

            threadLocations[threadId] = aggregateIndex

    del sampleFormatter
    del profile
    gc.collect()

    for key in subAggregate:
        if key in aggregatedProfile['profile']:
            aggregatedProfile['profile'][key][profileLib.AGGSAMPLE.time] += subAggregate[key][0] * modeFac
            aggregatedProfile['profile'][key][profileLib.AGGSAMPLE.energy] += subAggregate[key][1] * modeFac
            aggregatedProfile['profile'][key][profileLib.AGGSAMPLE.samples] += subAggregate[key][2] * modeFac
            aggregatedProfile['profile'][key][profileLib.AGGSAMPLE.execs] += subAggregate[key][3] * modeFac
        else:
            aggregatedProfile['profile'][key] = [
                subAggregate[key][0] * modeFac,
                0,
                subAggregate[key][1] * modeFac,
                subAggregate[key][2] * modeFac,
                subAggregate[key][3] * modeFac,
                subAggregate[key][4],
                subAggregate[key][5]
            ]

    del subAggregate
    gc.collect()

# aggregatedProfile['profile'][key] = [time, power, energy, samples, executions, label]

# aggregated energy and time, turn it to power
if 'aggregated' not in aggregatedProfile or aggregatedProfile['aggregated'] is False:
    for key in aggregatedProfile['profile']:
        time = aggregatedProfile['profile'][key][profileLib.AGGSAMPLE.time]
        energy = aggregatedProfile['profile'][key][profileLib.AGGSAMPLE.energy]
        aggregatedProfile['profile'][key][profileLib.AGGSAMPLE.power] = energy / time if time != 0 else 0

    aggregatedProfile['power'] = aggregatedProfile['energy'] / aggregatedProfile['samplingTime']
    aggregatedProfile['aggregated'] = True

values = numpy.array(list(aggregatedProfile['profile'].values()), dtype=object)
if (args.use_time):
    values = values[values[:, profileLib.AGGSAMPLE.time].argsort()]
else:
    values = values[values[:, profileLib.AGGSAMPLE.energy].argsort()]

times = numpy.array(values[:, profileLib.AGGSAMPLE.time], dtype=float)
powers = numpy.array(values[:, profileLib.AGGSAMPLE.power], dtype=float)
energies = numpy.array(values[:, profileLib.AGGSAMPLE.energy], dtype=float)
samples = numpy.array(values[:, profileLib.AGGSAMPLE.samples], dtype=float)
execs = numpy.array(values[:, profileLib.AGGSAMPLE.execs], dtype=float)
aggregationLabel = values[:, profileLib.AGGSAMPLE.label]

if len(args.exclude_binary) > 0 or len(args.exclude_file) > 0 or len(args.exclude_function) > 0 or args.exclude_external:
    mappedSamples = values[:, profileLib.AGGSAMPLE.mappedSample]
    keep = numpy.ones(aggregationLabel.shape, dtype=bool)
    for i, mappedSample in enumerate(mappedSamples):
        if args.exclude_external and mappedSample[profileLib.SAMPLE.binary] != aggregatedProfile['target']:
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
    pickle.dump(aggregatedProfile, output, pickle.HIGHEST_PROTOCOL)
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
