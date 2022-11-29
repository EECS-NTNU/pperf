#!/usr/bin/env python3

import argparse
import os
import sys
import bz2
import xopen
import struct
import binascii

supportedPmuTypes = {
  'float' : {'code' : 'f', 'size' : 4},
  'double': {'code' : 'd', 'size' : 8},
  'int8_t' : {'code': 'b', 'size' : 1},
  'int16_t': {'code': 'h', 'size' : 2},
  'int32_t' : {'code': 'i', 'size' : 4},
  'int64_t' : {'code': 'q', 'size' : 8},
  'uint8_t' : {'code': 'B', 'size' : 1},
  'uint16_t': {'code': 'H', 'size' : 2},
  'uint32_t' : {'code': 'I', 'size' : 4},
  'uint64_t' : {'code': 'Q', 'size' : 8},
  'binary' : {'code': 's', 'size': 0}
}

pmuTypeUnpackCodes = ['f', 'd', 'b', 'h', 'i', 'q', 'B', 'H', 'I', 'Q', 's']

parser = argparse.ArgumentParser(description="Convert a binary PPerf profile to a CSV")
parser.add_argument("profile", help="profile from PPerf")
parser.add_argument("-o", "--output", default=None, help="output CSV (default stdout)")
parser.add_argument("-v", "--vmmap", default=None, help="output VMMaps (default skipped)")
parser.add_argument("-d", "--delimiter", default=";", help="ouput delimiter (default %(default)s")
parser.add_argument("-p", "--pmu-type", default="double", choices=supportedPmuTypes.keys(), help="unpack pmu data as type (default %(default)s)")
parser.add_argument("--no-comment", action="store_true", help="do not include comments with global profile information")
parser.add_argument("-l", "--little-endian", action="store_true", help="parse profile using little endianess")
parser.add_argument("-b", "--big-endian", action="store_true", help="parse profile using big endianess")

args = parser.parse_args()

if not os.path.isfile(args.profile):
    raise Exception ("input file not found!")

binProfile = xopen.xopen(args.profile, mode='rb').read()
endianess = '<' if args.little_endian else '>' if args.big_endian else '='
binOffset = 0

pmuCode = supportedPmuTypes[args.pmu_type]['code']
pmuSize = supportedPmuTypes[args.pmu_type]['size']

try:
    (magic,) = struct.unpack_from(endianess + "I", binProfile, binOffset)
    binOffset += 4
except Exception as e:
    raise Exception("unexpected end of input file")

if not (0 <= magic <= 3):
    raise Exception("PPerf magic number in invalid range")

try:
    (wallTimeUs, latencyTimeUs, sampleCount, profilePmuSize, vmmapCount) = struct.unpack_from(endianess + 'QQQII', binProfile, binOffset)
    binOffset += 8 + 8 + 8 + 4 + 4
except Exception as e:
    raise Exception("unexpected end of input file")

if (sampleCount == 0):
    raise Exception("input file does not contain any samples")

if pmuSize == 0:
  pmuSize = profilePmuSize
  pmuCode = f'{pmuSize}{pmuCode}'
elif pmuSize != profilePmuSize:
  raise Exception(f"incorrect pmu type specified to unpack, profile contains pmu data type of {profilePmuSize} byte(s)")

if args.output:
  outputCSV = xopen.xopen(args.output, "w")
else:
  outputCSV = sys.stdout

if not args.no_comment:
  outputCSV.write(f"# total_time({float(wallTimeUs) / 1000000.0}), latency_time({float(latencyTimeUs) / 1000000.0}), samples({sampleCount}))\n")

outputCSV.write(args.delimiter.join(['time', 'cpu_time', 'thread_id', 'address', 'pmu_' + ['custom', 'current', 'voltage', 'power'][magic]]) + "\n")

startWallTimeMs = None
lastWallTimeMs = None

for i in range(sampleCount):
    try:
        (wallTimeMs, pmuValue, threadCount, ) = struct.unpack_from(endianess + "Q" + pmuCode + "I", binProfile, binOffset)
        binOffset += 8 + pmuSize + 4
    except Exception as e:
        raise Exception("unexcepted end of input file")

    if lastWallTimeMs is not None and wallTimeMs < lastWallTimeMs:
      raise Exception("unexpected sample time wall time (smaller than previous' samples)")

    normWallTimeMs = (wallTimeMs - startWallTimeMs) if startWallTimeMs is not None else 0
    startWallTimeMs = startWallTimeMs if startWallTimeMs is not None else wallTimeMs
    lastWallTimeMs = wallTimeMs

    for j in range(threadCount):
        try:
          (threadId, address, cpuTimeNs, ) = struct.unpack_from(endianess + "IQQ", binProfile, binOffset)
          binOffset += 4 + 8 + 8
        except Exception as e:
          raise Exception("unexcepted end of input file")
        outputCSV.write(args.delimiter.join(map(str, [normWallTimeMs / 1000000.0, cpuTimeNs / 1000000000.0, threadId, f"0x{address:x}", pmuValue if args.pmu_type != 'binary' else '0x' + binascii.hexlify(pmuValue).decode('utf-8')])) + "\n")

if args.output:
  outputCSV.close()

if args.vmmap is not None:
  vmmaps = []
  for i in range(vmmapCount):
      try:
          (addr, size, label,) = struct.unpack_from(endianess + "QQ256s", binProfile, binOffset)
          binOffset += 256 + 16
      except Exception as e:
          raise Exception("unexpected end of input file!")
      vmmaps.append([addr, size, label.decode('utf-8').rstrip('\0')])

  vmmapsString = '\n'.join([f"{x[0]:x} {x[1]:x} {x[2]}" for x in vmmaps])
  outputVMMaps = xopen.xopen(args.vmmap, "w")
  outputVMMaps.write(vmmapsString)
  outputVMMaps.close()
