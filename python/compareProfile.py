#!/usr/bin/env python3

import sys
import argparse
import bz2
import pickle
import numpy
import textwrap
import tabulate
import copy
import math
import operator
import collections
import profileLib
import statistics


def error(baseline, value, totalBaseline, totalValue, weight):
    return value - baseline


def weightedError(baseline, value, totalBaseline, totalValue, weight):
    return error(baseline, value, totalBaseline, totalValue, weight) * weight


def absoluteWeightedError(baseline, value, totalBaseline, totalValue, weight):
    return abs(weightedError(baseline, value, totalBaseline, totalValue, weight))


def absoluteError(baseline, value, totalBaseline, totalValue, weight):
    return abs(error(baseline, value, totalBaseline, totalValue, weight))


def relativeError(baseline, value, totalBaseline, totalValue, weight):
    return error(baseline, value, totalBaseline, totalValue, weight) / baseline if (baseline != 0) else 0


def absoluteRelativeError(baseline, value, totalBaseline, totalValue, weight):
    return abs(relativeError(baseline, value, totalBaseline, totalValue, weight))


def weightedRelativeError(baseline, value, totalBaseline, totalValue, weight):
    return relativeError(baseline, value, totalBaseline, totalValue, weight) * weight


def absoluteWeightedRelativeError(baseline, value, totalBaseline, totalValue, weight):
    return abs(weightedRelativeError(baseline, value, totalBaseline, totalValue, weight))


# values are already processed by errorFunction
def aggregateSum(baselines, values, totalBaseline, totalValue, weights):
    return sum(values)


# values are already processed by errorFunction
def aggregateMin(baselines, values, totalBaseline, totalValue, weights):
    return min(values)


# values are already processed by errorFunction
def aggregateMax(baselines, values, totalBaseline, totalValue, weights):
    return max(values)


# values are already processed by errorFunction
def aggregateMean(baselines, values, totalBaseline, totalValue, weights):
    return sum(values) / len(values)


def aggregateWeightedMean(baselines, values, totalBaseline, totalValue, weights):
    return sum([value * weight for value, weight in zip(values, weights)])
    explodedData = []
    for value, weight in zip(values, weights):
        explodedData = numpy.append(explodedData, [value] * max(1, int(10000 * abs(weight))))
    return statistics.mean(explodedData)


def aggregateRootMeanSquaredError(baselines, values, totalBaseline, totalValue, weights):
    return math.sqrt(sum([math.pow(error(baseline, value, totalBaseline, totalValue, weight), 2) for baseline, value, weight in zip(baselines, values, weights)]) / len(values))


def aggregateWeightedRootMeanSquaredError(baselines, values, totalBaseline, totalValue, weights):
    return math.sqrt(sum([math.pow(error(baseline, value, totalBaseline, totalValue, weight), 2) * weight for baseline, value, weight in zip(baselines, values, weights)]))


# [ parameter, description, error function,  ]
errorFunctions = numpy.array([
    ['relative_error', 'Relative Error', relativeError],
    ['error', 'Error', error],
    ['absolute_error', 'Absolute Error', absoluteError],
    ['weighted_error', 'Weighted Error', weightedError],
    ['absolute_weighted_error', 'Absolute Weighted Error', absoluteWeightedError],
    ['absolute_relative_error', 'Absolute Relative Error', absoluteRelativeError],
    ['weighted_relative_error', 'Weighted Relative Error', weightedRelativeError],
    ['absolute_weighted_relative_error', 'Absolute Weighted Relative Error', absoluteWeightedRelativeError],
], dtype=object)

aggregateFunctions = numpy.array([
    ['sum', 'Total', aggregateSum, True],
    ['min', 'Minimum', aggregateMin, True],
    ['max', 'Maximum', aggregateMax, True],
    ['mean', 'Mean', aggregateMean, True],
    ['wmean', 'Weighted Mean', aggregateWeightedMean, True],
    ['rmse', 'Root Mean Squared Error', aggregateRootMeanSquaredError, False],
    ['wrmse', 'Weighted Root Mean Squared Error', aggregateWeightedRootMeanSquaredError, False]
])

parser = argparse.ArgumentParser(description="Visualize profiles from intrvelf sampler.")
parser.add_argument("profile", help="baseline aggregated profile")
parser.add_argument("profiles", help="aggregated profiles to compare", nargs="+")
parser.add_argument("--use-time", help="compare time values", action="store_true", default=False)
parser.add_argument("--use-energy", help="compare energy values (default)", action="store_true", default=False)
parser.add_argument("--use-power", help="compare power values", action="store_true", default=False)
parser.add_argument("--use-samples", help="compare sample counters", action="store_true", default=False)
parser.add_argument("--use-exec-times", help="compare execution time", action="store_true", default=False)
parser.add_argument("-e", "--error", help=f"error function (default: {errorFunctions[0][0]})", default=False, choices=errorFunctions[:, 0], type=str.lower)
parser.add_argument("-a", "--aggregate", help="aggregate erros", default=False, choices=aggregateFunctions[:, 0], type=str.lower)
parser.add_argument("-c", "--compensation", help="switch on latency compensation (experimental)", action="store_true", default=False)
parser.add_argument("--limit-time-top", help="include top n entries ranked after time", type=int, default=0)
parser.add_argument("--limit-time", help="include top entries until limit (in percent, e.g. 0.0 - 1.0)", type=float, default=0)
parser.add_argument("--time-threshold", help="time contribution threshold to include (in percent, e.g. 0.0 - 1.0)", type=float, default=0)
parser.add_argument("--limit-energy-top", help="include top n entries ranked after energy", type=int, default=0)
parser.add_argument("--limit-energy", help="include top entries until limit (in percent, e.g. 0.0 - 1.0)", type=float, default=0)
parser.add_argument("--exclude-kernel", help="exclude kernel symbols from comparison", action="store_true", default=False)
parser.add_argument("--exclude-foreign", help="exclude foreign symbols from comparison", action="store_true", default=False)
parser.add_argument("--exclude-unknown", help="exclude unknown symbols from comparison", action="store_true", default=False)
parser.add_argument("--energy-threshold", help="energy contribution threshold (in percent, e.g. 0.0 - 1.0)", type=float, default=0)
parser.add_argument('--names', help='names of the provided profiles (comma sepperated)', type=str, default=False)
parser.add_argument('-n', '--name', action='append', help='name the provided profiles', default=[])
parser.add_argument("-t", "--table", help="output csv table")
parser.add_argument("-p", "--plot", help="plotly html file")
parser.add_argument("--coverage", action="store_true", help="output coverage", default=False)
parser.add_argument("--totals", action="store_true", help="output total", default=False)
parser.add_argument("--weights", action="store_true", help="output importance", default=False)
parser.add_argument("-q", "--quiet", action="store_true", help="do not automatically open plot file", default=False)
parser.add_argument("--export", help="export plot (pdf, svg, png,...)")
parser.add_argument("--width", help="export width", type=int, default=1500)
parser.add_argument("--height", help="export height", type=int)
parser.add_argument("--cut-off-symbols", help="number of characters symbol to insert line break (positive) or cut off (negative)", type=int, default=64)


args = parser.parse_args()

if (not args.use_time and not args.use_energy and not args.use_power and not args.use_samples and not args.use_exec_times):
    args.use_time = True

if (len(args.name) == 0 and args.names is not False):
    args.name = args.names.split(',')

header = ""

cmpTime = 0
cmpPower = 1
cmpEnergy = 2
cmpRelSamples = 3
cmpExecs = 4

cmpOffset = cmpEnergy
if args.use_time:
    header = "Time "
    cmpOffset = cmpTime
if args.use_power:
    header = "Power "
    cmpOffset = cmpPower
if args.use_samples:
    header = "Relative Samples "
    cmpOffset = cmpRelSamples
if args.use_exec_times:
    header = "Execution Times "
    cmpOffset = cmpExecs
if args.use_energy:
    header = "Energy "
    cmpOffset = cmpEnergy

if (args.limit_time is not 0 or args.limit_time_top is not 0) and (args.limit_energy is not 0 or args.limit_energy_top is not 0):
    print("ERROR: cannot simultanously limit after energy and time!")
    parser.print_help()
    sys.exit(1)


if args.limit_time_top is not 0 and args.limit_time_top < 0:
    print("ERROR: time limit top can't be negative")
    parser.print_help()
    sys.exit(0)

if (args.limit_time is not 0 and (args.limit_time < 0 or args.limit_time > 1.0)):
    print("ERROR: time limit out of range")
    parser.print_help()
    sys.exit(0)

if args.limit_energy_top is not 0 and args.limit_energy_top < 0:
    print("ERROR: energy limit top can't be negative")
    parser.print_help()
    sys.exit(0)

if (args.limit_energy is not 0 and (args.limit_energy < 0 or args.limit_energy > 1.0)):
    print("ERROR: energy limit out of range")
    parser.print_help()
    sys.exit(0)

if (args.time_threshold is not 0 and (args.time_threshold < 0 or args.time_threshold > 1.0)):
    print("ERROR: time threshold out of range")
    parser.print_help()
    sys.exit(0)

if (args.energy_threshold is not 0 and (args.energy_threshold < 0 or args.energy_threshold > 1.0)):
    print("ERROR: energy threshold out of range")
    parser.print_help()
    sys.exit(0)

if (args.quiet and not args.plot and not args.table and not args.export):
    print("ERROR: don't know what to do")
    parser.print_help()
    sys.exit(1)

if (not args.profiles) or (len(args.profiles) <= 0):
    print("ERROR: unsufficient amount of profiles passed")
    parser.print_help()
    sys.exit(1)


if args.profile.endswith(".bz2"):
    baselineProfile = pickle.load(bz2.BZ2File(args.profile, mode="rb"))
else:
    baselineProfile = pickle.load(open(args.profile, mode="rb"))

if 'version' not in baselineProfile or baselineProfile['version'] != profileLib.aggProfileVersion:
    raise Exception(f"Incompatible profile version (required: {profileLib.aggProfileVersion})")

errorFunction = False
aggregateFunction = False

if args.aggregate is not False:
    chosenAggregateFunction = aggregateFunctions[numpy.where(aggregateFunctions == args.aggregate)[0][0]]
    aggregateFunction = chosenAggregateFunction[2]

if args.aggregate is not False and not chosenAggregateFunction[3] and args.error is not False:
    print(f"NOTICE: error function does not have an influence on '{chosenAggregateFunction[1]}'")
    args.error = False

if args.error is False and args.aggregate is False:  # default value
    args.error = errorFunctions[0][0]

if args.error is not False:
    chosenErrorFunction = errorFunctions[numpy.where(errorFunctions == args.error)[0][0]]
    errorFunction = chosenErrorFunction[2]

chart = {'name': '', 'fullTotals': [0.0, 0.0, 0.0, 0.0, 0.0], 'totals': [0.0, 0.0, 0.0, 0.0, 0.0], 'keys': [], 'labels': [], 'values': [], 'errors': [], 'weights': []}
baselineChart = copy.deepcopy(chart)
baselineChart['name'] = f"{baselineProfile['samples'] / baselineProfile['samplingTime']:.2f} Hz, {baselineProfile['samplingTime']:.2f} s, {baselineProfile['latencyTime'] * 1000000 / baselineProfile['samples']:.2f} us"

if (args.limit_energy is not 0 or args.limit_energy_top is not 0):
    baselineProfile['profile'] = collections.OrderedDict(sorted(baselineProfile['profile'].items(), key=lambda x: operator.itemgetter(profileLib.aggEnergy)(x[1]), reverse=True))
else:
    baselineProfile['profile'] = collections.OrderedDict(sorted(baselineProfile['profile'].items(), key=lambda x: operator.itemgetter(profileLib.aggTime)(x[1]), reverse=True))


for key in baselineProfile['profile']:
    baselineChart['fullTotals'][cmpTime] += baselineProfile['profile'][key][profileLib.aggTime]
    baselineChart['fullTotals'][cmpEnergy] += baselineProfile['profile'][key][profileLib.aggEnergy]
    baselineChart['fullTotals'][cmpExecs] += baselineProfile['profile'][key][profileLib.aggExecs]
baselineChart['fullTotals'][cmpRelSamples] = 1
baselineChart['fullTotals'][cmpPower] = (baselineChart['fullTotals'][cmpEnergy] / baselineChart['fullTotals'][cmpTime])


chart = {'name': '', 'fullTotals': [0.0, 0.0, 0.0, 0.0, 0.0], 'totals': [0.0, 0.0, 0.0, 0.0, 0.0], 'values': [], 'errors': [], 'weights': []}
errorCharts = [copy.deepcopy(chart) for x in args.profiles]

includedBaselineTime = 0.0
includedBaselineEnergy = 0.0
includedKeys = 0

i = 1
for index, errorChart in enumerate(errorCharts):
    print(f"Compare profile {i}/{len(args.profiles)}...\r", end="")
    i += 1

    if args.profiles[index].endswith(".bz2"):
        profile = pickle.load(bz2.BZ2File(args.profiles[index], mode="rb"))
    else:
        profile = pickle.load(open(args.profiles[index], mode="rb"))

    if 'version' not in profile or profile['version'] != profileLib.aggProfileVersion:
        raise Exception(f"Incompatible profile version (required: {profileLib.aggProfileVersion})")

    if len(args.name) > index:
        errorCharts[index]['name'] = args.name[index]
    else:
        errorCharts[index]['name'] = f"{profile['samples'] / profile['samplingTime']:.2f} Hz, {profile['samplingTime']:.2f} s"

    for key in profile['profile']:
        errorChart['fullTotals'][cmpTime] += profile['profile'][key][profileLib.aggTime]
        errorChart['fullTotals'][cmpEnergy] += profile['profile'][key][profileLib.aggEnergy]
        errorChart['fullTotals'][cmpExecs] += profile['profile'][key][profileLib.aggExecs]
    errorChart['fullTotals'][cmpRelSamples] = 1
    errorChart['fullTotals'][cmpPower] = (errorChart['fullTotals'][cmpEnergy] / errorChart['fullTotals'][cmpTime])

    for key in baselineProfile['profile']:
        if key in profile['profile']:
            # Key never seen before, so add it to the baseline and all charts
            if key not in baselineChart['keys']:
                # Key was never compared before, check thresholds and limitations whether to include or not
                if (
                        (args.exclude_kernel and key.startswith(profileLib.LABEL_KERNEL)) or
                        (args.exclude_foreign and key.startswith(profileLib.LABEL_FOREIGN)) or
                        (args.exclude_unknown and key.startswith(profileLib.LABEL_UNKNOWN)) or
                        ((args.limit_time_top is not 0) and (includedKeys >= args.limit_time_top)) or
                        ((args.limit_energy_top is not 0) and (includedKeys >= args.limit_energy_top)) or
                        ((args.limit_time is not 0) and ((includedBaselineTime / baselineChart['fullTotals'][cmpTime]) >= args.limit_time)) or
                        ((args.limit_energy is not 0) and ((includedBaselineEnergy / baselineChart['fullTotals'][cmpEnergy]) >= args.limit_energy)) or
                        ((args.time_threshold is not 0) and ((baselineProfile['profile'][key][profileLib.aggTime] / baselineChart['fullTotals'][cmpTime]) < args.time_threshold)) or
                        ((args.energy_threshold is not 0) and ((baselineProfile['profile'][key][profileLib.aggEnergy] / baselineChart['fullTotals'][cmpEnergy]) < args.energy_threshold))
                ):
                    continue
                baselineChart['keys'].append(key)
                baselineChart['labels'].append(baselineProfile['profile'][key][profileLib.aggLabel])
                baselineChart['values'].append([
                    baselineProfile['profile'][key][profileLib.aggTime],     # time
                    baselineProfile['profile'][key][profileLib.aggPower],    # power
                    baselineProfile['profile'][key][profileLib.aggEnergy],   # energy
                    baselineProfile['profile'][key][profileLib.aggSamples] / baselineProfile['samples'],  # relSamples
                    baselineProfile['profile'][key][profileLib.aggTime] / baselineProfile['profile'][key][profileLib.aggExecs]  # execTimes
                ])
                includedBaselineTime += baselineProfile['profile'][key][profileLib.aggTime]
                includedBaselineEnergy += baselineProfile['profile'][key][profileLib.aggEnergy]
                includedKeys += 1
                # print(f'include {key} with now beeing at {includedBaselineTime / baselineChart["fullTotals"][cmpTime]:.3f} time and {includedBaselineEnergy / baselineChart["fullTotals"][cmpEnergy]:.3f} energy')
                for chart in errorCharts:
                    chart['values'].append([0.0, 0.0, 0.0, 0.0, 0.0])

            # Index of the key correlates to the errorChart (same order)
            keyIndex = baselineChart['keys'].index(key)
            errorChart['values'][keyIndex] = [
                profile['profile'][key][profileLib.aggTime],
                profile['profile'][key][profileLib.aggPower],
                profile['profile'][key][profileLib.aggEnergy],
                profile['profile'][key][profileLib.aggSamples] / profile['samples'],
                profile['profile'][key][profileLib.aggTime] / profile['profile'][key][profileLib.aggExecs]
            ]
            # Totals are the totals of only comparable keys
            errorChart['totals'][cmpTime] += profile['profile'][key][profileLib.aggTime]
            errorChart['totals'][cmpEnergy] += profile['profile'][key][profileLib.aggEnergy]
            errorChart['totals'][cmpExecs] += profile['profile'][key][profileLib.aggTime] / profile['profile'][key][profileLib.aggExecs]
        # fullTotals are the metrics of all profile keys

    # These can be calculated afterwards
    errorChart['totals'][cmpPower] = (errorChart['totals'][cmpEnergy] / errorChart['totals'][cmpTime]) if errorChart['totals'][cmpTime] != 0 else 0
    errorChart['totals'][cmpRelSamples] = 1

    del profile

if len(baselineChart['keys']) == 0:
    raise Exception("Nothing found to compare, limit too strict?")

# calculate baseline total
values = numpy.array(baselineChart['values'])
baselineChart['totals'] = [
    numpy.sum(values[:, 0]),
    0.0,
    numpy.sum(values[:, 2]),
    1,
    numpy.sum(values[:, 4])
]
baselineChart['totals'][cmpPower] = (baselineChart['totals'][cmpEnergy] / baselineChart['totals'][cmpTime]) if baselineChart['totals'][cmpTime] != 0 else 0
baselineChart['totals'][cmpRelSamples] = 1
del values

# fill in the weights, based on baseline energy
for index, _ in enumerate(baselineChart['keys']):
    for chart in errorCharts:
        if args.limit_energy:
            chart['weights'].append(chart['values'][index][cmpEnergy] / baselineChart['fullTotals'][cmpEnergy])
        else:
            chart['weights'].append(chart['values'][index][cmpTime] / baselineChart['fullTotals'][cmpTime])

# fill in the errors
if errorFunction is not False:
    for index, _ in enumerate(baselineChart['keys']):
        for chart in errorCharts:
            chart['errors'].append(errorFunction(baselineChart['values'][index][cmpOffset], chart['values'][index][cmpOffset], baselineChart['totals'][cmpOffset], chart['totals'][cmpOffset], chart['weights'][index]))

# names = [ key, name1, name2, name3, name4 ]
# values = [ key, error1, error2, error3, error4 ]a
#


if aggregateFunction:
        header += f"{chosenAggregateFunction[1]} "
if errorFunction:
        header += f"{chosenErrorFunction[1]}"
header = header.strip()


if errorFunction is not False and aggregateFunction is False:
    headers = numpy.array([chart['name'] for chart in errorCharts])
    rows = numpy.array(baselineChart['labels']).reshape(-1, 1)
    weights = numpy.empty((rows.shape[0], 0))
    barLabels = numpy.empty((rows.shape[0], 0))
    for chart in errorCharts:
        rows = numpy.append(rows, numpy.array(chart['errors']).reshape(-1, 1), axis=1)
        weights = numpy.append(weights, numpy.array(chart['weights']).reshape(-1, 1), axis=1)
        barLabels = numpy.append(barLabels, numpy.array(chart['weights']).reshape(-1, 1), axis=1)  # weights
        # barLabels = numpy.append(barLabels, chartValues[:, 4].reshape(-1, 1), axis=1) # execTimes
    try:
        # Try to sort after numeric values
        asort = numpy.array(rows[:, 1], dtype=float).argsort()
    except Exception:
        asort = rows[:, 1].argsort()
    rows = rows[asort]
    weights = weights[asort]
    barLabels = barLabels[asort]

if aggregateFunction is not False:
    baselineValues = numpy.array(baselineChart['values'])
    rows = numpy.array([chart['name'] for chart in errorCharts], dtype=object).reshape(-1, 1)
    barLabels = numpy.array([''] * len(rows)).reshape(1, -1)
    errors = numpy.empty(0)
    for chart in errorCharts:
        chartValues = numpy.array(chart['values'])
        errors = numpy.append(errors, aggregateFunction(
            baselineValues[:, cmpOffset],
            chart['errors'] if errorFunction is not False else chartValues[:, cmpOffset],
            baselineChart['totals'][cmpOffset],
            chart['totals'][cmpOffset],
            chart['weights']
        ))
    rows = numpy.append(rows, errors.reshape(-1, 1), axis=1)
    headers = numpy.array([header], dtype=object)

if (args.plot or args.export):
    import plotly
    import plotly.graph_objs as go
    import plotlyExport
    plotly.io.templates.default = 'plotly_white'

    fig = {'data': []}
    if (args.cut_off_symbols > 0):
        pAggregationLabel = [textwrap.fill(x, args.cut_off_symbols).replace('\n', '<br />') for x in rows[:, 0]]
        leftMargin = min(abs(args.cut_off_symbols), numpy.max([len(x) for x in rows[:, 0]]))
    elif (args.cut_off_symbols < 0):
        pAggregationLabel = [f"{x[0:abs(args.cut_off_symbols)]}..." if len(x) > abs(args.cut_off_symbols) else x for x in rows[:, 0]]
        leftMargin = min(abs(args.cut_off_symbols) + 3, numpy.max([len(x) for x in rows[:, 0]]))
    else:
        pAggregationLabel = rows[:, 0]
        leftMargin = numpy.max([len(x) for x in pAggregationLabel])

    indices = [i for i, _ in enumerate(rows[:, 0])]

    for index, name in enumerate(headers):
        pBarLabels = [(f'{t * 100:.2f}%' if isinstance(t, float) else t) for t in barLabels[:, index]]
        fig["data"].append(
            go.Bar(
                y=indices,
                x=rows[:, (index + 1)],
                name=name,
                text=pBarLabels,
                textposition='auto',
                orientation='h',
                hoverinfo='name+x' if aggregateFunction is False else 'y+x'
            )
        )

    fig['layout'] = go.Layout(
        title=go.layout.Title(
            text=f"{header}, {baselineProfile['name']}, Frequency {baselineProfile['samples'] / baselineProfile['samplingTime']:.2f} Hz, Time {baselineProfile['samplingTime']:.2f} s, Energy {baselineChart['fullTotals'][cmpEnergy]:.2f} J, Latency {baselineProfile['latencyTime'] * 1000000 / baselineProfile['samples']:.2f} us",
            xref='paper',
            x=0
        ),
        xaxis=go.layout.XAxis(
            title=go.layout.xaxis.Title(
                text=header,
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
            tickvals=indices
        ),
        legend=go.layout.Legend(traceorder="reversed"),
        margin=go.layout.Margin(l=10 + (7.00 * leftMargin))
    )
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


if (args.table or not args.quiet):
    if aggregateFunction is False:
        if args.totals:
            total = ['_total']
            for i in range(1, len(rows[0])):
                total = numpy.append(total, numpy.sum(numpy.array(rows[:, (i)], dtype=float)))
            weights = numpy.concatenate(([[0] * (len(total) - 1)], weights), axis=0)
            rows = numpy.concatenate(([total], rows), axis=0)
        if args.coverage:
            coverage = ['_coverage']
            coverage.extend([chart['totals'][cmpOffset] / chart['fullTotals'][cmpOffset] if chart['fullTotals'][cmpOffset] != 0 else 0 for chart in errorCharts])
            weights = numpy.concatenate(([[0] * (len(coverage) - 1)], weights), axis=0)
            rows = numpy.concatenate(([coverage], rows), axis=0)
        if args.weights:
            for i in range(0, len(rows[0]) - 1):
                headers = numpy.insert(headers, (i * 2), 'Weights')
                rows = numpy.insert(rows, (i * 2) + 1, weights[:, i], axis=1)
    else:
        header = "Profile"
        rows = rows[::-1]

if (args.table):
    if args.table.endswith("bz2"):
        table = bz2.BZ2File.open(args.table, "w")
    else:
        table = open(args.table, "w")
    table.write(header + ";" + ';'.join(headers) + "\n")
    for i, x in enumerate(rows):
        table.write(';'.join([f"{y:.16f}" if not isinstance(y, str) else y for y in x]) + "\n")
    table.close()
    print(f"CSV saved to {args.table}")

if (not args.quiet):
    headers = numpy.append([header], headers)
    if (args.cut_off_symbols > 0):
        rows[:, 0] = [textwrap.fill(x, args.cut_off_symbols) for x in rows[:, 0]]
    elif (args.cut_off_symbols < 0):
        rows[:, 0] = [f"{x[0:abs(args.cut_off_symbols)]}..." if len(x) > abs(args.cut_off_symbols) else x for x in rows[:, 0]]
    print(tabulate.tabulate(rows, headers=headers, floatfmt=".16f"))
