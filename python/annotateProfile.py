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
import copy
from xopen import xopen

tabulate.PRESERVE_WHITESPACE = True

aggregateDefault = [profileLib.SAMPLE.names[profileLib.SAMPLE.binary], profileLib.SAMPLE.names[profileLib.SAMPLE.function]]

parser = argparse.ArgumentParser(description="Annotate profiles on asm and source level.")
parser.add_argument("profiles", help="postprocessed profiles from pperf", nargs="+")
parser.add_argument("--mode", choices=['mean', 'add'], default='mean', help=f"compute mean profiles or accumulated profiles (default: %(default)s)")
parser.add_argument("--annotate", choices=['asm', 'source'], default='asm', help=f"what to annotate (default: %(default)s)")

#parser.add_argument("-a", "--aggregate", help=f"aggregate symbols (default: %{', '.join(aggregateDefault)}s)", choices=profileLib.SAMPLE.names, nargs="+", default=[])
#parser.add_argument("-d", "--delimiter", help=f"aggregate symbol delimiter (default '%(default)s')", default=":")
#parser.add_argument("-ea", "--external-aggregate", help=f"aggregate external symbols (default: %{', '.join(aggregateDefault)}s)", choices=profileLib.SAMPLE.names, nargs="+", default=[])
#parser.add_argument("-ed", "--external-delimiter", help=f"delimiter for external symbols (default: ':')", default=None)

parser.add_argument("--share", default=False, action="store_true" , help="display metirc shares")
parser.add_argument("--no-share", default=False, action="store_true" , help="hide metric shares (default)")
parser.add_argument("-s", "--show", choices=['time', 'energy', 'samples'], default=['time', 'samples'], nargs="+", help="show time, energy and/or samples")

parser.add_argument("--binary-time-threshold", type=float, help="include binaries with at least this runtime (default %(default)s)", default=0)
parser.add_argument("--binary-energy-threshold", type=float, help="include binaries with at least this energy consumption (default %(default)s)", default=0)
parser.add_argument("--binary-sample-threshold", type=float, help="include binaries with at least this many samples (default %(default)s)", default=0)

parser.add_argument("--function-time-threshold", type=float, help="include functions with at least this runtime (default %(default)s)", default=0)
parser.add_argument("--function-energy-threshold", type=float, help="include functions with at least this energy consumption (default %(default)s)", default=0)
parser.add_argument("--function-sample-threshold", type=float, help="include functions with at least this many samples (default %(default)s)", default=1)

parser.add_argument("--basicblock-time-threshold", type=float, help="include basicblocks with at least this runtime (default %(default)s)", default=0)
parser.add_argument("--basicblock-energy-threshold", type=float, help="include basicblocks with at least this energy consumption (default %(default)s)", default=0)
parser.add_argument("--basicblock-sample-threshold", type=float, help="include basicblocks with at least this many samples (default %(default)s)", default=0)

parser.add_argument("--instruction-time-threshold", type=float, help="include instructions with at least this runtime (default %(default)s)", default=0)
parser.add_argument("--instruction-energy-threshold", type=float, help="include instructions with at least this energy consumption (default %(default)s)", default=0)
parser.add_argument("--instruction-sample-threshold", type=float, help="include instructions with at least this many samples (default %(default)s)", default=0)

parser.add_argument("--level", choices=['binary', 'function', 'instruction'], default='instruction', help="until which level to output")
parser.add_argument("--external-level", choices=['binary', 'function', 'instruction'], default='instruction', help="until which level to output for external binaries")

#parser.add_argument("--exclude-binary", help="exclude these binaries", default=[], action="append")
#parser.add_argument("--exclude-file", help="exclude these files", default=[], action="append")
#parser.add_argument("--exclude-function", help="exclude these functions", default=[], action="append")
#parser.add_argument("--exclude-external", help="exclude external binaries", default=False, action="store_true")

parser.add_argument("--less-memory", help="opens only one input profile at a time", action="store_true", default=False)
#parser.add_argument("-t", "--table", help="output csv table")
parser.add_argument("-o", "--output", help="output annotated profile")
#parser.add_argument("--cut-off-symbols", help="number of characters symbol to insert line break (positive) or cut off (negative)", type=int, default=64)
parser.add_argument("--account-latency", action="store_true", help="substract latency")
parser.add_argument("--use-wall-time", action="store_true", help="use sample wall time")
parser.add_argument("--use-cpu-time", action="store_true", help="use cpu time (default)")
parser.add_argument("-q", "--quiet", help="do not print annotated profile", default=False, action="store_true")


args = parser.parse_args()

if not args.share and not args.no_share:
    args.share = False

if args.share:
    args.no_share = False

if args.annotate == 'source':
    raise Exception('source annotation is currently not supported, coming soon...')


if (args.quiet and not args.output):
    print("ERROR: don't know what to do")
    parser.print_help()
    sys.exit(1)

if (not args.profiles) or (len(args.profiles) <= 0):
    print("ERROR: unsufficient amount of profiles passed")
    parser.print_help()
    sys.exit(1)

args.show = list(dict.fromkeys(args.show))

inputProfiles = []
cacheMap = {}

annotatedProfile = None

for i, fileProfile in enumerate(args.profiles):
    try:
        profile = pickle.load(xopen(fileProfile, mode="rb"))
    except:
        raise Exception(f'Could not read file {fileProfile}')

    if i == 0 and len(args.profiles) == 1 and 'version' in profile and profile['version'] == profileLib.annProfileVersion:
        annotatedProfile = profile
        if args.use_cpu_time or args.use_wall_time:
            print('WARNING: --use-cpu-time and --use-wall-time have only an effect on annotating full profiles')
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
    if not args.use_cpu_time and not args.use_wall_time:
        args.use_cpu_time = True

    modeFac = 1
    if args.mode == 'mean':
        modeFac /= len(inputProfiles)
   
    # aggregateKeys = [profileLib.SAMPLE.binary, profileLib.SAMPLE.file, profileLib.SAMPLE.function, profileLib.SAMPLE.pc]
    annotatedProfile = {
        'version': profileLib.annProfileVersion,
        'samples': 0,
        'samplingTime': 0,
        'latencyTime': 0,
        'asm': {},
        'source': {},
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

    print('Reading in assembly and source', flush=True, file=sys.stderr)
    asm = pandas.concat([pandas.DataFrame(cache['cache'].values(), columns=['pc', 'binary', 'file', 'function', 'basicblock', 'line', 'instruction', 'meta']).drop(['meta'], axis=1) for cache in caches.values()], ignore_index=True)
    asm['args'] = asm.apply(lambda r: '' if '\t' not in caches[r['binary']]['asm'][r['pc']] else caches[r['binary']]['asm'][r['pc']].split('\t', 1)[1].replace('\t',' '), axis=1)
    source = pandas.concat([pandas.DataFrame({'binary': b, 'file': f, 'line': range(1, len(caches[b]['source'][f])+1), 'source' : caches[b]['source'][f]}) for b in caches for f in caches[b]['source'] if caches[b]['source'][f] is not None], ignore_index=True)

    aggregate = {}

    for i, profile in enumerate(inputProfiles):
        print(f'\rParsing profile {i+1}/{len(inputProfiles)}... ', flush=True, file=sys.stderr)
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

                aggregate[binary][pc][0] += time * modeFac
                aggregate[binary][pc][1] += energy * modeFac
                aggregate[binary][pc][2] += 1 * modeFac

            prevSampleWallTime = sample[1]
        del profile
        gc.collect()

    print('Correlating data', flush=True, file=sys.stderr)
    asm[['time', 'energy', 'samples']] = asm.apply(lambda r: aggregate[r['binary']][r['pc']] if r['binary'] in aggregate and r['pc'] in aggregate[r['binary']] else [0, 0, 0], axis=1, result_type='expand')
    source = source.join(asm.groupby(['binary', 'file', 'line'], as_index=False)[['time','energy','samples']].sum().set_index(['binary', 'file', 'line']), on=['binary', 'file', 'line'])
    print('Cleaning up', flush=True, file=sys.stderr)

    # Fill in 0 values for time, energy and samples
    asm[['line', 'time', 'energy', 'samples']] = asm[['line', 'time', 'energy', 'samples']].fillna(0)
    source[['time', 'energy', 'samples']] = source[['time', 'energy', 'samples']].fillna(0)

    # Line must be object
    annotatedProfile['asm'] = asm.astype({'pc': 'uint64', 'binary': 'object', 'file': 'object', 'function': 'object', 'basicblock': 'object', 'line': 'uint64', 'instruction': 'object', 'args': 'object', 'time': 'float64', 'energy': 'float64', 'samples': 'float64'})
    annotatedProfile['source'] = source.astype({'binary': 'object', 'file': 'object', 'line': 'uint64', 'source': 'object', 'time': 'float64', 'energy': 'float64', 'samples': 'uint64'})

    del aggregate
    del inputProfiles

    gc.collect()

if (args.output):
    output = xopen(args.output, "wb")
    pickle.dump(annotatedProfile, output)
    print(f"Annotated profile saved to {args.output}", flush=True, file=sys.stderr)


if args.quiet:
    exit(0)


asm = annotatedProfile['asm']
source = annotatedProfile['source']

if args.binary_time_threshold > 0:
    asm = asm[asm.groupby(['binary'])['time'].transform('sum') >= args.binary_time_threshold]
    source = source[source.groupby(['binary'])['time'].transform('sum') >= args.binary_time_threshold]
if args.binary_energy_threshold > 0:
    asm = asm[asm.groupby(['binary'])['energy'].transform('sum') >= args.binary_energy_threshold]
    source = source[source.groupby(['binary'])['energy'].transform('sum') >= args.binary_energy_threshold]
if args.binary_sample_threshold > 0:
    asm = asm[asm.groupby(['binary'])['samples'].transform('sum') >= args.binary_sample_threshold]
    source = source[source.groupby(['binary'])['samples'].transform('sum') >= args.binary_sample_threshold]

if args.function_time_threshold > 0:
    asm = asm[asm.groupby(['binary', 'function'])['time'].transform('sum') >= args.function_time_threshold]
if args.function_energy_threshold > 0:
    asm = asm[asm.groupby(['binary', 'function'])['energy'].transform('sum') >= args.function_energy_threshold]
if args.function_sample_threshold > 0:
    asm = asm[asm.groupby(['binary', 'function'])['samples'].transform('sum') >= args.function_sample_threshold]

if args.basicblock_time_threshold > 0:
    asm = asm[asm.groupby(['binary', 'function', 'basicblock'])['time'].transform('sum') >= args.basicblock_time_threshold]
if args.basicblock_energy_threshold > 0:
    asm = asm[asm.groupby(['binary', 'function', 'basicblock'])['energy'].transform('sum') >= args.basicblock_energy_threshold]
if args.basicblock_sample_threshold > 0:
    asm = asm[asm.groupby(['binary', 'function', 'basicblock'])['samples'].transform('sum') >= args.basicblock_sample_threshold]

if args.instruction_time_threshold > 0:
    asm = asm[asm.groupby(['binary', 'pc'])['time'].transform('sum') >= args.instruction_time_threshold]
if args.instruction_energy_threshold > 0:
    asm = asm[asm.groupby(['binary', 'pc'])['energy'].transform('sum') >= args.instruction_energy_threshold]
if args.instruction_sample_threshold > 0:
    asm = asm[asm.groupby(['binary', 'pc'])['samples'].transform('sum') >= args.instruction_sample_threshold]

order = asm.groupby(['binary', 'function'])['samples'].sum().sort_values(ascending=False).reset_index()

pandas.options.mode.chained_assignment = None
asm['pc'] = asm['pc'].apply('0x{:x}'.format)

columns = (((['_tshare_' + x for x in args.show]) + (['_bshare_' + x for x in args.show]) + (['_fshare_' + x for x in args.show])) if args.share else []) + args.show + ['pc', 'basicblock', 'instruction', 'args']

shareFloatFmt = "3.2f"
columnNames = {'time': 'Time [s]', 'energy': 'Energy [J]', 'samples': 'Samples #'}
columnFmts = {'time' : '10.4f', 'energy' : '10.4f', 'samples' : '10.0f'}
stats = { 'time' : annotatedProfile['asm']['time'].sum(), 'energy': annotatedProfile['asm']['energy'].sum(), 'samples': annotatedProfile['asm']['samples'].sum()}

# print('=' * 80)
print(tabulate.tabulate([
    [(stats[x]) for x in args.show]
    + ['Total']
], tablefmt="simple", headers=[columnNames[x] for x in args.show] + [''], floatfmt=[columnFmts[x] for x in args.show]))

print('')

for bi, binary in enumerate(order['binary'].unique()):
    bAsm = asm[asm['binary'] == binary]
    bTotalAsm = annotatedProfile['asm'][annotatedProfile['asm']['binary'] == binary]
    bStats = { 'time' : bTotalAsm['time'].sum(), 'energy': bTotalAsm['energy'].sum(), 'samples': bTotalAsm['samples'].sum() }

    print(tabulate.tabulate([
        ([(bStats[x] * 100 / stats[x]) for x in args.show] if args.share else [])
        + [(bStats[x]) for x in args.show]
        + [binary]
    ], tablefmt="simple", headers=(['(%)'] * len(args.show) if args.share else []) + [columnNames[x] for x in args.show] + [''], floatfmt=([shareFloatFmt] * len(args.show) if args.share else []) + [columnFmts[x] for x in args.show], showindex=False))
    print('')

    if binary == annotatedProfile['target'] and args.level == 'binary':
        continue
    if binary != annotatedProfile['target'] and args.external_level == 'binary':
        continue
    for fi, function in enumerate(order[order['binary'] == binary]['function'].unique()):
        fAsm = asm[(asm['binary'] == binary) & (asm['function'] == function)]
        fTotalAsm = annotatedProfile['asm'][(annotatedProfile['asm']['binary'] == binary) & (annotatedProfile['asm']['function'] == function)]
        fStats = { 'time' : fTotalAsm['time'].sum(), 'energy': fTotalAsm['energy'].sum(), 'samples': fTotalAsm['samples'].sum() }

        print(tabulate.tabulate([
            ([(fStats[x] * 100 / stats[x]) for x in args.show] if args.share else [])
            + ([(fStats[x] * 100 / bStats[x]) for x in args.show] if args.share else [])
            + [(fStats[x]) for x in args.show] + [function]
        ], tablefmt="simple", headers=(['(%)'] * 2 * len(args.show) if args.share else []) + [columnNames[x] for x in args.show] + [''], floatfmt=([shareFloatFmt] * 2 * len(args.show) if args.share else []) + [columnFmts[x] for x in args.show], showindex=False))
        print('')

        if binary == annotatedProfile['target'] and args.level == 'function':
            continue
        if binary != annotatedProfile['target'] and args.external_level == 'function':
            continue

        if args.share:
            for x in args.show:
                fAsm['_tshare_' + x] = fAsm.apply(lambda r: r[x] * 100 / stats[x], axis=1)
                fAsm['_bshare_' + x] = fAsm.apply(lambda r: r[x] * 100 / bStats[x], axis=1)
                fAsm['_fshare_' + x] = fAsm.apply(lambda r: r[x] * 100/ fStats[x], axis=1)

        fAsm = fAsm.replace({'basicblock': r'^f[0-9]+b'}, {'basicblock': ''}, regex=True)
        print(tabulate.tabulate(fAsm[columns], tablefmt='simple', headers = ((['(%)'] * 3 * len(args.show)) if args.share else []) + [columnNames[x] for x in args.show] + ['Addr', 'BB', 'Instr', 'Asm'], floatfmt=([shareFloatFmt] * 3 * len(args.show) if args.share else []) + [columnFmts[x] for x in args.show], showindex=False))
        print('')

exit(0)
