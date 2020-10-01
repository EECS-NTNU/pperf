#!/usr/bin/env python3

import argparse
import os
import sys
import bz2
import struct
import time
import datetime
import numpy
import gc
from xopen import xopen


parser = argparse.ArgumentParser(description="Parse binary tracev profile to csv")
parser.add_argument("trace", help="tracev binary profile (read from stdin if not provided)", default='-', nargs="?")

parser.add_argument("-c", "--stdout", help="write to standard output", action="store_true", default=False)
parser.add_argument("-o", "--output", help="write to file (disabled if stdout is used)", default=False)
parser.add_argument("-b", "--block-size", type=int, default=4194304, help="cycles read at once (default: %(default)s)")
parser.add_argument("-f", "--frequency", type=float, default=3200.0, help="frequency in MHz to translate cycles into time (0 - do not translate) (default: %(default)s MHz)")
parser.add_argument("-s", "--stat", default=False, action="store_true", help="gather and output cycle statistics")
parser.add_argument("-g", "--gap", type=int, default=5000, help="record cycle gaps at least that big, requires stat (default: %(default)s)")

parser.add_argument("--no-kernel-fix", action="store_true", default=False, help="will not try to detect and fix kernel instructions")

args = parser.parse_args()

if not args.stdout and not args.output and not args.stat:
    parser.print_help()
    sys.exit(0)

if args.trace and args.trace == '-':
    args.trace = False

if args.trace and not os.path.isfile(args.trace):
    print("ERROR: binary tracev file not found!")
    parser.print_help()
    sys.exit(1)

if (args.frequency < 0):
    print("ERROR: frequency can't be negative!")
    parser.print_help()
    sys.exit(1)

args.frequency = args.frequency * 1000 * 1000

validCycles = 0
allCycles = 0
cycleGaps = numpy.array([], dtype=numpy.uint64)
maxCycle = -1

updateInterval = 5000000
lastTime = time.time()
sampleCount = 0
oooCycles = 0

bufCycles = args.block_size

if args.trace:
    tracevFile = xopen(args.trace, mode='rb')
else:
    tracevFile = sys.stdin.buffer
   
csvFile = None
if args.stdout:
    csvFile = sys.stdout
    args.output = False

if args.output:
    csvFile = xopen(args.output,'w')

if csvFile is not None:
    csvFile.write('time;pc0;pc1;pc2;pc3;pc4;pc5;pc6\n')

tracevFile.readline();
if args.trace and not (args.trace.endswith('.gz') or args.trace.endswith('.bz2') or args.trace.endswith('.xz')):
    correction = tracevFile.tell()
    tracevFile.seek(0, os.SEEK_END)
    sampleCount = int((tracevFile.tell() - correction) / 64)
    tracevFile.seek(correction, os.SEEK_SET)
else:
    print('WARNING: cannot show progress for this type of trace file', file=sys.stderr)
    sampleCount = 0


nextUpdate = 0

while True:
    buf = tracevFile.read(bufCycles * 64)
    if not buf:
        break

    if allCycles >= nextUpdate:
        currentTime = time.time()
        elapsed = currentTime - lastTime
        if allCycles == 0 or elapsed <= 0:
            samplesPerSecond = remainingTime = 'n/a'
        else:
            samplesPerSecond = int(updateInterval / elapsed)
        if sampleCount == 0:
            progress = f'{allCycles} cycles'
            remainingTime = 'n/a'
        else:
            progress = str(int((allCycles + 1) * 100 / sampleCount)) + '%'
            remainingTime = datetime.timedelta(seconds=int((sampleCount - allCycles) / samplesPerSecond)) if samplesPerSecond != 0 else 'n/a'
        print(f"\rPost processing... {progress} (ETA: {remainingTime}, {samplesPerSecond} samples/s, extracted {validCycles})      ", end="", file=sys.stderr)
        lastTime = currentTime
        nextUpdate = allCycles + updateInterval

    rawCycles = int(len(buf) / 64)
    allCycles += rawCycles

    # Decode the data into a numpy array
    decoded = numpy.ndarray((rawCycles, 8), dtype='<Q', buffer=buf)
    # Filter out cycles that only contain invalid instructions
    decoded = decoded[numpy.bitwise_and(decoded[:, 1:], 0x1 << 40).any(1), :]

    # If any cycles are left
    if decoded.shape[0] > 0:
        # Remember how many cycles are valid
        containedCycles = decoded.shape[0]

        # Filter out cycles that are out of order i.e. which are in the past
        decoded = decoded[decoded[:,:1].flatten() > maxCycle]

        validCycles += decoded.shape[0]
        # Create a view containing only instruction addresses and cycles
        cycles = decoded[:,:1]
        instrs = decoded[:,1:]

        # Gather some statistics
        if (args.stat):
            # Out of Order Cycles (cycles that are in the past and were ignored)
            if containedCycles != decoded.shape[0]:
                oooCycles += containedCycles - decoded.shape[0]

            # Record cycle gaps bigger/equal to args.gap
            if args.gap > 1:
                # Prepend the last seen cycle to the current cycles
                if maxCycle < 0:
                    maxCycle = cycles.min()
                gapcycles = numpy.append(maxCycle, cycles.flatten())
                # Calculate the differences
                gapdiffs = numpy.diff(gapcycles)
                # Mask those which satisfy the condition
                gapmask = gapdiffs > args.gap
                if gapmask.any():
                    # Create an array with which gap at which cycle
                    gapcycles = gapcycles[numpy.append(gapmask, False)]
                    gapdiffs = gapdiffs[gapmask]
                    gaps = numpy.empty(gapcycles.size * 2, dtype=cycles.dtype)
                    gaps[0::2] = gapcycles
                    gaps[1::2] = gapdiffs
                    cycleGaps = numpy.append(cycleGaps, gaps)

        # Remember the last (biggest) cycle
        maxCycle = cycles.max()

        # If we have no output there is no need to do any further processing
        if csvFile is not None:
            # Zero out all invalid instructions
            instrs[instrs & 0x10000000000  == 0] = 0
            # Sort valid instructions to the beginning
            instrsc = numpy.zeros_like(instrs, dtype=numpy.uint64)
            instrsc[~numpy.sort(instrs == 0, 1)] = numpy.bitwise_and(instrs[instrs != 0], 0xffffffffff)

            # Fix kernel adresses
            if not args.no_kernel_fix:
                instrsc[instrsc & 0xe000000000 == 0xe000000000] |= 0xffffffe000000000
               
            # Convert cycles to time
            if args.frequency > 0:
                cycles = numpy.array(numpy.divide(cycles, args.frequency), dtype=object)
            else:
                cycles = numpy.array(cycles, dtype=object)

            # output to csv file
            numpy.savetxt(csvFile, numpy.append(cycles, instrsc, 1), delimiter=';', fmt=['%.16f' if args.frequency > 0 else '%d', '0x%x', '0x%x', '0x%x', '0x%x', '0x%x', '0x%x', '0x%x'])
       
    # Cleanup
    gc.collect()

if args.output:
    csvFile.close()
   
print(f'\nPostprocessing finished after {allCycles} cycles', file=sys.stderr)
print(f'Extracted cycles: {validCycles} ({validCycles * 100 / allCycles:.2f} %)', file=sys.stderr)
if args.stat:
    if oooCycles > 0:
        print(f'Out of order cycles: {oooCycles}', file=sys.stderr)
    if args.gap > 1 and cycleGaps.size > 0:
        print(f'Recorded cycle gaps: {int(cycleGaps.size / 2)}\n', file=sys.stderr)
        print(f"{'Time':22s} {'Cycle':16s} {'Gap':16s}", file=sys.stderr)
        print(f"{'-'*22:s} {'-'*16:s} {'-'*16:s}", file=sys.stderr)
        for gap in cycleGaps.reshape(-1,2):
            if args.frequency > 0:
                print(f"{gap[0] / args.frequency : 22.16f}", file=sys.stderr, end='')
            else:
                print(f"{'-':22s} ", file.sys.stderr, end='')
            print(f"{gap[0]:16d} {gap[1]:16d}", file=sys.stderr)

exit(0)
