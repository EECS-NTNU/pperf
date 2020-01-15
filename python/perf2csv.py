#!/usr/bin/env python

import argparse
import os
import sys
import bz2
import subprocess

parser = argparse.ArgumentParser(description="Parse perf data to csv/vmmap")
parser.add_argument("perfdata", help="perf-data from perf record")
parser.add_argument("-o", "--output", help="output csv")
parser.add_argument("-v", "--vmmap", help="output vmmap")
parser.add_argument("-t", "--target", help="set target executeable")
parser.add_argument("-p", "--perf", help="use this perf executable")

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

perf = subprocess.Popen([args.perf if args.perf else 'perf', 'report', '--header', '-D', '-i', args.perfdata], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
for line in perf.stdout:
    line = line.decode('utf-8').strip().rstrip('\n')
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

    if (sampleTime is 0):
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

    if args.vmmap and sampleType is 'PERF_RECORD_MMAP':
        if (targetParentId is None and not args.target) or (args.target and sampleMmapTarget == args.target):
            targetParentId = sampleParentId
        if targetParentId == sampleParentId:
            vmmapFile.write(f'0x{sampleMmapBaseAddr:016x} 0x{sampleMmapLength:016x} {sampleMmapTarget}\n')

    if sampleType is 'PERF_RECORD_SAMPLE':
        if sampleCpu not in seenCpus:
            seenCpus.append(sampleCpu)
        samples.append([sampleTime, sampleCpu, samplePc])

    # print(f"Type {sampleType}, Source {sampleSource}, Time {sampleTime}, ParentId {sampleParentId}, ThreadId {sampleThreadId}, PC {samplePc}, BaseAddr {sampleMmapBaseAddr}, Length {sampleMmapLength}, Target {sampleMmapTarget}")

perf.wait()

if len(seenCpus) == 0:
    raise Exception('Nothing was extracted')

if perf.returncode is not 0:
    print("ERROR: perf report failed!")
    print(perf.stderr.read().decode('utf-8'))
    sys.exit(1)

if args.output.endswith(".bz2"):
    csvFile = bz2.open(args.output, "wt")
else:
    csvFile = open(args.output, "w")

csvFile.write('time')
for cpu in seenCpus:
    csvFile.write(f';pc{cpu}')
csvFile.write('\n')


pcVector = [0] * (max(seenCpus) + 1)
for sample in samples:
    csvFile.write(f'{float(sample[0]) / 1000000000.0:.16f}')
    pcVector[sample[1]] = sample[2]
    for cpu in seenCpus:
        csvFile.write(f';{pcVector[cpu]}')
    csvFile.write('\n')


if args.vmmap and targetParentId is None:
    print("WARNING: no executable found that was memory mapped")

if (args.vmmap):
    vmmapFile.close()

csvFile.close()
