#!/usr/bin/env python3

import sys
import os
import argparse
import bz2
import pickle
import plotly
import plotly.graph_objs as go
from plotly.subplots import make_subplots
import numpy
import profileLib
import gc
from xopen import xopen

plotly.io.templates.default = 'plotly_white'

aggregateKeyNames = ["pc", "binary", "file", "procedure_mangled", "procedure", "line"]

parser = argparse.ArgumentParser(description="Visualize profiles from intrvelf sampler.")
parser.add_argument("profile", help="postprocessed profile from intrvelf")
parser.add_argument("-s", "--start", type=float, help="start time (seconds)")
parser.add_argument("-e", "--end", type=float, help="end time (seconds)")
parser.add_argument("-i", "--interpolate", type=int, help="interpolate samples")
parser.add_argument("-a", "--aggregate-keys", help=f"aggregate after this list (%(default)s) e.g.: {','.join(aggregateKeyNames)}", default="binary,procedure")
parser.add_argument("-ls", "--lstrip", default=None, help=f"strip labels on the left (default target binary is stripped)")
parser.add_argument("-o", "--output", help="save html plot")
parser.add_argument("--browser", default=False, action="store_true", help="open plot on browser")
parser.add_argument("--csv-power", help="save time, power csv to file")
parser.add_argument("--csv-threads", help="save thread csv containing  each sample with threads")
parser.add_argument("--csv-gantt-threads", help="save gannt like thread csv")

args = parser.parse_args()

if (not args.browser and not args.output and not args.csv_power and not args.csv_threads and not args.csv_gantt_threads):
    args.browser = True

if (not args.profile) or (not os.path.isfile(args.profile)):
    print("ERROR: profile not found")
    parser.print_help()
    sys.exit(1)

aggregateKeys = [aggregateKeyNames.index(x) for x in args.aggregate_keys.split(',')]

print("Reading profile... ", end="")
sys.stdout.flush()

profile = pickle.load(xopen(args.profile, mode="rb"))

print("finished")


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
    print("Interpolating... ", end="")
    sys.stdout.flush()
    if (len(samples) % args.interpolate != 0):
        samples = numpy.delete(samples, numpy.s_[-(len(samples) % args.interpolate):], axis=0)
    samples = samples.reshape(-1, args.interpolate, 3)
    samples = numpy.array([[x[:, :1].mean(), x[0][1], x[0][2]] for x in samples], dtype=object)
    samples = samples.reshape(-1, 3)
    print("finished")
else:
    args.interpolate = 1

powers = samples[:, 0:1].flatten()
times = samples[:, 1:2].flatten()

if (args.csv_power):
    csvFile = xopen(args.csv_power, "w")
    csvFile.write('Time\tPower\n')
    for time, power in zip(times, powers):
        csvFile.write(f'{time:.16f}\t{power}\n')
    csvFile.close()


threads = []
threadDisplay = []

sampleFormatter = profileLib.sampleFormatter(profile['binaries'], profile['functions'], profile['files'])

print("Parsing threads... ", end="")
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
        threadDisplay[threadIndex][index] = sampleFormatter.sanitizeOutput(sampleFormatter.formatData(threadSample[2], displayKeys=aggregateKeys), lStringStrip=profile['target'] if args.lstrip is None else False if len(args.lstrip) == 0 else args.strip)

if args.csv_gantt_threads:
    ganttThreadMap = {}
    csvFile = xopen(args.csv_gantt_threads, "w")
    csvFile.write('_thread\tTime\t_offset\t_label\n')
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


if args.csv_threads:
    csvFile = xopen(args.csv_threads, "w")
    csvFile.write('Time')
    for t, _ in enumerate(threadDisplay):
        csvFile.write(f'\tThread_{t}')
    csvFile.write('\n')
    for s, _ in enumerate(samples):
        csvFile.write(f'{times[s]}')
        for t, _ in enumerate(threadDisplay):
            csvFile.write(f'\t{threadDisplay[t][s]}')
        csvFile.write('\n')
    csvFile.close()

print("finished")


title = f"{profile['name']}, {freq:.2f} Hz, {profile['samples']} samples, {int(avgSampleLatency * 1000000)} us latency"

del profile
del sampleFormatter
gc.collect()

if (args.browser or args.output):
    if args.interpolate > 1:
        title += f", {args.interpolate} samples interpolated"
        threadAxisHeight = 0.1 + (0.233 * min(1, len(threads) / 32))

    print(f"Going to plot {len(samples)} samples from {times[0]}s to {times[-1]}s")

    fig = make_subplots(
        rows=2,
        cols=1,
        specs=[[{}], [{}]],
        shared_xaxes=True,
        shared_yaxes=False,
        print_grid=False
    )

    fig.append_trace(
        go.Scatter(
            x=times,
            y=powers,
            line_width=1,
        ), 1, 1
    )

    del powers
    gc.collect()

    for i in range(0, len(threads)):
        print(f"Including thread {i}... ", end="")
        sys.stdout.flush()
        fig.append_trace(
            go.Scatter(
                name=f"Thread {i+1}",
                x=times,
                y=threads[i],
                text=threadDisplay[i],
                hoverinfo='text+x'
            ), 2, 1
        )
        print("finished")

    fig.update_layout(title=dict(text=title), showlegend=False)
    fig.update_yaxes(domain=[0.25, 1], title_text="Power in Watt", col=1, row=1)
    fig.update_yaxes(domain=[0, 0.25], title_text="Threads", type='category', range=[-0.5, len(threads)], col=1, row=2)
    fig.update_xaxes(title_text="Time in Seconds", col=1, row=2)

    del times
    del threads
    del threadDisplay
    gc.collect()
    if (args.output):
        plotly.offline.plot(fig, filename=args.output, auto_open=False)
        print(f'Saved to {args.output}')
    if (args.browser):
        fig.show()
