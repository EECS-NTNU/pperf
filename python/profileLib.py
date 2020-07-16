#!/usr/bin/env python3
import sys
import bz2
import re
import os
import subprocess
import hashlib
import pickle
import pathlib
from filelock import FileLock
import tempfile

LABEL_UNKNOWN = '_unknown'
LABEL_FOREIGN = '_foreign'
LABEL_KERNEL = '_kernel'

aggProfileVersion = 'a0.7'
profileVersion = '0.5'
cacheVersion = '0.1'

aggTime = 0
aggPower = 1
aggEnergy = 2
aggSamples = 3
aggExecs = 4
aggLabel = 5

disableInlineUnwinding = False if 'UNWIND_INLINE' not in os.environ else (True if os.environ['UNWIND_INLINE'] == '0' else False)
disableCache = True if disableInlineUnwinding else (False if 'DISABLE_CACHE' not in os.environ else (True if os.environ['DISABLE_CACHE'] == '1' else False))
crossCompile = "" if 'CROSS_COMPILE' not in os.environ else os.environ['CROSS_COMPILE']
_cppfiltCache = {}
_toolchainVersion = False


def getToolchainVersion():
    global _toolchainVersion
    global crossCompile
    if _toolchainVersion is not False:
        return _toolchainVersion
    addr2line = subprocess.run(f"{crossCompile}addr2line -v | head -n 1 | egrep -Eo '[0-9]+\.[0-9.]+$'", shell=True, stdout=subprocess.PIPE)
    addr2line.check_returncode()
    _toolchainVersion = crossCompile + addr2line.stdout.decode('utf-8').split('\n')[0]
    return _toolchainVersion


def parseRange(stringRange):
    result = []
    for part in stringRange.split(','):
        if '-' in part:
            a, b = part.split('-')
            a, b = int(a), int(b)
            result.extend(range(a, b + 1))
        else:
            a = int(part)
            result.append(a)
    return result


def demangleFunction(function):
    global _cppfiltCache
    global crossCompile
    if function in _cppfiltCache:
        return _cppfiltCache[function]
    cppfilt = subprocess.run(f"{crossCompile}c++filt -i '{function}'", shell=True, stdout=subprocess.PIPE)
    cppfilt.check_returncode()

    _cppfiltCache[function] = cppfilt.stdout.decode('utf-8').split("\n")[0]
    return _cppfiltCache[function]


def decodeAddr2Line(output, demangle=True):
    lines = output.split('\n')
    while len(lines[-1]) == 0:
        lines.pop()
    if (len(lines) < 3):
        raise Exception('addr2line output malformed!')
    address = int(lines[0], 0)
    function = LABEL_UNKNOWN if lines[-2] == '??' else lines[-2]
    demangled = function
    if (demangle and demangled != LABEL_UNKNOWN):
        demangled = demangleFunction(demangled)
    location = lines[-1].split(' ')[0].split(':')
    sourcefile = LABEL_UNKNOWN if location[0] == '??' else location[0]
    sourceline = 0 if location[1] == '?' else int(location[1])
    return {
        'address': address,
        'function': function,
        'demangled': demangled,
        'sourcefile': sourcefile,
        'sourceline': sourceline
    }


def batchAddr2line(elf, pcs, demangle=True):
    global crossCompile
    tmpFile, tmpFilename = tempfile.mkstemp()
    result = {}
    try:
        with os.fdopen(tmpFile, 'w') as tmp:
            for pc in pcs:
                tmp.write(f"0x{pc:x}\n")
        addr2line = subprocess.run(f"{crossCompile}addr2line -fsai -e {elf} @{tmpFilename}", shell=True, stdout=subprocess.PIPE)
        addr2line.check_returncode()
        parsed = addr2line.stdout.decode('utf-8').split("\n0x")
        first = True
        for x in parsed:
            x = x if first else '0x' + x
            first = False
            decoded = decodeAddr2Line(x, demangle)
            result[decoded['address']] = [decoded['sourcefile'], decoded['function'], decoded['demangled'], decoded['sourceline']]
    finally:
        os.remove(tmpFilename)

    return result


def addr2line(elf, pc, demangle=True):
    global crossCompile
    global disableInlineUnwinding
    inlineOption = 'i' if not disableInlineUnwinding else ''
    addr2line = subprocess.run(f"{crossCompile}addr2line -fsa{inlineOption} -e {elf} {pc:x}", shell=True, stdout=subprocess.PIPE)
    addr2line.check_returncode()
    decoded = decodeAddr2Line(addr2line.stdout.decode('utf-8'), demangle)
    return [decoded['sourcefile'], decoded['function'], decoded['demangled'], decoded['sourceline']]


# Work in Progress
class elfCache:
    cacheFolder = str(pathlib.Path.home()) + "/.cache/pperf/"

    caches = {}

    def __init__(self):
        if not os.path.isdir(self.cacheFolder):
            os.makedirs(self.cacheFolder)

    def getDataFromPC(self, elf, pc):
        if elf not in self.caches:
            self.openOrCreateCache(elf)
        if pc not in self.caches[elf]['cache']:
            print(f"WARNING: 0x{pc:x} does not exist in cache for file {elf}", file=sys.stderr)
            return addr2line(elf, pc)
        else:
            return self.caches[elf]['cache'][pc]

    def openOrCreateCache(self, elf):
        global cacheVersion
        cacheName = self.getCacheName(elf)
        lock = FileLock(cacheName + ".lock")
        lock.acquire()
        if os.path.isfile(cacheName):
            lock.release()
            try:
                self.caches[elf] = pickle.load(open(cacheName, mode="rb"))
            except Exception:
                os.remove(cacheName)
                self.openOrCreateCache(elf)
            if 'version' not in self.caches[elf] or self.caches[elf]['version'] != cacheVersion:
                raise Exception(f"Wrong version of cache for {elf} located at {cacheName}!")
            if self.caches[elf]['toolchain'] != getToolchainVersion():
                raise Exception(f"Toolchain version of cache for {elf} located at {cacheName} does not match")
        else:
            self.caches[elf] = {'version': cacheVersion, 'toolchain': getToolchainVersion(), 'cache': {}}
            readelf = subprocess.run(f"readelf -lW {elf} 2>/dev/null | awk '$0 ~ /LOAD.+ R.E 0x/ {{print $3\":\"$6}}'", shell=True, stdout=subprocess.PIPE)
            readelf.check_returncode()
            maps = readelf.stdout.decode('utf-8').split('\n')[:-1]
            for map in maps:
                start = int(map.split(":")[0], 0)
                end = int(map.split(":")[1], 0) + start
                print(f"\rCreating address cache for {elf} from 0x{start:x} to 0x{end:x}...", file=sys.stderr)
                self.caches[elf]['cache'].update(batchAddr2line(elf, list(range(start, end + 1))))

            pickle.dump(self.caches[elf], open(cacheName, "wb"), pickle.HIGHEST_PROTOCOL)
            lock.release()

    def getCacheName(self, elf):
        global crossCompile
        hasher = hashlib.md5()
        with open(elf, 'rb') as afile:
            hasher.update(afile.read())
        return self.cacheFolder + '/elfcache_' + hasher.hexdigest()


class sampleParser:
    useDemangling = True
    binaries = []
    kallsyms = []
    binaryMap = []
    functionMap = []
    _functionMap = []
    fileMap = []
    searchPaths = []
    _fetched_pc_data = {}
    cache = None

    def __init__(self, labelUnknown=LABEL_UNKNOWN, labelForeign=LABEL_FOREIGN, labelKernel=LABEL_KERNEL, useDemangling=True, pcHeuristic=False):
        global disableCache
        self.binaryMap = [labelUnknown, labelForeign]
        self.functionMap = [[labelUnknown, labelUnknown], [labelForeign, labelForeign]]
        self._functionMap = [x[0] for x in self.functionMap]
        self.fileMap = [labelUnknown, labelForeign]
        self.useDemangling = useDemangling
        self.LABEL_KERNEL = labelKernel
        self.LABEL_UNKNOWN = labelUnknown
        self.LABEL_FOREIGN = labelForeign
        self.searchPaths = []
        self._fetched_pc_data = {}
        self._pc_heuristic = pcHeuristic
        self.cache = elfCache() if not disableCache else None

    def addSearchPath(self, path):
        if not isinstance(path, list):
            path = [path]
        for p in path:
            if not os.path.isdir(p):
                raise Exception(f"Not a directory '{path}'")
        self.searchPaths.extend(path)

    def loadVMMap(self, fromFile=False, fromBuffer=False):
        if (not fromFile and not fromBuffer):
            raise Exception("Not enough arguments")
        if (fromFile and not os.path.isfile(fromFile)):
            raise Exception(f"File '{fromFile}' not found")

        if (fromFile):
            if fromFile.endswith("bz2"):
                fromBuffer = bz2.open(fromFile, 'rt').read()
            else:
                fromBuffer = open(fromFile, "r").read()

        for line in fromBuffer.split("\n"):
            if (len(line) > 2):
                (addr, size, label,) = line.split(" ", 2)
                addr = int(addr, 16)
                size = int(size, 16)

                found = False
                static = False
                for searchPath in self.searchPaths:
                    path = f"{searchPath}/{label}"
                    if (os.path.isfile(path)):
                        readelf = subprocess.run(f"readelf -h {path}", shell=True, stdout=subprocess.PIPE)
                        readelfsection = subprocess.run(f"readelf -lW {path} 2>/dev/null | awk '$0 ~ /LOAD.+ R.E 0x/ {{print $3\":\"$6}}'", shell=True, stdout=subprocess.PIPE)
                        try:
                            readelf.check_returncode()
                            readelfsection.check_returncode()
                            static = True if re.search("Type:[ ]+EXEC", readelf.stdout.decode('utf-8'), re.M) else False
                            offset = int(readelfsection.stdout.decode('utf-8').split('\n')[:-1][0].split(":")[0], 0)
                            found = True
                            break
                        except Exception as e:
                            pass

                if found:
                    # Not seen so far but a binary could have multiple code sections which wouldn't work with that structure so far:
                    # print(f"Using offset {offset:x} for {label}")
                    self.binaries.append({
                        'binary': label,
                        'path': path,
                        'kernel': False,
                        'skewed': False,
                        'static': static,
                        'offset': offset,
                        'start': addr,
                        'size': size,
                        'end': addr + size
                    })
                else:
                    raise Exception(f"Could not find {label}")

    def loadKallsyms(self, fromFile=False, fromBuffer=False):
        if (not fromFile and not fromBuffer):
            raise Exception("Not enough arguments")
        if (fromFile and not os.path.isfile(fromFile)):
            raise Exception(f"File '{fromFile}' not found")
        if (fromFile):
            if fromFile.endswith("bz2"):
                fromBuffer = bz2.open(fromFile, 'rt').read()
            else:
                fromBuffer = open(fromFile, "r").read()

        for symbol in fromBuffer.split('\n'):
            s = symbol.split(" ")
            if len(s) >= 3:
                self.kallsyms.append([int(s[0], 16), s[2]])

        if len(self.kallsyms) <= 0:
            return

        kstart = self.kallsyms[0][0]

        self.binaries.append({
            'binary': '_kernel',
            'path': '_kernel',
            'kernel': True,
            'static': False,
            'skewed': False,
            'start': kstart,
            'offset': 0,
            'size': self.kallsyms[-1][0] - kstart,
            'end': self.kallsyms[-1][0]
        })

        self.kallsyms = [[x - kstart, y] for (x, y) in self.kallsyms]
        self.kallsyms.reverse()

    def enableSkewedPCAdjustment(self):
        raise Exception("Don't use this!")
        fakeHighBits = [0x55, 0x7f, 0xffffff80]
        for binary in self.binaries:
            if binary['skewed'] is False:
                nbinary = binary.copy()
                nbinary['skewed'] = True
                laddr = binary['start'] & 0xffffffff
                haddr = binary['start'] >> 32
                for fakeHigh in fakeHighBits:
                    if haddr != fakeHigh:
                        nbinary['start'] = (fakeHigh << 32) | laddr
                        nbinary['end'] = nbinary['start'] + nbinary['size']
                        self.binaries.append(nbinary.copy())

    def disableSkewedPCAdjustment(self):
        self.binaries = [x for x in self.binaries if not x['skewed']]

    def isPCKnown(self, pc):
        if self.getBinaryFromPC(pc) is False:
            return False
        return True

    def getBinaryFromPC(self, pc):
        for binary in self.binaries:
            if (pc >= binary['start'] and pc <= binary['end']):
                return binary
        return False

    def parseFromPC(self, pc):
        if pc in self._fetched_pc_data:
            return self._fetched_pc_data[pc]

        binary = self.getBinaryFromPC(pc)
        if binary is not False:
            # Static pc is used as is
            # dynamic pc points into a virtual memory range which was mapped according to the vmmap
            # the binary on e.g. x86 are typically mapped using an offset to the actual code section
            # in the binary meaning the read pc value must be treated with the offset for correlation
            srcpc = pc if binary['static'] else (pc - binary['start']) + binary['offset']
            srcbinary = binary['binary']

            if binary['kernel']:
                srcfunction = self.LABEL_UNKNOWN
                srcdemangled = self.LABEL_UNKNOWN
                srcfile = self.LABEL_UNKNOWN
                srcline = 0
                for f in self.kallsyms:
                    if f[0] <= srcpc:
                        srcfunction = f[1]
                        srcdemangled = f[1]
                        break
            else:
                srcfile, srcfunction, srcdemangled, srcline = addr2line(binary['path'], srcpc) if self.cache is None else self.cache.getDataFromPC(binary['path'], srcpc)
        else:
            srcpc = pc
            srcbinary = self.LABEL_FOREIGN
            srcfile = self.LABEL_FOREIGN
            srcfunction = self.LABEL_FOREIGN
            srcdemangled = self.LABEL_FOREIGN
            srcline = 0

        if srcbinary not in self.binaryMap:
            self.binaryMap.append(srcbinary)
        if srcfunction not in self._functionMap:
            self.functionMap.append([srcfunction, srcdemangled])
            self._functionMap.append(srcfunction)
        if srcfile not in self.fileMap:
            self.fileMap.append(srcfile)

        result = [
            srcpc,
            self.binaryMap.index(srcbinary),
            self.fileMap.index(srcfile),
            self._functionMap.index(srcfunction),
            srcline
        ]

        self._fetched_pc_data[pc] = result
        return result

    def parseFromSample(self, sample):
        if sample[1] not in self.binaryMap:
            self.binaryMap.append(sample[1])
        if sample[2] not in self.fileMap:
            self.fileMap.append(sample[2])
        if sample[3] not in self._functionMap:
            self.functionMap.append([sample[3], sample[4]])
            self._functionMap.append(sample[3])

        result = [
            sample[0],
            self.binaryMap.index(sample[1]),
            self.fileMap.index(sample[2]),
            self._functionMap.index(sample[3]),
            sample[5]
        ]
        return result

    def getBinaryMap(self):
        return self.binaryMap

    def getFunctionMap(self):
        return self.functionMap

    def getFileMap(self):
        return self.fileMap


class sampleFormatter():
    binaryMap = []
    functionMap = []
    fileMap = []

    def __init__(self, binaryMap, functionMap, fileMap):
        self.binaryMap = binaryMap
        self.functionMap = functionMap
        self.fileMap = fileMap

    def getSample(self, data):
        return [
            data[0],
            self.binaryMap[data[1]],
            self.fileMap[data[2]],
            self.functionMap[data[3]][0],
            self.functionMap[data[3]][1],
            data[4]
        ]

    def formatData(self, data, displayKeys=[1, 4], delimiter=":", doubleSanitizer=[LABEL_FOREIGN, LABEL_UNKNOWN, LABEL_KERNEL], lStringStrip=False, rStringStrip=False):
        return self.sanitizeOutput(
            self.formatSample(self.getSample(data), displayKeys, delimiter),
            delimiter,
            doubleSanitizer,
            lStringStrip,
            rStringStrip
        )

    def formatSample(self, sample, displayKeys=[1, 4], delimiter=":"):
        return delimiter.join([f"0x{sample[x]:x}" if x == 0 else str(sample[x]) for x in displayKeys])

    def sanitizeOutput(self, output, delimiter=":", doubleSanitizer=[LABEL_FOREIGN, LABEL_UNKNOWN, LABEL_KERNEL], lStringStrip=False, rStringStrip=False):
        if doubleSanitizer is not False:
            if not isinstance(doubleSanitizer, list):
                doubleSanitizer = [doubleSanitizer]
            for double in doubleSanitizer:
                output = output.replace(f"{double}{delimiter}{double}", f"{double}")
        if lStringStrip is not False:
            if not isinstance(lStringStrip, list):
                lStringStrip = [lStringStrip]
            for lstrip in lStringStrip:
                output = re.sub(r"^" + re.escape(lstrip), "", output).lstrip(delimiter)
        if rStringStrip is not False:
            if not isinstance(rStringStrip, list):
                rStringStrip = [rStringStrip]
            for rstrip in rStringStrip:
                output = re.sub(re.escape(rstrip) + r"$", "", output).rstrip(delimiter)
        return output
