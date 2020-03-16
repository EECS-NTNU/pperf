#!/usr/bin/env python3

import sys
import os
import argparse
import bz2
import pickle
import plotly
import plotly.graph_objs as go
import numpy
import profileLib
import gc
import plotlyExport

plotly.io.templates.default = 'plotly_white'

aggregateKeyNames = ["pc", "binary", "file", "procedure_mangled", "procedure", "line"]

parser = argparse.ArgumentParser(description="Visualize profiles from intrvelf sampler.")
parser.add_argument("profile", help="postprocessed profile from intrvelf")
parser.add_argument("-s", "--start", type=float, help="plot start time (seconds)")
parser.add_argument("-e", "--end", type=float, help="plot end time (seconds)")
parser.add_argument("-i", "--interpolate", type=int, help="interpolate samples")
parser.add_argument("-a", "--aggregate-keys", help=f"aggregate after this list (%(default)s) e.g.: {','.join(aggregateKeyNames)}", default="binary,procedure")
parser.add_argument("-p", "--plot", help="plot output html file")
parser.add_argument("-q", "--quiet", action="store_true", help="do not automatically open plot")
parser.add_argument("--csv-power", help="save time, power csv to file")
parser.add_argument("--csv-threads", help="save thread csv")
parser.add_argument("--csv-gantt-threads", help="save gantt like thread focus csv")
parser.add_argument("--csv-gantt-labels", help="save gantt like per label focus csv (directory needed!)")

parser.add_argument("--export", help="export plot (pdf, svg, png,...)")
parser.add_argument("--width", help="export width", type=int, default=1500)
parser.add_argument("--height", help="export height", type=int)

args = parser.parse_args()

if (not args.profile) or (not os.path.isfile(args.profile)):
    print("ERROR: profile not found")
    parser.print_help()
    sys.exit(1)

aggregateKeys = [aggregateKeyNames.index(x) for x in args.aggregate_keys.split(',')]

print("Reading profile... ", end="")
sys.stdout.flush()

if args.profile.endswith(".bz2"):
    profile = pickle.load(bz2.BZ2File(args.profile, mode="rb"))
else:
    profile = pickle.load(open(args.profile, mode="rb"))

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
    if (args.csv_power.endswith('.bz2')):
        csvFile = bz2.open(args.csv_power, "wt")
    else:
        csvFile = open(args.csv_power, "w")
    csvFile.write('Time\tPower\n')
    for time, power in zip(times, powers):
        csvFile.write(f'{time}\t{power}\n')
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
        threadDisplay[threadIndex][index] = sampleFormatter.sanitizeOutput(sampleFormatter.formatData(threadSample[2], displayKeys=aggregateKeys), lStringStrip=profile['target'])

if args.csv_gantt_threads:
    ganttThreadMap = {}
    if (args.csv_gantt_threads.endswith('.bz2')):
        csvFile = bz2.open(args.csv_gantt_threads, "wt")
    else:
        csvFile = open(args.csv_gantt_threads, "w")
    csvFile.write('_thread\ttime\t_base\t_label\n')
    for s, time in enumerate(times):
        for t, _ in enumerate(threadDisplay):
            if (t in ganttThreadMap) and (ganttThreadMap[t]['label'] != threadDisplay[t][s]):
                if (ganttThreadMap[t]['label'] is not None):
                    csvFile.write(f"{t}\t{time - ganttThreadMap[t]['time']}\t{ganttThreadMap[t]['time']}\t{ganttThreadMap[t]['label']}\n")
                ganttThreadMap[t]['time'] = time
                ganttThreadMap[t]['label'] = threadDisplay[t][s]
            elif (t not in ganttThreadMap) and (threadDisplay[t][s] is not None):
                ganttThreadMap[t] = {'time': time, 'label': threadDisplay[t][s]}
    csvFile.close()


if args.csv_threads:
    if (args.csv_threads.endswith('.bz2')):
        csvFile = bz2.open(args.csv_threads, "wt")
    else:
        csvFile = open(args.csv_threads, "w")
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

if (args.plot):
    if args.interpolate > 1:
        title += f", {args.interpolate} samples interpolated"
        threadAxisHeight = 0.1 + (0.233 * min(1, len(threads) / 32))

    print(f"Going to plot {len(samples)} samples from {times[0]}s to {times[-1]}s")

    fig = plotly.subplots.make_subplots(
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

    sys.stdout.flush()
    if (args.plot):
        plotly.offline.plot(fig, filename=args.plot, auto_open=not args.quiet)
        print(f"Plot saved to {args.plot}")

        if (args.export):
            plotlyExport.exportInternal(
                go.Figure(fig).update_layout(title=None, margin_t=0, margin_r=0),
                args.width if args.width else None,
                args.height if args.height else None,
                args.export,
                not args.quiet
            )
            print(f"Exported to {args.export}")
