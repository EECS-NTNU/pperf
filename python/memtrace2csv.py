#!/usr/bin/env python3

import argparse
import os
import sys
import time
import datetime
import numpy
from xopen import xopen


parser = argparse.ArgumentParser(description="Parse binary memtrace to csv (energy <> bytes)")
parser.add_argument("memtrace", help="memtrace binary (read from stdin if not provided)", default='-', nargs="?")

parser.add_argument("-c", "--stdout", help="write to standard output", action="store_true", default=False)
parser.add_argument("-o", "--output", help="write to file (disabled if stdout is used)", default=False)
parser.add_argument("-b", "--block-size", type=int, default=1000000, help="cycles read at once (default: %(default)s)")
parser.add_argument("-l", "--compress-limit", type=int, default=100000000, help="compress after that many cycles (default: %(default)s)")

args = parser.parse_args()

if not args.output:
    args.stdout = True

if args.memtrace and args.memtrace == '-':
    args.memtrace = False

if args.memtrace and not os.path.isfile(args.trace):
    print("ERROR: binary memtrace file not found!")
    parser.print_help()
    sys.exit(1)

updateInterval = args.compress_limit + 1
lastTime = time.time()
sampleCount = 0

bufCycles = args.block_size

if args.memtrace:
    traceFile = xopen(args.memtrace, mode='rb')
else:
    traceFile = sys.stdin.buffer


if args.memtrace and not (args.memtrace.endswith('.gz') or args.memtrace.endswith('.bz2') or args.memtrace.endswith('.xz')):
    traceFile.seek(0, os.SEEK_END)
    sampleCount = int(traceFile.tell() / 32)
    traceFile.seek(0, os.SEEK_SET)
else:
    print('WARNING: cannot show progress for this type of input file', file=sys.stderr)
    sampleCount = 0

currentCycles = 0
nextUpdate = 0
lastCycles = -updateInterval

runningTime = 0

acc = {}
saddrs = numpy.array([], dtype=numpy.uint64)
scounts = numpy.array([], dtype=numpy.uint64)
sbytes = numpy.array([], dtype=numpy.uint64)

nextCompressCycle = currentCycles + args.compress_limit


def scompress():
    nsaddrs, inv = numpy.unique(saddrs, return_inverse=True)
    nscounts = numpy.zeros(len(nsaddrs), dtype=numpy.uint64)
    nsbytes = numpy.zeros(len(nsaddrs), dtype=numpy.uint64)
    numpy.add.at(nscounts, inv, scounts)
    numpy.add.at(nsbytes, inv, sbytes)
    return (nsaddrs, nscounts, nsbytes)


while True:
    buf = traceFile.read(bufCycles * 32)
    if not buf:
        break

    if currentCycles >= lastCycles + updateInterval:
        currentTime = time.time()
        elapsed = currentTime - lastTime
        if currentCycles == 0 or elapsed <= 0:
            samplesPerSecond = remainingTime = 'n/a'
        else:
            samplesPerSecond = int((currentCycles - lastCycles) / elapsed)
        if sampleCount == 0:
            progress = f'{currentCycles} cycles'
            remainingTime = 'n/a'
        else:
            progress = str(int((currentCycles + 1) * 100 / sampleCount)) + '%'
            remainingTime = datetime.timedelta(seconds=int((sampleCount - currentCycles) / samplesPerSecond)) if samplesPerSecond != 0 else 'n/a'
        print(f"\rPost processing... {progress} (ETA: {remainingTime}, {samplesPerSecond} samples/s)   ", end="", file=sys.stderr)
        lastTime = currentTime
        lastCycles = currentCycles

    rawCycles = int(len(buf) / 32)
    currentCycles += rawCycles

    # Decode the data into a numpy array
    decoded = numpy.ndarray((rawCycles, 4), dtype='<Q', buffer=buf)

    # If any cycles are left
    if decoded.shape[0] > 0:

        # Compress this block
        naddrs, inv, ncounts = numpy.unique(decoded[:, 3], return_inverse=True, return_counts=True)
        nbytes = numpy.zeros(len(naddrs), dtype=numpy.uint64)
        numpy.add.at(nbytes, inv, decoded[:, 2])

        # Append results
        saddrs = numpy.append(saddrs, naddrs)
        sbytes = numpy.append(sbytes, nbytes)
        scounts = numpy.append(scounts, ncounts)

        # Compress data, else we would accumalate too much over time
        if currentCycles >= nextCompressCycle:
            saddrs, scounts, sbytes = scompress()
            nextCompressCycle = currentCycles + args.compress_limit

        # for sample in decoded:
        #     if sample[3] not in acc:
        #         acc[sample[3]] = [1, sample[2]]
        #     else:
        #         acc[sample[3]][0] += 1
        #         acc[sample[3]][1] += sample[2]

        # for i, addr in enumerate(saddrs):
        #     assert(addr in acc)
        #     assert(acc[addr][0] == scounts[i])
        #     assert(acc[addr][1] == sbytes[i])

    # if currentCycles >= 100:
    #     break

# Make sure a last time to compress
saddrs, scounts, sbytes = scompress()

csvFile = None
if args.stdout:
    csvFile = sys.stdout
    args.output = False

if args.output:
    csvFile = xopen(args.output, 'w')

if csvFile is not None:
    csvFile.write('time;power0;pc0;bytes;count\n')
    csvFile.write('0;0;0;0;0\n')
    numpy.savetxt(csvFile,
                  numpy.concatenate(
                      (
                          numpy.cumsum(scounts, dtype=numpy.uint64).reshape(-1, 1),
                          numpy.array(sbytes / scounts, dtype=numpy.float64).reshape(-1, 1),
                          numpy.array(saddrs, dtype=numpy.uint64).reshape(-1, 1),
                          numpy.array(sbytes, dtype=numpy.uint64).reshape(-1, 1),
                          numpy.array(scounts, dtype=numpy.uint64).reshape(-1, 1),
                      ),
                      axis=1
                  ),
                  fmt='%i;%.16f;%i;%i;%i')


if args.output:
    csvFile.close()

print(f'\nPostprocessing finished after {currentCycles} samples', file=sys.stderr)

exit(0)
