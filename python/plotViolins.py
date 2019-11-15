#!/usr/bin/env python

import sys
import argparse
import plotly
import plotly.graph_objects as go
import numpy
import pandas
import collections
import statistics
import os

plotly.io.templates.default = 'plotly_white'

if os.path.exists('/opt/plotly-orca/orca'):
    plotly.io.orca.config.executable = '/opt/plotly-orca/orca'

parser = argparse.ArgumentParser(description="Visualize compared csv profiles with weights")
parser.add_argument("profiles", help="compared profiles with weights", nargs="+")
parser.add_argument('--points', choices=['none', 'outliers', 'all'], default='none')
parser.add_argument("--means", action="store_true", help="show mean values", default=False)
parser.add_argument("--boxes", action="store_true", help="show integrated box diagram", default=False)
parser.add_argument("--asc", action="store_true", help="sort after mean ascending", default=False)
parser.add_argument("--desc", action="store_true", help="sort after mean descending", default=False)
parser.add_argument("-s", "--sharpness", help="violin sharpness (> 0)", type=int, default=1000)
parser.add_argument("-p", "--plot", help="plotly html file")
parser.add_argument("--export", help="export plot (pdf, svg, png,...)")
parser.add_argument("--width", help="export width", type=int, default=1500)
parser.add_argument("--height", help="export height", type=int)
parser.add_argument("-q", "--quiet", action="store_true", help="do not automatically open output file", default=False)

args = parser.parse_args()

if (not args.plot and not args.export):
    print("ERROR: don't know what to do")
    parser.print_help()
    sys.exit(1)

if (args.sharpness <= 0):
    print("ERROR: violin sharpness must be bigger than 0")
    parser.print_help()
    sys.exit(1)

if (args.export and args.points is not 'none'):
    print("WARNING: Export with points and high violin sharpnesses can be unstable")


if (not args.profiles) or (len(args.profiles) <= 0):
    print("ERROR: unsufficient amount of profiles passed")
    parser.print_help()
    sys.exit(1)

violins = {}

for profile in args.profiles:
    pddata = pandas.read_csv(profile, sep=';')
    columns = list(pddata.columns)
    weightIndex = columns.index('weights') if 'weights' in columns else columns.index('Weights') if 'Weights' in columns else False
    data = numpy.array([])
    dataColumn = ''
    if weightIndex is False:
        dataColumn = columns[1]
        data = pddata[columns[1]]
    else:
        weightColumn = columns[weightIndex]
        dataColumn = columns[weightIndex + 1]
        for _, row in pddata.iterrows():
            data = numpy.append(data, [row[dataColumn]] * max(1, int(args.sharpness * row[weightColumn])))

    violins[dataColumn] = data

if (args.asc or args.desc):
    violins = collections.OrderedDict(sorted(violins.items(), key=lambda x: statistics.mean(x[1]), reverse=True if args.desc else False))

fig = go.Figure()

index = 0
annotations = []
for violin in violins:
    # yposlist = tips.groupby(['day'])['total_bill'].median().tolist()
    # xposlist = range(len(yposlist))
    mean = statistics.mean(violins[violin])
    fig.add_trace(go.Violin(
        y=violins[violin],
        name=violin,
        box_visible=args.boxes,
        points=False if args.points is 'none' else args.points,
        pointpos=0,
        jitter=0,
        meanline_visible=True,
        line_color='rgba(60,80,158,0.6)',
        fillcolor='rgba(121, 162, 206, 1.0)'
    ))

    if args.means:
        annotations.append(go.layout.Annotation(x=index, y=mean, text=f'{mean:.2f}', ax=20))
    index += 1

fig.update_yaxes(rangemode="nonnegative")
if args.means:
    fig.update_layout(annotations=annotations)

if (args.export):
    go.Figure(fig).update_layout(showlegend=False, title=None, margin_t=0, margin_r=0, margin_l=0).write_image(args.export, width=args.width if args.width else None, height=args.height if args.height else None)
    print(f"Exported to {args.export}")

if (args.plot):
    plotly.offline.plot(fig, filename=args.plot, auto_open=not args.quiet)
    print(f"Plot saved to {args.plot}")
