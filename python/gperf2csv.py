#!/usr/bin/env python3

import argparse
import os
import sys
import bz2
import struct


def readHeader(binFile, word):
    result = []
    try:
        result = struct.unpack_from(endianess + binWord + binWord + binWord + binWord + binWord, binProfile, 0)
    except Exception as e:
        raise Exception("Unexpected end of file")
    return result


parser = argparse.ArgumentParser(description="Parse gperf data to csv/vmmap")
parser.add_argument("cpuprofile", help="cpuprofile from gperf")
parser.add_argument("-o", "--output", help="output csv")
parser.add_argument("-v", "--vmmap", help="output vmmap")
parser.add_argument("-t", "--time", type=float, help="use runtime instead of internal period")
parser.add_argument("-l", "--little-endian", action="store_true", help="parse cpuprofile using little endianess")
parser.add_argument("-b", "--big-endian", action="store_true", help="parse cpuprofile using big endianess")

args = parser.parse_args()

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
binProfile = open(args.cpuprofile, mode='rb').read()

header = readHeader(binProfile, binWord)

if (header[0] != 0 or header[1] != 3 or header[2] != 0 or header[4] != 0):
    binWord = 'Q'
    binWordSize = 8
    header = readHeader(binProfile, binWord)
    if (header[0] != 0 or header[1] != 3 or header[2] != 0 or header[4] != 0):
        raise Exception("Header mismatch for 32bit and 64bit profile, is endianess correct?")

binOffset = 5 * binWordSize

samples = []
sampleCount = 0
stackTraces = 0

# csvFile.write('0;0\n')

while (True):
    try:
        sample = struct.unpack_from(endianess + binWord + binWord + binWord, binProfile, binOffset)
        binOffset += 3 * binWordSize
    except Exception as e:
        raise Exception("Unexpected end of file")

    binOffset += (sample[1] - 1) * binWordSize

    if (sample[0] == 0 and sample[1] == 1 and sample[2] == 0):
        break  # Binary trail detected

    sampleCount += sample[0]
    stackTraces += sample[1] - 1

    for i in range(sample[0]):
        samples.append(sample[2])

samplingPeriod = float(header[3]) / 1000000.0 if not args.time else args.time / len(samples)

print(f"Extracted {sampleCount} samples (ignored {stackTraces} stack traces) for {len(samples) * samplingPeriod:.2f}s sampling time")

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
vmmapCount = 0

for line in binProfile[binOffset:].decode('utf-8').split('\n')[:-1]:
    lineComponents = (' '.join(line.split())).split(' ')

    vmmapMod = lineComponents[1]
    if vmmapMod[2].lower() != 'x' or len(lineComponents) < 5:
        continue

    vmmapTarget = os.path.basename(lineComponents[5])
    if '[' in vmmapTarget and ']' in vmmapTarget:
        continue

    vmmapBaseAddressStr = lineComponents[0].split('-')[0]
    vmmapEndAddressStr = lineComponents[0].split('-')[1]
    vmmapBaseAddress = int('0x' + vmmapBaseAddressStr if not vmmapBaseAddressStr.startswith('0x') else vmmapBaseAddressStr, 0)
    vmmapEndAddress = int('0x' + vmmapEndAddressStr if not vmmapEndAddressStr.startswith('0x') else vmmapEndAddressStr, 0)
    vmmapLength = vmmapEndAddress - vmmapBaseAddress
    vmmapFile.write(f'0x{vmmapBaseAddress:016x} 0x{vmmapLength:016x} {vmmapTarget}\n')
    vmmapCount += 1


print(f"Extracted {vmmapCount} vmmaps")

vmmapFile.close()

print(f"Wrote to {args.vmmap}")

csvFile.close()
