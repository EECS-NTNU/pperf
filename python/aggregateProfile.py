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


aggregateKeyNames = ["pc", "binary", "file", "procedure_mangled", "procedure", "line"]

parser = argparse.ArgumentParser(description="Visualize profiles from intrvelf sampler.")
parser.add_argument("profiles", help="postprocessed profiles from intrvelf", nargs="+")
parser.add_argument("-a", "--aggregate-keys", help=f"aggregate after this list (%(default)s) e.g.: {','.join(aggregateKeyNames)}", default="binary,procedure")
parser.add_argument("--use-time", action="store_true", help="sort and plot based on time (default)", default=False)
parser.add_argument("--use-energy", action="store_true", help="sort and plot based on energy", default=False)
parser.add_argument("-l", "--limit", help="limit output to %% of time", type=float, default=0)
parser.add_argument("-t", "--table", help="output csv table")
parser.add_argument("-p", "--plot", help="plotly html file")
parser.add_argument("-o", "--output", help="output aggregated profile")
parser.add_argument("--export", help="export plot (pdf, svg, png,...)")
parser.add_argument("--width", help="export width", type=int, default=1500)
parser.add_argument("--height", help="export height", type=int)
parser.add_argument("--cut-off-symbols", help="number of characters symbol to insert line break (positive) or cut off (negative)", type=int, default=64)
parser.add_argument("--account-latency", action="store_true", help="substract latency")
parser.add_argument("--use-wall-time", action="store_true", help="use sample wall time")
parser.add_argument("--use-cpu-time", action="store_true", help="use cpu time (default)")
parser.add_argument("-q", "--quiet", action="store_true", help="do not automatically open output file", default=False)


args = parser.parse_args()

if (args.use_time is False and args.use_energy is False):
    args.use_time = True

if not args.use_cpu_time and not args.use_wall_time:
    args.use_cpu_time = True

if (args.limit is not 0 and (args.limit < 0 or args.limit > 1)):
    print("ERROR: limit is out of range")
    parser.print_help()
    sys.exit(0)

if (args.quiet and not args.plot and not args.table and not args.output and not args.export):
    print("ERROR: don't know what to do")
    parser.print_help()
    sys.exit(1)

if (not args.profiles) or (len(args.profiles) <= 0):
    print("ERROR: unsufficient amount of profiles passed")
    parser.print_help()
    sys.exit(1)


aggregateKeys = [aggregateKeyNames.index(x) for x in args.aggregate_keys.split(',')]

if (max(aggregateKeys) > 5 or min(aggregateKeys) < 0):
    print("ERROR: aggregate keys are out of bounds (0-5)")
    sys.exit(1)


aggregatedProfile = {
    'version': profileLib.aggProfileVersion,
    'samples': 0,
    'samplingTime': 0,
    'latencyTime': 0,
    'profile': {},
    'volts': 0,
    'name': False,
    'target': False,
    'mean': len(args.profiles),
    'aggregated': False,
    'toolchain': 'various'
}

meanFac = 1 / aggregatedProfile['mean']
avgLatencyUs = 0
avgSampleTime = 0

i = 1
for fileProfile in args.profiles:
    profile = {}
    if fileProfile.endswith(".bz2"):
        profile = pickle.load(bz2.BZ2File(fileProfile, mode="rb"))
    else:
        profile = pickle.load(open(fileProfile, mode="rb"))

    if i == 1 and 'version' in profile and profile['version'] == profileLib.aggProfileVersion and len(args.profiles) == 1:
        aggregatedProfile = profile
        break

    if i == 1:
        aggregatedProfile['toolchain'] = profile['toolchain']
    elif aggregatedProfile['toolchain'] != profile['toolchain']:
        aggregatedProfile['toolchain'] = 'various'

    print(f"Aggregate profile {i}/{len(args.profiles)}...\r", end="")
    i += 1

    if 'version' not in profile or profile['version'] != profileLib.profileVersion:
        raise Exception(f"Incompatible profile version (required: {profileLib.profileVersion})")

    if not aggregatedProfile['target']:
        aggregatedProfile['name'] = profile['name']
        aggregatedProfile['target'] = profile['target']
        aggregatedProfile['volts'] = profile['volts']

    if (profile['volts'] != aggregatedProfile['volts']):
        print("ERROR: profile voltages don't match!")

    sampleFormatter = profileLib.sampleFormatter(profile['binaries'], profile['functions'], profile['files'])

    aggregatedProfile['latencyTime'] += profile['latencyTime'] * meanFac
    aggregatedProfile['samplingTime'] += profile['samplingTime'] * meanFac
    aggregatedProfile['samples'] += profile['samples'] * meanFac
    avgSampleTime = profile['samplingTime'] / profile['samples']
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

            sampleData = sampleFormatter.getSample(thread[2])

            aggregateIndex = sampleFormatter.formatSample(sampleData, displayKeys=aggregateKeys)
            if threadId not in threadLocations:
                threadLocations[threadId] = None

            if aggregateIndex not in subAggregate:
                subAggregate[aggregateIndex] = [
                    useSampleTime,  # total execution time
                    sample[0] * cpuShare * useSampleTime,  # energy (later power)
                    1,
                    1,
                    sampleFormatter.sanitizeOutput(aggregateIndex, lStringStrip=aggregatedProfile['target'])
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
            aggregatedProfile['profile'][key][profileLib.aggTime] += subAggregate[key][0] * meanFac
            aggregatedProfile['profile'][key][profileLib.aggEnergy] += subAggregate[key][1] * meanFac
            aggregatedProfile['profile'][key][profileLib.aggSamples] += subAggregate[key][2] * meanFac
            aggregatedProfile['profile'][key][profileLib.aggExecs] += subAggregate[key][3] * meanFac
        else:
            aggregatedProfile['profile'][key] = [
                subAggregate[key][0] * meanFac,
                0,
                subAggregate[key][1] * meanFac,
                subAggregate[key][2] * meanFac,
                subAggregate[key][3] * meanFac,
                subAggregate[key][4]

            ]

    del subAggregate
    gc.collect()

# aggregatedProfile['profile'][key] = [time, power, energy, samples, executions, label]

# aggregated energy and time, turn it to power
if 'aggregated' not in aggregatedProfile or aggregatedProfile['aggregated'] is False:
    for key in aggregatedProfile['profile']:
        time = aggregatedProfile['profile'][key][profileLib.aggTime]
        energy = aggregatedProfile['profile'][key][profileLib.aggEnergy]
        aggregatedProfile['profile'][key][profileLib.aggPower] = energy / time if time != 0 else 0

    aggregatedProfile['aggregated'] = True

avgLatencyTime = aggregatedProfile['latencyTime'] / aggregatedProfile['samples']
avgSampleTime = aggregatedProfile['samplingTime'] / aggregatedProfile['samples']
frequency = 1 / avgSampleTime

values = numpy.array(list(aggregatedProfile['profile'].values()), dtype=object)
if (args.use_time):
    values = values[values[:, profileLib.aggTime].argsort()]
else:
    values = values[values[:, profileLib.aggEnergy].argsort()]

times = numpy.array(values[:, profileLib.aggTime], dtype=float)
powers = numpy.array(values[:, profileLib.aggPower], dtype=float)
energies = numpy.array(values[:, profileLib.aggEnergy], dtype=float)
samples = numpy.array(values[:, profileLib.aggSamples], dtype=float)
execs = numpy.array(values[:, profileLib.aggExecs], dtype=float)
aggregationLabel = values[:, profileLib.aggLabel]

totalTime = numpy.sum(times)
totalEnergy = numpy.sum(energies)
totalPower = totalEnergy / totalTime if totalTime > 0 else 0
totalExec = numpy.sum(execs)
totalSamples = numpy.sum(samples)

if args.limit is not 0:
    accumulate = 0.0
    accumulateLimit = totalTime * args.limit
    for index, value in enumerate(times[::-1]):
        accumulate += value
        if (accumulate >= accumulateLimit):
            cutOff = len(energies) - (index + 1)
            print(f"Limit output to {index+1}/{len(times)} values...")
            times = times[cutOff:]
            execs = execs[cutOff:]
            energies = energies[cutOff:]
            powers = powers[cutOff:]
            aggregationLabel = aggregationLabel[cutOff:]
            samples = samples[cutOff:]
            break

labels = [f"{x:.4f} s, {s:.2f} W" + (f", {x * 100 / totalTime if totalTime > 0 else 0:.2f}%" if args.use_time else f", {y * 100 / totalEnergy if totalEnergy > 0 else 0:.2f}%") for x, s, y in zip(times, powers, energies)]


# aggregationLabel = [ re.sub(r'\(.*\)$', '', x) for x in aggregationLabel ]

if (args.plot) or (args.export):
    import plotly
    import plotly.graph_objects as go
    import plotlyExport
    plotly.io.templates.default = 'plotly_white'

    if (args.cut_off_symbols > 0):
        pAggregationLabel = [textwrap.fill(x, args.cut_off_symbols).replace('\n', '<br />') for x in aggregationLabel]
        leftMargin = abs(args.cut_off_symbols)
    elif (args.cut_off_symbols < 0):
        pAggregationLabel = [f"{x[0:abs(args.cut_off_symbols)]}..." if len(x) > abs(args.cut_off_symbols) else x for x in aggregationLabel]
        leftMargin = abs(args.cut_off_symbols) + 3
    else:
        pAggregationLabel = aggregationLabel
        leftMargin = numpy.max([len(x) for x in pAggregationLabel])

    indices = [i for i, _ in enumerate(energies)]
    fig = {
        "data": [go.Bar(
            x=times if args.use_time else energies,
            y=indices,
            text=labels,
            textposition='auto',
            orientation='h',
            hoverinfo="x",
        )],
        "layout": go.Layout(
            title=go.layout.Title(
                text=f"{aggregatedProfile['name']}, {frequency:.2f} Hz, {aggregatedProfile['samples']:.2f} samples, {(avgLatencyTime * 1000000):.2f} us latency, {totalEnergy:.2f} J" + (f", mean of {aggregatedProfile['mean']} runs" if aggregatedProfile['mean'] > 1 else ""),
                xref='paper',
                x=0
            ),
            xaxis=go.layout.XAxis(
                title=go.layout.xaxis.Title(
                    text="Time in s" if args.use_time else "Energy in J",
                    font=dict(
                        family='Courier New, monospace',
                        size=18,
                        color='black'  # '#7f7f7f'
                    )
                )
            ),
            yaxis=go.layout.YAxis(
                tickfont=dict(
                    family='monospace',
                    size=12,
                    color='black'
                ),
                ticktext=pAggregationLabel,
                tickvals=indices,
            ),
            margin=go.layout.Margin(l=10 + (7.00 * leftMargin))
        )
    }

    if (args.export):
        plotlyExport.exportFigure(
            go.Figure(fig).update_layout(title=None, margin_t=0, margin_r=0),
            args.width if args.width else None,
            args.height if args.height else None,
            args.export,
            not args.quiet
        )
        print(f"Exported to {args.export}")

    if (args.plot):
        plotly.offline.plot(fig, filename=args.plot, auto_open=not args.quiet)
        print(f"Plot saved to {args.plot}")

    del pAggregationLabel
    del fig
    gc.collect()

if (args.table or not args.quiet):
    aggregationLabel = numpy.insert(aggregationLabel[::-1], 0, "_total")
    times = numpy.insert(times[::-1], 0, totalTime)
    execs = numpy.insert(execs[::-1], 0, totalExec)
    energies = numpy.insert(energies[::-1], 0, totalEnergy)
    powers = numpy.insert(powers[::-1], 0, totalPower)
    samples = numpy.insert(samples[::-1], 0, totalSamples)


if (args.table):
    if args.table.endswith("bz2"):
        table = bz2.BZ2File.open(args.table, "w")
    else:
        table = open(args.table, "w")
    table.write("function;time;power;energy;samples\n")
    for f, t, e, s, m, n in zip(aggregationLabel, times, execs, powers, energies, samples):
        table.write(f"{f};{t};{e};{s};{m};{n}\n")
    table.close()
    print(f"CSV saved to {args.table}")

if (args.output):
    if args.output.endswith("bz2"):
        output = bz2.BZ2File(args.output, "wb")
    else:
        output = open(args.output, "wb")
    pickle.dump(aggregatedProfile, output, pickle.HIGHEST_PROTOCOL)
    print(f"Aggregated profile saved to {args.output}")

if (not args.quiet):
    relativeSamples = [f"{x / totalSamples:.3f}" for x in samples]
    if (args.cut_off_symbols > 0):
        pAggregationLabel = [textwrap.fill(x, args.cut_off_symbols) for x in aggregationLabel]
    elif (args.cut_off_symbols < 0):
        pAggregationLabel = [f"{x[0:abs(args.cut_off_symbols)]}..." if len(x) > abs(args.cut_off_symbols) else x for x in aggregationLabel]
    else:
        pAggregationLabel = aggregationLabel
    print(tabulate.tabulate(zip(pAggregationLabel, times, execs, powers, energies, samples, relativeSamples), headers=['Function', 'Time [s]', 'Executions', 'Power [W]', 'Energy [J]', 'Samples', '%']))
