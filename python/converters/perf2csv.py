#!/usr/bin/env python3

import argparse
import os
import sys
import bz2
import subprocess
import chardet


def guessEncoding(data):
    enc = chardet.detect(data)['encoding']
    if (enc is None):
        for enc in ['utf-8', 'latin-1', 'iso-8859']:
            try:
                data.decode(enc)
                return enc
            except Exception:
                continue
    else:
        return enc
    return None


parser = argparse.ArgumentParser(description="Parse perf data to csv/vmmap")
parser.add_argument("perfdata", help="perf-data from perf record")
parser.add_argument("-o", "--output", help="output csv")
parser.add_argument("-v", "--vmmap", help="output vmmap")
parser.add_argument("-t", "--target", help="set target executeable")
parser.add_argument("--type", choices=['full', 'flat'], default='full', help="create a full or flat profile")
parser.add_argument("--scale-time", default=1, type=float, help="scale time output")
parser.add_argument("-p", "--perf", help="use this perf executable")
parser.add_argument("-e", "--encoding", help="use this perf executable")

args = parser.parse_args()


if (not args.output):
    print("ERROR: no output file defined!")
    parser.print_help()
    sys.exit(1)

if (not args.perfdata) or (not os.path.isfile(args.perfdata)):
    print("ERROR: perfdata not found!")
    parser.print_help()
    sys.exit(1)


vmmapFile = False
csvFile = False
perfFile = False

if args.output.endswith(".bz2"):
    csvFile = bz2.open(args.output, "wt")
else:
    csvFile = open(args.output, "w")

if (args.vmmap):
    vmmapFile = open(args.vmmap, "w")


samples = []
seenCpus = []

targetParentId = None


print("Processing perf raw data...")
perf = subprocess.Popen([args.perf if args.perf else 'perf', 'report', '--header', '-D', '-i', args.perfdata], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
encoding = args.encoding if args.encoding else None

prevSampleTime = None

for line in perf.stdout:
    parsed = False
    encodingPass = 0

    while not parsed:
        if encoding is None:
            encoding = guessEncoding(line)
            if (encoding is None):
                raise Exception("Could not detect encoding or perf raw output")
            print(f"Encoding set to {encoding}")

        try:
            line = line.decode(encoding).strip().rstrip('\n').rstrip('\r\n')
            parsed = True
        except Exception:
            if encodingPass >= 1:
                raise Exception(f"Could not decode perf raw output with encoding {encoding}")
            encoding = None
            encodingPass += 1

    if 'PERF_RECORD_SAMPLE' not in line and 'PERF_RECORD_MMAP' not in line:
        continue

    sample = line.split(": ")
    sampleStat = sample[0].split(" ")
    if len(sampleStat) < 3:
        continue

    if len(sampleStat) == 3:
        sampleCpu = 0
        sampleTime = int(sampleStat[0], 0)
        sampleOffset = int(sampleStat[1], 0)
    else:
        sampleCpu = int(sampleStat[0], 0)
        sampleTime = int(sampleStat[1], 0)
        sampleOffset = int(sampleStat[2], 0)

    if (sampleTime == 0):
        continue

    sampleSource = None
    sampleParentId = None
    sampleThreadId = None
    samplePc = None
    sampleMmapBaseAddr = None
    sampleMmapLength = None
    sampleMmapTarget = None

    if 'PERF_RECORD_SAMPLE' in sample[1]:
        sampleType = 'PERF_RECORD_SAMPLE'
        if '(IP, 0x1)' in sample[1]:
            sampleSource = 'kernel'
        elif '(IP, 0x2)' in sample[1]:
            sampleSource = 'user'
        sampleParentId = int(sample[2].split('/')[0], 0)
        sampleThreadId = int(sample[2].split('/')[1], 0)
        samplePc = int(sample[3].split(' ')[0], 0)

    elif 'PERF_RECORD_MMAP' in sample[1]:
        sampleType = 'PERF_RECORD_MMAP'
        sampleParentId = int(sample[1].split(' ')[1].split('/')[0], 0)
        sampleThreadId = int(sample[1].split(' ')[1].split('/')[1], 0)
        tmp = sample[2]
        for c in ['(', ')', '[', ']', '@', ':']:
            tmp = tmp.replace(c, ' ')
        tmp = tmp.strip().split(' ')
        sampleMmapBaseAddr = int(tmp[0], 0)
        sampleMmapLength = int(tmp[1], 0)
        sampleMmapTarget = os.path.basename(sample[3].split(' ')[1])
        if '[' in sampleMmapTarget and ']' in sampleMmapTarget:
            continue
    else:
        print(f"ERROR: could not detect sample type: {line}")
        sys.exit(1)

    if args.vmmap and sampleType == 'PERF_RECORD_MMAP':
        if (targetParentId is None and not args.target) or (args.target and sampleMmapTarget == args.target):
            targetParentId = sampleParentId
        if targetParentId == sampleParentId:
            vmmapFile.write(f'0x{sampleMmapBaseAddr:016x} 0x{sampleMmapLength:016x} {sampleMmapTarget}\n')

    if sampleType == 'PERF_RECORD_SAMPLE':
        if sampleCpu not in seenCpus:
            seenCpus.append(sampleCpu)

        samples.append([sampleTime, sampleCpu, samplePc])

    # print(f"Type {sampleType}, Source {sampleSource}, Time {sampleTime}, ParentId {sampleParentId}, ThreadId {sampleThreadId}, PC {samplePc}, BaseAddr {sampleMmapBaseAddr}, Length {sampleMmapLength}, Target {sampleMmapTarget}")
if targetParentId is None:
    raise Exception(f"ERROR: '{args.target}' target binary was not detected")

if len(seenCpus) == 0:
    raise Exception(f"ERROR: could not extract any samples from {args.perfdata}, maybe profile perf version is incompatible with local perf")

# Perf raw dump samples are not necessarily ordered
samples = sorted(samples, key=lambda x: x[0])

pcVector = [0] * (max(seenCpus) + 1)
profile = []
flatProfile = {}
prevTime = samples[0][0]
for sample in samples:
    if args.type == 'flat':
        if sample[2] not in flatProfile:
            flatProfile[sample[2]] = 0
        flatProfile[sample[2]] += sample[0] - prevTime
        prevTime = sample[0]
    else:
        pcVector[sample[1]] = sample[2]
        profile.append([sample[0]] + pcVector)

if args.type == 'flat':
    for key in flatProfile:
        profile.append([flatProfile[key], key])
    seenCpus = [0]

for i, _ in enumerate(profile):
    profile[i][0] = (float(profile[i][0]) / 1000000000.0) * args.scale_time

if args.output.endswith(".bz2"):
    csvFile = bz2.open(args.output, "wt")
else:
    csvFile = open(args.output, "w")

csvFile.write('time')
for cpu in seenCpus:
    csvFile.write(f';pc{cpu}')
csvFile.write('\n')

for sample in profile:
    csvFile.write(f'{sample[0]:.16f}')
    for cpu in seenCpus:
        csvFile.write(f';0x{sample[cpu+1]:x}')
    csvFile.write('\n')

print(f"{len(samples)} samples extracted")

if args.vmmap and targetParentId is None:
    print("WARNING: no executable found that was memory mapped")

if (args.vmmap):
    vmmapFile.close()
    print(f'VMMap written to {args.vmmap}')

csvFile.close()
print(f'CSV written to {args.output}')
