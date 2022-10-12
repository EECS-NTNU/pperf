#!/usr/bin/env python3
#
import argparse
import csv
import profileLib
import sys
import os
import xopen
import fcntl

F_SETPIPE_SZ = 1031 if not hasattr(fcntl, "F_SETPIPE_SZ") else fcntl.F_SETPIPE_SZ
F_GETPIPE_SZ = 1032 if not hasattr(fcntl, "F_GETPIPE_SZ") else fcntl.F_GETPIPE_SZ

correlateSelectorNames = profileLib.SAMPLE.names.copy() + ['asm']
correlateSelector = ['binary', 'function', 'basicblock', 'line', 'instruction', 'asm']
correlateISelector = []

parser = argparse.ArgumentParser(description="Correlate address csv binary")
parser.add_argument("input", nargs="?", help="input csv")
parser.add_argument("-o", "--output", help="output csv", default=None)
parser.add_argument("-b", "--binary", help="correlate to this single binary (only static!)")
parser.add_argument("-v", "--vmmap", help="use vmmap to correlate binaries")
parser.add_argument("-s", "--search-path", help="search paths for vmmap binaries", default=[], type=str, nargs="+")
parser.add_argument("-ks", "--kallsyms", help="kernel symbols when using vmmap")
parser.add_argument("--selector", default=None, help=f"correlate selector (default: {' '.join(correlateSelector)})", type=str, nargs='+')
parser.add_argument("--address-column", help="specify the address columm name", type=str, default=None)
parser.add_argument("--address-icolumn", help="specify the address columm index", type=int, default=0)
parser.add_argument("--no-header", help="input file does not contain a header row", action="store_true", default=False)
parser.add_argument("--label-none", help="label unknown samples", default="_unknown")
parser.add_argument("--fill-addresses", help="fill addresses not seen in input", default=False, action="store_true")
parser.add_argument("--fill-columns", help="use this value for remaining columns when filling in addresses (default: '')", default='', type=str)
parser.add_argument("--filter-unknown", help="filter unknown addresses", default=False, action="store_true")
parser.add_argument("--only-filter-unknown", action="store_true", help="only filter addresses which are found in binary/vmmap", default=False)
parser.add_argument("--disable-cache", action="store_true", help="do not create or use prepared address caches", default=False)
parser.add_argument("--delimiter", default=';', help="correlate selector (default: '%(default)s')", type=str)


def selector(ilist):
    return [x for i, x in enumerate(ilist) if i in correlateISelector]


args = parser.parse_args()

if args.input and not os.path.exists(args.input):
    print("ERROR: csv input file not found!", file=sys.stderr)
    parser.print_help()
    sys.exit(1)

if (not args.binary and not args.vmmap):
    print("ERROR: either a static binary to correlate is required or a vmmap must be provided", file=sys.stderr)
    parser.print_help()
    sys.exit(1)

if args.binary and not os.path.isfile(args.binary):
    print("ERROR: binary not found!", file=sys.stderr)
    parser.print_help()
    sys.exit(1)

if args.vmmap and not os.path.isfile(args.vmmap):
    print("ERROR: vmmap not found!", file=sys.stderr)
    parser.print_help()
    sys.exit(1)

if args.kallsyms and (not os.path.isfile(args.kallsyms)):
    print("ERROR: kallsyms not found!", file=sys.stderr)
    parser.print_help()
    sys.exit(1)

if args.no_header and args.address_column:
    print("ERROR: cannot specify a address column without a header row in the file!", file=sys.stderr)
    parser.print_help()
    sys.exit(1)

if args.selector:
    if all(x == 'none' or x == '' for x in args.selector):
        correlateSelector = []
    else:
        args.selector = [x for x in args.selector if x != 'none' and x != '']
        if not all(x in correlateSelectorNames for x in args.selector):
            print(f"ERROR: could not find selectors {', '.join([x for x in args.selector if x not in correlateSelectorNames])}", file=sys.stderr)
            parser.print_help()
            sys.exit(1)
        correlateSelector = args.selector

if args.only_filter_unknown:
    correlateSelector = []
    args.filter_unknown = True

correlateISelector = [i for i, x in enumerate(correlateSelectorNames) if x in correlateSelector]
args.only_filter_unknown = len(correlateSelector) == 0

sampleParser = None
binaryCache = None

if args.disable_cache:
    profileLib.disableCache = True

if not args.binary:
    sampleParser = profileLib.sampleParser()
    sampleParser.addSearchPath(args.search_path)
    sampleParser.loadVMMap(args.vmmap)
    if args.kallsyms:
        sampleParser.loadKallsyms(args.kallsyms)
else:
    binaryCache = profileLib.elfCache()
    binaryCache.openOrCreateCache(args.binary)


if not args.input:
    try:
        fcntl.fcntl(sys.stdin.fileno(), F_SETPIPE_SZ, int(open("/proc/sys/fs/pipe-max-size", 'r').read()))
    except Exception:
        pass
    fInput = sys.stdin
else:
    fInput = xopen.xopen(args.input, 'r')

# dialectBuf = fInput.read(1024 * 1024)
# dialect = csv.Sniffer().sniff(io.StringIO(dialectBuf).read(1024 * 1024))
csvFile = csv.reader(fInput, delimiter=args.delimiter)

# del dialectBuf
# gc.collect()

if (args.output):
    outputFile = xopen.xopen(args.output, 'w')
    outputCsv = csv.writer(outputFile, delimiter=args.delimiter)
else:
    outputCsv = csv.writer(sys.stdout, delimiter=args.delimiter)

headerCol = args.address_icolumn
colCount = None

if not args.no_header:
    for header in csvFile:
        if header[0].startswith('#'):
            continue
        if args.address_column:
            if args.address_column not in header:
                print(f"ERROR: could not find column {args.address_column} in {args.input}")
                sys.exit(1)
            headerCol = header.index(args.address_column)
        if headerCol > len(header):
            print("ERROR: header column out of range")
            sys.exit(1)
        sample = profileLib.SAMPLE.names + ['asm']
        outputCsv.writerow(header[:headerCol + 1] + selector(sample) + header[headerCol + 1:])
        colCount = len(header)
        break

invalidSample = profileLib.SAMPLE.invalid.copy() + [None]

seenPCs = []

for line in csvFile:
    if line[0].startswith('#'):
        continue
    if colCount is None:
        colCount = len(line)

    pc = int(line[headerCol], 0)

    found = (sampleParser.isPCKnown(pc) and pc in sampleParser.cache.getCache(sampleParser.getBinaryFromPC(pc)['path'])['cache']) if sampleParser is not None else (pc in binaryCache.caches[args.binary]['cache'])

    if args.filter_unknown and not found:
        continue

    seenPCs.append(pc)

    if args.only_filter_unknown:
        outputCsv.writerow(line)
    else:
        if found:
            tCache = binaryCache.caches[args.binary] if sampleParser is None else sampleParser.cache.getCache(sampleParser.getBinaryFromPC(pc)['path'])
            sample = tCache['cache'][pc] + [tCache['asm'][pc]]
        else:
            sample = invalidSample

        outputCsv.writerow(line[:headerCol + 1] + [args.label_none if x is None else x for x in selector(sample)] + line[headerCol + 1:])

if args.fill_addresses:
    seenPCs = list(set(seenPCs))
    caches = []
    if colCount is None:
        colCount = headerCol
    if sampleParser is None :
        caches.append(binaryCache.caches[args.binary])
    else:
        for binary in sampleParser.binaries:
            sampleParser.cache.openOrCreateCache(binary['path'])
            caches.append(sampleParser.cache.caches[binary['path']])

    for cache in caches:
        for pc in [x for x in cache['cache'] if x not in seenPCs]:
            sample = cache['cache'][pc] + [cache['asm'][pc]]
            outputCsv.writerow(([args.fill_columns] * headerCol) + [f'0x{pc:x}'] + [args.label_none if x is None else x for x in selector(sample)] + ([args.fill_columns] * (colCount - 1 - headerCol)))

        
if (args.output):
    outputFile.close()
