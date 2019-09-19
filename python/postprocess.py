#!/usr/bin/env python3

import argparse
import os
import sys
import struct
import pickle
import bz2
import profileLib
import gc
import time
import datetime

profile = {
    'version': profileLib.profileVersion,
    'samples': 0,
    'samplingTime': 0,
    'latencyTime': 0,
    'volts': 0,
    'cpus': 0,
    'name': "",
    'target': "",
    'binaries': [],
    'functions': [],
    'files': [],
    'profile': [],
    'toolchain': profileLib.getToolchainVersion()
}

parser = argparse.ArgumentParser(description="Parse profiles from intrvelf sampler.")
parser.add_argument("profile", help="profile from intrvelf")
parser.add_argument("-n", "--name", help="name profile")
parser.add_argument("-v", "--volts", help="set pmu voltage", type=float)
parser.add_argument("-s", "--search-path", help="add search path", action="append")
parser.add_argument("-o", "--output", help="write postprocessed profile")
parser.add_argument("-c", "--cpus", help="list of active cpu cores", default="0-3")
parser.add_argument("-l", "--little-endian", action="store_true", help="parse profile using little endianess")
parser.add_argument("-b", "--big-endian", action="store_true", help="parse profile using big endianess")
parser.add_argument("--dump-vmmap", help="dump vmmap to file")

args = parser.parse_args()

if (not args.output):
    print("ERROR: not output file defined!")
    parser.print_help()
    sys.exit(1)

if (not args.profile) or (not os.path.isfile(args.profile)):
    print("ERROR: profile not found!")
    parser.print_help()
    sys.exit(1)

if (not args.search_path):
    args.search_path = []

args.search_path.append(os.getcwd())

binProfile = open(args.profile, mode='rb').read()

endianess = "="

if (args.little_endian):
    endianess = "<"

if (args.big_endian):
    endianess = ">"

binOffset = 0

useCpus = list(set(profileLib.parseRange(args.cpus)))
profile['cpus'] = len(useCpus)

try:
    (magic,) = struct.unpack_from(endianess + "I", binProfile, binOffset)
    binOffset += 4
except Exception as e:
    print("Unexpected end of file!")
    sys.exit(1)

if (magic < 0 or magic > 3):
    print("Invalid profile!")
    sys.exit(1)

if (magic == 0 or magic == 2):
    print("WARNING: postprocessed profiles currently only support power, input contains either custom or voltage data which is passed through!")
    if (args.volts):
        print("WARNING: volts argument therefore ignored")
    args.volts = 1

if (magic == 1 and not args.volts):
    print("ERROR: profile contains current pmu data, volts argument is required!")
    sys.exit(1)

if (magic == 3 or not args.volts):
    args.volts = 1

profile['volts'] = args.volts
useVolts = profile['volts']

try:
    (wallTimeUs, latencyTimeUs, sampleCount, pmuDataSize, vmmapCount) = struct.unpack_from(endianess + 'QQQII', binProfile, binOffset)
    binOffset += 8 + 8 + 8 + 4 + 4
except Exception as e:
    print("Unexpected end of file!")
    sys.exit(1)

if pmuDataSize != 8:
    print(f"pmuData size not supported: {pmuDataSize}")
    sys.exit(1)

if (sampleCount == 0):
    print("No samples found in profile!")
    sys.exit(1)

profile['samples'] = sampleCount
profile['samplingTime'] = (wallTimeUs / 1000000.0)
profile['latencyTime'] = (latencyTimeUs / 1000000.0)

rawSamples = []
for i in range(sampleCount):
    if (i % 1000 == 0):
        progress = int((i + 1) * 100 / sampleCount)
        print(f"\rReading raw samples... {progress}%", end="")

    try:
        (wallTimeMs, pmuValue, threadCount, ) = struct.unpack_from(endianess + "QdI", binProfile, binOffset)
        binOffset += 8 + 8 + 4
    except Exception as e:
        print("\nUnexpected end of file!")
        sys.exit(1)

    sample = []
    for j in range(threadCount):
        try:
            (tid, pc, cpuTimeNs, ) = struct.unpack_from(endianess + "IQQ", binProfile, binOffset)
            binOffset += 4 + 8 + 8
        except Exception as e:
            print("Unexpected end of file!")
            sys.exit(1)
        sample.append([tid, pc, (cpuTimeNs / 1000000000.0)])

    rawSamples.append([(wallTimeMs / 1000000.0), pmuValue, sample])


print("\rReading raw samples... finished!")
vmmaps = []
for i in range(vmmapCount):
    try:
        (addr, size, label,) = struct.unpack_from(endianess + "QQ256s", binProfile, binOffset)
        binOffset += 256 + 16
    except Exception as e:
        print("Unexpected end of file!")
        sys.exit(1)
    vmmaps.append([addr, size, label.decode('utf-8').rstrip('\0')])

print("Reading raw vm maps... finished!")

del binProfile
gc.collect()

vmmapString = '\n'.join([f"{x[0]:x} {x[1]:x} {x[2]}" for x in vmmaps])
if (args.dump_vmmap):
    with open(args.dump_vmmap, "w") as f:
        f.write(vmmapString)

sampleParser = profileLib.sampleParser()
sampleParser.addSearchPath(args.search_path)
sampleParser.loadVMMap(fromBuffer=vmmapString)
del vmmaps
del vmmapString
gc.collect()

profile['name'] = args.name if args.name else sampleParser.binaries[0]['binary']
profile['target'] = sampleParser.binaries[0]['binary']

i = 0
prevThreadCpuTimes = {}
offsetSampleWallTime = None
lastTime = time.time()
updateInterval = 5000 if (sampleCount / 5000 >= 100) else int(sampleCount / 100)

while rawSamples:
    sample = rawSamples.pop(0)
    if (i % updateInterval == 0):
        currentTime = time.time()
        elapsed = currentTime - lastTime
        progress = int((i + 1) * 100 / sampleCount)
        if (elapsed <= 0) or (i == 0):
            samplesPerSecond = remainingTime = 'n/a'
        else:
            samplesPerSecond = int(updateInterval / elapsed)
            remainingTime = datetime.timedelta(seconds=int((sampleCount - i) / samplesPerSecond))
        print(f"Post processing... {progress}% (ETA: {remainingTime}, {samplesPerSecond} samples/s)\r", end="")
        lastTime = currentTime
    i += 1

    if offsetSampleWallTime is None:
        offsetSampleWallTime = sample[0]

    processedSample = []
    sampleWallTime = sample[0] - offsetSampleWallTime
    samplePower = sample[1] * useVolts

    for thread in sample[2]:
        if not thread[0] in prevThreadCpuTimes:
            prevThreadCpuTimes[thread[0]] = thread[2]

        threadCpuTime = thread[2] - prevThreadCpuTimes[thread[0]]
        prevThreadCpuTimes[thread[0]] = thread[2]

        processedSample.append([thread[0], threadCpuTime, sampleParser.parseFromPC(thread[1])])

    profile['profile'].append([samplePower, sampleWallTime, processedSample])

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
