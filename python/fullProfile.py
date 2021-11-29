#!/usr/bin/env python3

import sys
import os
import argparse
import pickle
import numpy
import profileLib
import gc
from xopen import xopen

aggregateDefault = [profileLib.SAMPLE.names[profileLib.SAMPLE.binary], profileLib.SAMPLE.names[profileLib.SAMPLE.function]]
parser = argparse.ArgumentParser(description="Visualize profiles from intrvelf sampler.")
parser.add_argument("profile", help="postprocessed profile from intrvelf")
parser.add_argument("-s", "--start", type=float, help="start time (seconds)")
parser.add_argument("-e", "--end", type=float, help="end time (seconds)")
parser.add_argument("-i", "--interpolate", type=int, help="interpolate samples")
parser.add_argument("-a", "--aggregate", help=f"aggregate symbols (default: {' '.join(aggregateDefault)})", choices=profileLib.SAMPLE.names, nargs="+", default=[])
parser.add_argument("-d", "--delimiter", help="aggregate symbol delimiter (default '%(default)s')", default=":")
parser.add_argument("-ea", "--external-aggregate", help=f"aggregate external symbols (default: {' '.join(aggregateDefault)})", choices=profileLib.SAMPLE.names, nargs="+", default=[])
parser.add_argument("-ed", "--external-delimiter", help="delimiter for external symbols (default: ':')", default=None)
parser.add_argument("--label-none", help="label none data (default '%(default)s')", default="_unknown")
parser.add_argument("-t", "--table", help="save csv containing all threads and samples with time and power")
parser.add_argument("--table-gantt", help="save gantt like csv")

args = parser.parse_args()

if len(args.aggregate) == 0:
    args.aggregate = aggregateDefault

if len(args.external_aggregate) == 0:
    args.external_aggregate = args.aggregate

if args.external_delimiter is None:
    args.external_delimiter = args.delimiter

if (not args.table and not args.table_gantt):
    parser.print_help()
    sys.exit(0)

if (not args.profile) or (not os.path.isfile(args.profile)):
    print("ERROR: profile not found")
    parser.print_help()
    sys.exit(1)

print("Reading profile... ")
try:
    profile = pickle.load(xopen(args.profile, mode="rb"))
except Exception:
    raise Exception(f'Could not read file {args.profile}')


if 'version' not in profile or profile['version'] != profileLib.profileVersion:
    raise Exception(f"Incompatible profile version (required: {profileLib.profileVersion})")


avgSampleLatency = profile['latencyTime'] / profile['samples']
avgSampleTime = profile['samplingTime'] / profile['samples']
freq = 1 / avgSampleTime
volts = profile['volts']
cpus = profile['cpus']

samples = numpy.array(profile['profile'], dtype=object)
del profile['profile']
gc.collect()

if (args.start):
    samples = samples[int(args.start / avgSampleTime) - 1:]
    if (args.end):
        args.end -= args.start
else:
    args.start = 0.0

if (args.end):
    samples = samples[:int(args.end / avgSampleTime)]

if (args.interpolate):
    print("Interpolating... ")
    sys.stdout.flush()
    if (len(samples) % args.interpolate != 0):
        samples = numpy.delete(samples, numpy.s_[-(len(samples) % args.interpolate):], axis=0)
    samples = samples.reshape(-1, args.interpolate, 3)
    samples = numpy.array([[x[:, :1].mean(), x[0][1], x[0][2]] for x in samples], dtype=object)
    samples = samples.reshape(-1, 3)
else:
    args.interpolate = 1

powers = samples[:, 0:1].flatten()
times = samples[:, 1:2].flatten()

threads = []
threadDisplay = []

sampleFormatter = profileLib.sampleFormatter(profile['maps'])

print("Parsing threads... ")
sys.stdout.flush()
threadNone = [None] * len(samples)
threadMap = {}
prevSampleWallTime = None
for index, sample in enumerate(samples):
    # Determine possible active cores
    activeCores = min(len(sample[2]), cpus)
    if prevSampleWallTime is None:
        prevSampleWallTime = sample[1]

    sampleWallTime = sample[1] - prevSampleWallTime
    prevSampleWallTime = sample[1]
    for threadSample in sample[2]:
        if threadSample[0] in threadMap:
            threadIndex = threadMap[threadSample[0]]
        else:
            threadIndex = len(threads)
            threadMap[threadSample[0]] = threadIndex
            threads.append(list.copy(threadNone))
            threadDisplay.append(list.copy(threadNone))

        threads[threadIndex][index] = threadIndex + 1
        mappedSample = sampleFormatter.remapSample(threadSample[2])
        if mappedSample[profileLib.SAMPLE.binary] == profile['target']:
            threadDisplay[threadIndex][index] = sampleFormatter.formatSample(mappedSample, displayKeys=args.aggregate, delimiter=args.delimiter, labelNone=args.label_none)
        else:
            threadDisplay[threadIndex][index] = sampleFormatter.formatSample(mappedSample, displayKeys=args.external_aggregate, delimiter=args.external_delimiter, labelNone=args.label_none)

if args.table_gantt:
    ganttThreadMap = {}
    csvFile = xopen(args.table_gantt, "w")
    csvFile.write('_thread\ttime\t_offset\t_label\n')
    for s, time in enumerate(times):
        for t, _ in enumerate(threadDisplay):
            if (t in ganttThreadMap) and (ganttThreadMap[t]['label'] != threadDisplay[t][s]):
                if (ganttThreadMap[t]['label'] is not None):
                    csvFile.write(f"{t}\t{time - ganttThreadMap[t]['time']:.16f}\t{ganttThreadMap[t]['time']:.16f}\t{ganttThreadMap[t]['label']}\n")
                ganttThreadMap[t]['time'] = time
                ganttThreadMap[t]['label'] = threadDisplay[t][s]
            elif (t not in ganttThreadMap) and (threadDisplay[t][s] is not None):
                ganttThreadMap[t] = {'time': time, 'label': threadDisplay[t][s]}
    csvFile.close()
    print(f'CSV saved to {args.table_gantt}')


if args.table:
    csvFile = xopen(args.table, "w")
    csvFile.write('time\tpower')
    for t, _ in enumerate(threadDisplay):
        csvFile.write(f'\tthread_{t}')
    csvFile.write('\n')
    for s, _ in enumerate(samples):
        csvFile.write(f'{times[s]}\t{powers[s]}')
        for t, _ in enumerate(threadDisplay):
            csvFile.write(f'\t{threadDisplay[t][s]}')
        csvFile.write('\n')
    csvFile.close()
    print(f'CSV saved to {args.table}')
