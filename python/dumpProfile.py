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
parser = argparse.ArgumentParser(description="Dump profile data into a csv")
parser.add_argument("profile", help="postprocessed profile from intrvelf")
parser.add_argument("-o", "--output", help="output file (default stdout)", default=sys.stdout)

args = parser.parse_args()

if (not args.profile) or (not os.path.isfile(args.profile)):
    print("ERROR: profile not found")
    parser.print_help()
    sys.exit(1)

print("Reading profile... ")
try:
    profile = pickle.load(xopen(args.profile, mode="rb"))
except Exception:
    raise Exception(f'Could not read file {args.profile}')


if 'version' not in profile or (profile['version'] != profileLib.profileVersion and profile['version'] != profileLib.aggProfileVersion):
    raise Exception("Incompatible profile and/or version")


if profile['version'] == profileLib.profileVersion:
    samples = numpy.array(profile['profile'], dtype=object)

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
