#!/usr/bin/env python3

import argparse
import os
import sys
import bz2
import struct

parser = argparse.ArgumentParser(description="Parse gprof data to csv/vmmap")
parser.add_argument("cpuprofile", help="cpuprofile from gperf")
parser.add_argument("-o", "--output", help="output csv")
parser.add_argument("-v", "--vmmap", help="output vmmap")
parser.add_argument("-e", "--executable", help="name of the executable")
parser.add_argument("-t", "--time", type=float, help="use runtime instead of internal period")
parser.add_argument("--arch-32", action="store_true", help="profile was taken on a 32 bit machine")
parser.add_argument("--arch-64", action="store_true", help="profile was taken on a 64 bit machine (default)")
parser.add_argument("-l", "--little-endian", action="store_true", help="parse cpuprofile using little endianess")
parser.add_argument("-b", "--big-endian", action="store_true", help="parse cpuprofile using big endianess")

args = parser.parse_args()

if not args.arch_32 and not args.arch_64:
    args.arch_64 = True

args.arch_32 = not args.arch_64

if (args.vmmap and not args.executable):
    print("ERROR: need the name of the executable for writing vmmaps!")
    parser.print_help()
    sys.exit(1)


if (not args.output):
    print("ERROR: no output file defined!")
    parser.print_help()
    sys.exit(1)

if (not args.cpuprofile) or (not os.path.isfile(args.cpuprofile)):
    print("ERROR: file for cpuprofile found!")
    parser.print_help()
    sys.exit(1)

if (args.time and args.time <= 0):
    print("ERROR: time can't be negative or 0!")
    parser.print_help()
    sys.exit(1)

endianess = "="
if (args.little_endian):
    endianess = "<"

if (args.big_endian):
    endianess = ">"

binWord = 'I'  # 32bit standard, 'Q' is 64bit
binWordSize = 4
binOffset = 0
binProfile = open(args.cpuprofile, mode='rb').read()
binPayloadSize = 8 if args.arch_64 else 4
binPayload = 'Q' if args.arch_64 else 'I'


try:
    (magic,) = struct.unpack_from(endianess + '4s', binProfile, 0)
    binOffset += binWordSize
    (version,) = struct.unpack_from(endianess + binWord, binProfile, binOffset)
    binOffset += binWordSize + 3 * binWordSize
except Exception as e:
    raise Exception("Unexpected end of file")

if magic != 'gmon' and version != 1:
    raise Exception('Invalid gmon_out file!')

samples = []
sampleTime = 0
sampleCount = 0
arcrecords = 0
while True:
    try:
        (recordType,) = struct.unpack_from(endianess + 'B', binProfile, binOffset)
        binOffset += 1
    except Exception as e:
        break
    if recordType == 0:
        try:
            (lowPc, highPc) = struct.unpack_from(endianess + binPayload + binPayload, binProfile, binOffset)
            binOffset += 2 * binPayloadSize
            (histSize, profRate) = struct.unpack_from(endianess + binWord + binWord, binProfile, binOffset)
            binOffset += 2 * binWordSize + 15 + 1
        except Exception as e:
            raise Exception("Unexpected end of file")
        print(f'Found {histSize} entries in hist record from 0x{lowPc:x} to 0x{highPc:x} profiled with {profRate} Hz')
        step = (highPc - lowPc) / histSize
        localSampleCount = 0
        for i in range(histSize):
            pc = lowPc + int(i * step)
            try:
                (count,) = struct.unpack_from(endianess + 'H', binProfile, binOffset)
                binOffset += 2
            except Exception as e:
                raise Exception("Unexpected end of file")
            for i in range(count):
                samples.append(pc)
            localSampleCount += count
        sampleTime += localSampleCount / profRate
        sampleCount += localSampleCount
    elif recordType == 1:
        binOffset += 2 * binPayloadSize + binWordSize
        arcrecords += 1
    elif recordType == 2:
        try:
            (bbcount,) = struct.unpack_from(endianess + binWord, binProfile, binOffset)
            binOffset += binWordSize + bbcount * binWordSize + bbcount * binWordSize
        except Exception as e:
            raise Exception("Unexpected end of file")
        print(f'Ignored {bbcount} entries from basic block count record')
    else:
        raise Exception(f'Unexpected record type {recordType}!')

if (arcrecords > 0):
    print(f'Ignored {arcrecords} arc records')

if len(samples) == 0:
    raise Exception('No samples could be extracted!')

if args.time:
    sampleTime = args.time
samplingPeriod = sampleTime / len(samples)

print(f"Extracted {sampleCount} samples for {sampleTime}s sampling time")

if args.output.endswith(".bz2"):
    csvFile = bz2.open(args.output, "wt")
else:
    csvFile = open(args.output, "w")

csvFile.write('time;pc0\n')
runningTime = 0.0

for sample in samples:
    runningTime += samplingPeriod
    csvFile.write(f'{runningTime:.16f};{sample}\n')

print(f"Wrote to {args.output}")

csvFile.close()

if (not args.vmmap):
    exit(0)

vmmapFile = open(args.vmmap, "w")
vmmapBaseAddress = 0 # min(samples)
vmmapLength = max(samples) # - min(samples)
vmmapTarget = args.executable
vmmapFile.write(f'0x{vmmapBaseAddress:016x} 0x{vmmapLength:016x} {vmmapTarget}\n')
vmmapFile.close()
print(f"Wrote to {args.vmmap}")
