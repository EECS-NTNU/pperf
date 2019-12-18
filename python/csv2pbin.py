#!/usr/bin/env python3

import argparse
import os
import sys
import pickle
import bz2
import csv
import profileLib
import time
import datetime

profile = {
    'version': profileLib.profileVersion,
    'samples': 0,
    'samplingTime': 0,
    'latencyTime': 0,
    'volts': 1,
    'cpus': 1,
    'name': "",
    'target': "",
    'binaries': [],
    'functions': [],
    'files': [],
    'profile': [],
    'toolchain': profileLib.getToolchainVersion()
}

parser = argparse.ArgumentParser(description="Parse sthem csv exports.")
parser.add_argument("csv", help="csv export from sthem")
parser.add_argument("-p", "--power-sensor", help="power sensor to use", type=int, default=False)
parser.add_argument("-n", "--name", help="name profile")
parser.add_argument("-s", "--search-path", help="add search path", action="append")
parser.add_argument("-o", "--output", help="output profile")
parser.add_argument("-v", "--vmmap", help="vmmap from profiling run")
parser.add_argument("-ks", "--kallsyms", help="parse with kernel symbol file")
parser.add_argument("-c", "--cpus", help="list of active cpu cores", default="0-3")
parser.add_argument("--disable-unwind-inline", action="store_true", help="do not unwind inlined functions (disables cache)")
parser.add_argument("--disable-cache", action="store_true", help="do not create or use address caches")

args = parser.parse_args()

if (not args.output):
    print("ERROR: no output file defined!")
    parser.print_help()
    sys.exit(1)

if (not args.csv) or (not os.path.isfile(args.csv)):
    print("ERROR: profile not found!")
    parser.print_help()
    sys.exit(1)

if (not args.vmmap) or (not os.path.isfile(args.vmmap)):
    print("ERROR: vmmap not found!")
    parser.print_help()
    sys.exit(1)

if (args.kallsyms) and (not os.path.isfile(args.kallsyms)):
    print("ERROR: kallsyms not found!")
    parser.print_help()
    sys.exit(1)

if args.disable_cache:
    profileLib.disableCache = True
if args.disable_unwind_inline:
    profileLib.disableCache = True
    profileLib.disableInlineUnwinding = True

if (not args.search_path):
    args.search_path = []
args.search_path.append(os.getcwd())

useCpus = list(set(profileLib.parseRange(args.cpus)))
profile['cpus'] = len(useCpus)

sampleParser = profileLib.sampleParser()

sampleParser.addSearchPath(args.search_path)

print("Opening csv... ", end="")
sys.stdout.flush()

if args.csv.endswith(".bz2"):
    csvFile = bz2.open(args.csv, "rt")
else:
    csvFile = open(args.csv, "r")


csvProfile = csv.reader(csvFile, delimiter=";")

# get number of samples

profile['samples'] = sum(1 for line in csvFile) - 1
csvFile.seek(0)

print("finished!")

print("Reading vm maps... ", end="")
sys.stdout.flush()
sampleParser.loadVMMap(args.vmmap)
print("finished")

profile['name'] = args.name if args.name else sampleParser.binaries[0]['binary']
profile['target'] = sampleParser.binaries[0]['binary']

if (args.kallsyms):
    sampleParser.loadKallsyms(args.kallsyms)

# print("Not using skewed pc adjustment!")
# sampleParser.enableSkewedPCAdjustment()

i = 0
sampleCount = profile['samples']
prevTime = None
lastTime = time.time()
updateInterval = max(1, int(sampleCount / 200))
wallTime = 0.0

timeColumn = False

while (not timeColumn):
    header = [x.lower() for x in next(csvProfile)]
    if not header:
        print("ERROR: could not find header row")
    timeColumn = [i for i, x in enumerate(header) if 'time' in x]
    powerColumns = [i for i, x in enumerate(header) if 'power' in x]
    currentColumns = [i for i, x in enumerate(header) if 'current' in x]
    voltageColumns = [i for i, x in enumerate(header) if 'voltage' in x]
    pcColumns = [i for i, x in enumerate(header) if 'pc' in x]


if not timeColumn:
    print("ERROR: could not find time column")
    sys.exit(1)
else:
    timeColumn = timeColumn[0]

for cpu in useCpus:
    if cpu > (len(pcColumns) - 1):
        print(f"ERROR: could not find PC columns for cpu {cpu}")
        sys.exit(1)

if args.power_sensor is not False:
    args.power_sensor -= 1
    if powerColumns:
        if args.power_sensor > (len(powerColumns)):
            print(f"ERROR: could not find power column for power sensor {args.power_sensor + 1}")
            sys.exit(1)
        usePower = True
    elif voltageColumns:
        if args.power_sensor > (len(voltageColumns)) or args.power_sensor > (len(currentColumns)):
            print(f"ERROR: could not find current and voltage column for power sensor {args.power_sensor + 1}")
            sys.exit(1)
        usePower = False

power = 0

for sample in csvProfile:
    if (i % updateInterval == 0):
        currentTime = time.time()
        elapsed = currentTime - lastTime
        progress = int((i + 1) * 100 / sampleCount)
        if (elapsed <= 0) or (i == 0):
            samplesPerSecond = remainingTime = 'n/a'
        else:
            samplesPerSecond = int(updateInterval / elapsed)
            remainingTime = datetime.timedelta(seconds=int((sampleCount - i) / samplesPerSecond)) if samplesPerSecond != 0 else 'n/a'
        print(f"Post processing... {progress}% (ETA: {remainingTime}, {samplesPerSecond} samples/s)\r", end="")
        lastTime = currentTime
    i += 1

    wallTime = float(sample[timeColumn])

    if prevTime is None:
        prevTime = wallTime

    if args.power_sensor is not False:
        if usePower:
            power = float(sample[powerColumns[args.power_sensor]])
        else:
            power = float(sample[voltageColumns[args.power_sensor]]) * float(sample[currentColumns[args.power_sensor]])

    processedSample = []
    for cpu in useCpus:
        pc = int(sample[pcColumns[cpu]])
        processedSample.append([cpu, ((wallTime - prevTime) / len(useCpus)), sampleParser.parseFromPC(pc)])

    prevTime = wallTime
    profile['profile'].append([power, wallTime, processedSample])

del csvProfile
del csvFile

profile['samplingTime'] = wallTime - profile['profile'][0][1]
profile['binaries'] = sampleParser.getBinaryMap()
profile['functions'] = sampleParser.getFunctionMap()
profile['files'] = sampleParser.getFileMap()

print("\nPost processing... finished!")

print(f"Writing {args.output}... ", end="")
sys.stdout.flush()
if args.output.endswith(".bz2"):
    outProfile = bz2.BZ2File(args.output, mode='wb')
else:
    outProfile = open(args.output, mode="wb")
pickle.dump(profile, outProfile, pickle.HIGHEST_PROTOCOL)
outProfile.close()

print("finished")
