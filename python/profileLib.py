#!/usr/bin/env python3
import sys
import xopen
import re
import os
import subprocess
import hashlib
import pickle
import pathlib
from filelock import FileLock
from datetime import datetime
import tempfile
import csv
from copy import copy

LABEL_UNKNOWN = '_unknown'
LABEL_FOREIGN = '_foreign'
LABEL_KERNEL  = '_kernel'
LABEL_UNSUPPORTED = '_unsupported'

cacheVersion = 'c0.3'
profileVersion = '0.5'
aggProfileVersion = 'agg0.9'
annProfileVersion = 'ann0.1'

unwindInline = True if 'UNWIND_INLINE' in os.environ and os.environ['UNWIND_INLINE'] == '1' else False
disableCache = True if 'DISABLE_CACHE' in os.environ and os.environ['DISABLE_CACHE'] == '1' else False
crossCompile = "" if 'CROSS_COMPILE' not in os.environ else os.environ['CROSS_COMPILE']
cacheFolder = str(pathlib.Path.home()) + "/.cache/pperf/" if 'PPERF_CACHE' not in os.environ or len(os.environ['PPERF_CACHE']) == 0 else os.environ['PPERF_CACHE']
_toolchainVersion = None


class AGGSAMPLE:
    time         = 0
    power        = 1
    energy       = 2
    samples      = 3
    execs        = 4
    label        = 5
    mappedSample = 6


class SAMPLE:
    pc          = 0  # int
    binary      = 1  # str
    file        = 2  # str
    function    = 3  # str
    basicblock  = 4  # str
    line        = 5  # int
    instruction = 6  # str
    opcode      = 7  # int
    meta        = 8  # int
    names = ['pc', 'binary', 'file', 'function', 'basicblock', 'line', 'instruction', 'opcode', 'meta']
    invalid = [None, None, None, None, None, None, None, None, None]


class META:
    normalInstruction    = 0
    branchInstruction    = 1
    branchTarget         = 2
    dynamicBranchTarget  = 4
    functionHead         = 8
    functionBack         = 16
    basicblockHead       = 32
    basicblockBack       = 64


def getToolchainVersion():
    global _toolchainVersion
    if _toolchainVersion is not None:
        return _toolchainVersion
    global crossCompile
    addr2line = subprocess.run(f"{crossCompile}addr2line -v | head -n 1 | egrep -Eo '[0-9]+\.[0-9.]+$'", shell=True, stdout=subprocess.PIPE)
    addr2line.check_returncode()
    _toolchainVersion = crossCompile + addr2line.stdout.decode('utf-8').split('\n')[0]
    return _toolchainVersion


def getElfArchitecture(elf: str):
    readelf = subprocess.run(f'readelf -h {elf}', shell=True, stdout=subprocess.PIPE)
    readelf.check_returncode()
    for line in readelf.stdout.decode('utf-8').split('\n'):
        line = line.strip()
        if line.startswith('Machine:'):
            return line.split(':', 1)[1].strip()
    return None


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


class elfCache:
    # Basic Block Reconstruction:
    # currently requires support through dynamic branch analysis which
    # provides a csv with dynamic branches and their targets to accuratly
    # reconstruct basic blocks
    # AArch64 - Stable
    # RISC-V  - Experimental
    archBranches = {
        'AArch64': {
            # These instruction divert the control flow of the application
            'all': {'b', 'b.eq', 'b.ne', 'b.cs', 'b.hs', 'b.cc', 'b.lo', 'b.mi', 'b.pl', 'b.vs', 'b.vc', 'b.hi', 'b.ls', 'b.ge', 'b.lt', 'b.gt', 'b.le', 'b.al', 'b.nv', 'bl', 'br', 'blr', 'svc', 'brk', 'ret', 'cbz', 'cbnz', 'tbnz'},
            # These instructions are dynamic branches that can only divert control flow towards the head of a basicblock/function or after another branch instruction
            'remote': {'svc', 'brk', 'blr', 'ret'},
        },
        'RISC-V': {
            'all': {'j', 'jal', 'jr', 'jalr', 'ret', 'call', 'tail', 'bne', 'beq', 'blt', 'bltu', 'bge', 'bgeu', 'beqz', 'bnez', 'blez', 'bgez', 'bltz', 'bgtz', 'bgt', 'ble', 'bgtu', 'bleu', 'ecall', 'ebreak', 'scall', 'sbreak'},
            'remote': {'ebreak', 'ecall', 'sbreak', 'scall', 'jalr', 'ret'},
        }
    }

    caches = {}
    cacheFiles = {}

    def __init__(self):
        global cacheFolder
        if not os.path.isdir(cacheFolder):
            os.makedirs(cacheFolder)
    


    def getRawCache(self, name):
        global cacheFolder
        name = os.path.abspath(f'{cacheFolder}/{name}')
        lock = FileLock(name + ".lock")
        # If the lock is held this will stall
        lock.acquire()
        lock.release()
        if os.path.isfile(name):
            return pickle.load(open(name, mode="rb"))
        else:
            raise Exception(f'could not find requested elf cache {name}')

    def getCacheFile(self, elf):
        if elf in self.cacheFiles:
            return self.cacheFiles[elf]
        global cacheFolder
        global unwindInline
        hasher = hashlib.md5()
        with open(elf, 'rb') as afile:
            hasher.update(afile.read())
        return os.path.abspath(f"{cacheFolder}/{os.path.basename(elf)}_{'i' if unwindInline else ''}{hasher.hexdigest()}")

    def getCache(self, elf):
        self.openOrCreateCache(elf)
        return self.caches[elf]

    def openOrCreateCache(self, elf: str):
        global disableCache
        if not self.cacheAvailable(elf):
            if disableCache:
                print("WARNING: cache disabled, constructing limited in memory cache", file=sys.stderr)
                self.createCache(elf, basicblockReconstruction=False, includeSource=False, verbose=False)
            else:
                raise Exception(f'could not find cache for file {elf}, please create first or run with disabled cache')

    def getSampleFromPC(self, elf: str, pc: int):
        self.openOrCreateCache(elf)
        if pc not in self.caches[elf]['cache']:
            print(f"WARNING: 0x{pc:x} does not exist in {elf}", file=sys.stderr)
            sample = copy(SAMPLE.invalid)
            sample[SAMPLE.binary] = self.caches[elf]['name']
            sample[SAMPLE.pc] = pc
            return sample
        else:
            return self.caches[elf]['cache'][pc]

    def cacheAvailable(self, elf: str, load=True):
        if elf in self.caches:
            return True
        global disableCache
        if disableCache:
            return False
        global cacheVersion
        cacheFile = self.getCacheFile(elf)
        lock = FileLock(cacheFile + ".lock")
        # If the lock is held this will stall
        lock.acquire()
        lock.release()
        if os.path.isfile(cacheFile):
            cache = pickle.load(open(cacheFile, mode="rb"))
            if 'version' not in cache or cache['version'] != cacheVersion:
                raise Exception(f"wrong version of cache for {elf} located at {cacheFile}!")
            if load:
                self.cacheFiles[elf] = cacheFile
                self.caches[elf] = cache
            return True
        else:
            return False

    def closeCache(self, elf):
        if elf in self.cacheFiles:
            del self.cacheFiles[elf]
        if elf in self.caches:
            del self.caches[elf]

    def createCache(self, elf: str, name=None, sourceSearchPaths=[], dynmapfile=None, includeSource=True, basicblockReconstruction=True, verbose=True):
        global cacheVersion
        global crossCompile
        global unwindInline
        global disableCache

        if name is None:
            name = os.path.basename(elf)

        if not disableCache:
            cacheFile = self.getCacheFile(elf)
            lock = FileLock(cacheFile + ".lock")
            lock.acquire()

            # Remove the cache if it already exists
            if os.path.isfile(cacheFile):
                os.remove(cacheFile)

        try:

            functionCounter = -1

            cache = {
                'version': cacheVersion,
                'binary': os.path.basename(elf),
                'name': name,
                'arch': getElfArchitecture(elf),
                'date': datetime.now(),
                'toolchain': getToolchainVersion(),
                'unwindInline': unwindInline,
                'cache': {},
                'source': {},
                'asm': {},
            }

            if cache['arch'] not in self.archBranches and basicblockReconstruction:
                basicblockReconstruction = False
                if verbose:
                    print(f"WARNING: disabling basic block reconstruction due to unknown architecture {cache['arch']}")

            sPreObjdump = f"{crossCompile}objdump -wh {elf}"
            pPreObjdump = subprocess.Popen(sPreObjdump, shell=True, stdout=subprocess.PIPE, universal_newlines=True)
            for sectionLine in pPreObjdump.stdout:
                sectionLine = re.sub(r', ', ',', sectionLine)
                sectionList = re.sub(r'[\t ]+', ' ', sectionLine).strip().split(' ')
                # Check whether we write, allocate or execute a section
                if len(sectionList) < 7 or 'CODE' not in sectionList[7]:
                    continue
                section = sectionList[1]

                # First step is creating an object dump of the elf file
                # We disassemble much more than needed however its necesarry for some profilers
                sObjdump = f"{crossCompile}objdump -Dwz --prefix-addresses --show-raw-insn -j {section} {elf}"
                # sObjdump = f"{crossCompile}objdump -Dz --prefix-addresses -j {section} {elf}"
                pObjdump = subprocess.Popen(sObjdump, shell=True, stdout=subprocess.PIPE, universal_newlines=True)
                # Remove trailing additional data that begins with '//'
                # sObjdump = re.sub('[ \t]+(// ).+\n','\n', sObjdump)
                # Remove trailing additional data that begins with '#'
                # sObjdump = re.sub('[ \t]+(# ).+\n','\n', sObjdump)

                for line in pObjdump.stdout:
                    objdumpLine = re.compile(r'([0-9a-fA-F]+) <([^+]+)?\+?(0x[0-9a-f-A-F]+)?> ([0-9a-fA-F ]+)[\t]+([^<\t ]+)?(.+)?')
                    match0 = objdumpLine.match(line)
                    if match0:
                        meta = META.normalInstruction
                        if match0.group(3) is None:
                            meta |= META.functionHead | META.basicblockHead
                            functionCounter += 1

                        pc = int(match0.group(1), 16)
                        instr = match0.group(5).rstrip('\n').strip()
                        opcode = match0.group(4).replace(' ', '').strip()
                        func = match0.group(1).strip()

                        sample = [pc, name, None, func, f'f{functionCounter}', None, instr, opcode, meta]
                        asm = instr
                        if match0.group(6) is not None:
                            asm += match0.group(6).rstrip('\n').rstrip()
                        cache['asm'][pc] = asm
                        cache['cache'][pc] = sample
                pObjdump.stdout.close()
                returnCode = pObjdump.wait()
                if returnCode:
                    raise subprocess.CalledProcessError(returnCode, sObjdump)

            pPreObjdump.stdout.close()
            returnCode = pPreObjdump.wait()
            if returnCode:
                raise subprocess.CalledProcessError(returnCode, sPreObjdump)

            if (len(cache['cache']) == 0):
                raise Exception(f'Could not parse any instructions from {elf}')

            # Second Step, correlate addresses to function/files
            tmpfile, tmpfilename = tempfile.mkstemp()
            try:
                addr2lineDecode = re.compile('^(0x[0-9a-fA-F]+)\n(.+?)\n(.+)?:(([0-9]+)|(\?)).*$')
                with os.fdopen(tmpfile, 'w') as tmp:
                    tmp.write('\n'.join(map(lambda x: f'0x{x:x}', cache['cache'].keys())) + '\n')
                    tmp.close()
                    # addr2line by default outputs the file/line where the instruction originates from
                    # the -i option lets it print the chain of inlining which might be multiple files/lines
                    # We are only intersted in one result per address. We want either the function the
                    # address ends up in or the function it came from (when inlined). It will return the origin
                    # without -i and when -i is passed, the last result will be always the function this
                    # address was inlined to. That means this option is logically inverted for this script
                    # as we only take the last result per address.
                    pAddr2line = subprocess.run(f"{crossCompile}addr2line -Cafr{'i' if not unwindInline else ''} -e {elf} @{tmpfilename}", shell=True, stdout=subprocess.PIPE)
                    pAddr2line.check_returncode()
                    sAddr2line = pAddr2line.stdout.decode('utf-8').split("\n0x")
                    for entry in sAddr2line:
                        matchEntry = (entry if entry.startswith('0x') else '0x' + entry).split('\n')
                        while len(matchEntry) > 3 and len(matchEntry[-1]) == 0:
                            matchEntry.pop()
                        matchEntry = '\n'.join([matchEntry[0], matchEntry[-2], matchEntry[-1]])

                        match = addr2lineDecode.match(matchEntry)
                        if match:
                            iAddr = int(match.group(1), 16)
                            if iAddr not in cache['cache']:
                                raise Exception(f'Got an unknown address from addr2line: {match.group(1)}')
                            if match.group(3) is not None and len(match.group(3).strip('?')) != 0:
                                cache['cache'][iAddr][SAMPLE.file] = match.group(3)
                            if match.group(2) is not None and len(match.group(2).strip('?')) != 0:
                                # If we do source correlation save the absolute path for the moment
                                cache['cache'][iAddr][SAMPLE.function] = match.group(2)
                            if match.group(4) is not None and len(match.group(4).strip('?')) != 0 and int(match.group(4)) != 0:
                                cache['cache'][iAddr][SAMPLE.line] = int(match.group(4))
                        else:
                            raise Exception(f'Could not decode the following addr2line entry\n{entry}')
            finally:
                os.remove(tmpfilename)

            # Third Step, read in source code
            if includeSource:
                # Those encondings will be tried
                all_encodings = ['utf_8', 'latin_1', 'ascii', 'utf_16', 'utf_32', 'iso8859_2', 'utf_8_sig' 'utf_16_be', 'utf_16_le', 'utf_32_be', 'utf_32_le',
                                 'iso8859_3', 'iso8859_4', 'iso8859_5', 'iso8859_6', 'iso8859_7', 'iso8859_8', 'iso8859_9', 'iso8859_10', 'iso8859_11', 'iso8859_12',
                                 'iso8859_13', 'iso8859_14', 'iso8859_15', 'iso8859_16']
                for pc in cache['cache']:
                    if cache['cache'][pc][SAMPLE.file] is not None and cache['cache'][pc][SAMPLE.file] not in cache['source']:
                        targetFile = None
                        sourcePath = cache['cache'][pc][SAMPLE.file]
                        searchPath = pathlib.Path(sourcePath)
                        cache['source'][sourcePath] = None
                        if (os.path.isfile(sourcePath)):
                            targetFile = sourcePath
                        elif len(sourceSearchPaths) > 0:
                            if searchPath.is_absolute():
                                searchPath = pathlib.Path(*searchPath.parts[1:])
                            found = False
                            for search in sourceSearchPaths:
                                currentSearchPath = searchPath
                                while not found and len(currentSearchPath.parts) > 0:
                                    if os.path.isfile(search / currentSearchPath):
                                        targetFile = search / currentSearchPath
                                        found = True
                                        break
                                    currentSearchPath = pathlib.Path(*currentSearchPath.parts[1:])
                                if found:
                                    break

                        if targetFile is not None:
                            decoded = False
                            for enc in all_encodings:
                                try:
                                    with open(targetFile, 'r', encoding=enc) as fp:
                                        cache['source'][sourcePath] = []
                                        for i, line in enumerate(fp):
                                            cache['source'][sourcePath].append(line.strip('\r\n'))
                                    # print(f"Opened file {targetFile} with encoding {enc}")
                                    decoded = True
                                    break
                                except Exception:
                                    pass
                            if not decoded:
                                cache['source'][sourcePath] = None
                                raise Exception(f"could not decode source code {sourcePath}")
                        elif verbose:
                            print(f"WARNING: could not find source code for {os.path.basename(sourcePath)}", file=sys.stderr)

            # Fourth Step, basic block reconstruction
            if basicblockReconstruction:
                # If a dynmap file is provided, read it in and add the dynamic branch informations
                dynmap = {}
                if dynmapfile is None and os.path.isfile(elf + '.dynmap'):
                    dynmapfile = elf + '.dynmap'
                if dynmapfile is not None and os.path.isfile(dynmapfile):
                    try:
                        with open(dynmapfile, "r") as fDynmap:
                            csvDynmap = csv.reader(fDynmap)
                            for row in csvDynmap:
                                try:
                                    fromPc = int(row[0], 0)
                                    toPc = int(row[1], 0)
                                except Exception:
                                    continue
                                if fromPc not in dynmap:
                                    dynmap[fromPc] = [toPc]
                                else:
                                    dynmap[fromPc].append(toPc)
                    except Exception:
                        if verbose:
                            print(f"WARNING: could not read dynamic branch information from {dynmapfile}", file=sys.stderr)

                # pcs = sorted(cache['cache'].keys())
                unresolvedBranches = []
                # First pass to identify branches
                for pc in cache['cache']:
                    instruction = cache['cache'][pc][SAMPLE.instruction].lower()
                    if instruction in self.archBranches[cache['arch']]['all']:
                        cache['cache'][pc][SAMPLE.meta] |= META.branchInstruction
                        asm = cache['asm'][pc].split('\t')
                        if instruction not in self.archBranches[cache['arch']]['remote'] and len(asm) >= 2:
                            branched = False
                            for argument in reversed(re.split(', |,| ', asm[1])):
                                try:
                                    branchTarget = int(argument.strip(), 16)
                                    if branchTarget in cache['cache']:
                                        cache['cache'][branchTarget][SAMPLE.meta] |= META.branchTarget
                                        branched = True
                                        break
                                except Exception:
                                    pass
                            if not branched and verbose:
                                # Might be a branch that has dynmap information or comes from the plt
                                if pc not in dynmap and not (cache['cache'][pc][SAMPLE.function].endswith('.plt') or cache['cache'][pc][SAMPLE.function].endswith('@plt')):
                                    unresolvedBranches.append(pc)

                # Parse dynmap to complete informations
                newBranchTargets = []
                knownBranchTargets = []
                for pc in dynmap:
                    if pc not in cache['cache']:
                        raise Exception(f'address 0x{pc:x} from dynamic branch informations is unknown in file {elf}')
                    if not cache['cache'][pc][SAMPLE.meta] & META.branchInstruction:
                        raise Exception(f'dynamic branch information provided an unknown branch at 0x{pc:x} in file {elf}')
                    # With the Exception this is unecessary
                    # cache['cache'][pc][SAMPLE.meta] |= META.branchInstruction
                    for target in dynmap[pc]:
                        if target not in cache['cache']:
                            raise Exception(f'target address 0x{target:x} from dynamic branch informations is unknown in file {elf}')
                        if not cache['cache'][target][SAMPLE.meta] & META.branchTarget and not cache['cache'][target][SAMPLE.meta] & META.functionHead:
                            newBranchTargets.append(target)
                        else:
                            knownBranchTargets.append(target)
                        cache['cache'][target][SAMPLE.meta] |= META.dynamicBranchTarget
                if verbose and len(newBranchTargets) > 0:
                    print(f"INFO: {len(newBranchTargets)} new branch targets were identified with dynamic branch information ({', '.join([f'0x{x:x}' for x in newBranchTargets])})", file=sys.stderr)
                if verbose and len(knownBranchTargets) > 0:
                    print(f"INFO: {len(knownBranchTargets)} branch targets from dynamic branch information were already known ({', '.join([f'0x{x:x}' for x in knownBranchTargets])})", file=sys.stderr)

                if verbose and len(unresolvedBranches) > 0:
                    print(f"WARNING: {len(unresolvedBranches)} dynamic branches might not be resolved! ({', '.join([f'0x{x:x}' for x in unresolvedBranches])})", file=sys.stderr)
                    # print('\n'.join([cache['asm'][x] for x in unresolvedBranches]))

                # Second pass to resolve the basic blocks
                basicblockCount = 0
                prevPc = None
                for pc in cache['cache']:
                    # If function head, we reset the basicblock counter to zero (functions are already a basicblock)
                    if cache['cache'][pc][SAMPLE.meta] & META.functionHead:
                        basicblockCount = 0
                        cache['cache'][pc][SAMPLE.meta] |= META.basicblockHead
                        if prevPc is not None:
                            cache['cache'][prevPc][SAMPLE.meta] |= META.functionBack | META.basicblockBack
                    # Else, if instruction is a branch target or the previous is a branch we increase the basicblock counter
                    elif (cache['cache'][pc][SAMPLE.meta] & META.branchTarget) or (cache['cache'][pc][SAMPLE.meta] & META.dynamicBranchTarget) or (prevPc is not None and cache['cache'][prevPc][SAMPLE.meta] & META.branchInstruction):
                        basicblockCount += 1
                        cache['cache'][pc][SAMPLE.meta] |= META.basicblockHead
                        if prevPc is not None:
                            cache['cache'][prevPc][SAMPLE.meta] |= META.basicblockBack

                    cache['cache'][pc][SAMPLE.basicblock] += f'b{basicblockCount}'
                    prevPc = pc

            if not disableCache:
                pickle.dump(cache, open(cacheFile, "wb"), pickle.HIGHEST_PROTOCOL)
            self.caches[elf] = cache
        finally:
            if not disableCache:
                lock.release()


class listmapper:
    maps = {}

    def __init__(self, mapping=None):
        if mapping is not None:
            self.addMaping(mapping)

    def removeMapping(self, mapping):
        if isinstance(mapping, list):
            for m in mapping:
                if not isinstance(m, int):
                    raise Exception('class listmapper must be used with integer maps')
                if m in self.maps:
                    del self.maps[m]
        elif isinstance(mapping, int):
            raise Exception('class listmapper must be used with integer maps')
        elif mapping in self.maps:
            del self.maps[mapping]

    def addMaping(self, mapping):
        if isinstance(mapping, list):
            for m in mapping:
                if not isinstance(m, int):
                    raise Exception('class listmapper must be used with integer maps')
                if m not in self.maps:
                    self.maps[m] = []
        elif isinstance(m, int):
            raise Exception('class listmapper must be used with integer maps')
        elif mapping not in self.maps:
            self.maps[mapping] = []

    def mapValues(self, values: list):
        mapped = []
        for i, val in enumerate(values):
            if i in self.maps:
                if val not in self.maps[i]:
                    self.maps[i].append(val)
                mapped.append(self.maps[i].index(val))
            else:
                mapped.append(val)
        return mapped

    def remapValues(self, values: list):
        remapped = []
        for i, val in enumerate(values):
            if i in self.maps:
                if not isinstance(val, int) or val >= len(self.maps[i]):
                    raise Exception(f'listmapper invalid remap request for value {val} in map {i}')
                remapped.append(self.maps[i][val])
            else:
                remapped.append(val)
        return remapped

    def setMaps(self, maps: dict):
        self.maps = maps

    def retrieveMaps(self):
        return self.maps


class sampleParser:
    cache = elfCache()
    # Mapper will compress the samples down to a numeric list
    mapper = listmapper([SAMPLE.binary, SAMPLE.file, SAMPLE.function, SAMPLE.basicblock, SAMPLE.instruction])
    cacheMap = {}

    binaries = []
    kallsyms = []
    searchPaths = []

    _localSampleCache = {}

    def __init__(self):
        pass

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
            fromBuffer = xopen.xopen(fromFile, "r").read()

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
                        except Exception:
                            pass

                if found:
                    # Not seen so far but a binary could have multiple code sections which wouldn't work with that structure so far:
                    # print(f"Using offset {offset:x} for {label}")
                    self.binaries.append({
                        'binary': label,
                        'path': path,
                        'kernel': False,
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
            fromBuffer = xopen.xopen(fromFile, "r").read()

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
            'start': kstart,
            'offset': 0,
            'size': self.kallsyms[-1][0] - kstart,
            'end': self.kallsyms[-1][0]
        })

        self.kallsyms = [[x - kstart, y] for (x, y) in self.kallsyms]
        self.kallsyms.reverse()

    def isPCKnown(self, pc):
        if self.getBinaryFromPC(pc) is False:
            return False
        return True

    def getBinaryFromPC(self, pc):
        for binary in self.binaries:
            if (pc >= binary['start'] and pc <= binary['end']):
                return binary
        return False

    def getSampleFromPC(self, pc):
        binary = self.getBinaryFromPC(pc)
        sample = None

        if binary is not False:
            # Static pc is used as is
            # dynamic pc points into a virtual memory range which was mapped according to the vmmap
            # the binary on e.g. x86 are typically mapped using an offset to the actual code section
            # in the binary meaning the read pc value must be treated with the offset for correlation
            srcpc = pc if binary['static'] else (pc - binary['start']) + binary['offset']

            if binary['kernel']:
                sample = copy(SAMPLE.invalid)
                sample[SAMPLE.pc] = srcpc
                sample[SAMPLE.binary] = binary['binary']
                for f in self.kallsyms:
                    if f[0] <= srcpc:
                        sample[SAMPLE.function] = f[1]
                        break
            else:
                sample = self.cache.getSampleFromPC(binary['path'], srcpc)
                if sample is not None:
                    if sample[SAMPLE.binary] not in self.cacheMap:
                        self.cacheMap[sample[SAMPLE.binary]] = os.path.basename(self.cache.getCacheFile(binary['path']))

        if sample is None:
            sample = copy(SAMPLE.invalid)
            sample[SAMPLE.pc] = pc

        return sample

    def parsePC(self, pc):
        if pc in self._localSampleCache:
            return self._localSampleCache[pc]

        sample = self.getSampleFromPC(pc)
        result = self.mapper.mapValues(sample)

        self._localSampleCache[pc] = result
        return result

    def parseFromSample(self, sample):
        return self.mapper.remapValues(sample)

    def getMaps(self):
        return self.mapper.retrieveMaps()

    def getCacheMap(self):
        return self.cacheMap

    def getName(self, binary):
        self.cache.openOrCreateCache(binary)
        return self.cache.caches[binary]['name']


class sampleFormatter():
    mapper = listmapper()

    def __init__(self, maps):
        self.mapper.setMaps(maps)

    def remapSample(self, sample):
        return self.mapper.remapValues(sample)

    def formatSample(self, sample, displayKeys=[SAMPLE.binary, SAMPLE.function], delimiter=":", labelNone='_unknown'):
        for i, k in enumerate(displayKeys):
            valid = True
            if isinstance(k, str):
                if k not in SAMPLE.names:
                    valid = False
                else:
                    displayKeys[i] = SAMPLE.names.index(k)
            elif isinstance(k, int):
                if i < 0 or i >= len(SAMPLE.names):
                    valid = False
            else:
                valid = False
            if not valid:
                raise Exception(f'class sampleFormatter encountered unknown display key {k}')
        return delimiter.join([str(labelNone) if sample[x] is None else
                               f"0x{sample[x]:x}" if x == SAMPLE.pc else
                               os.path.basename(sample[x]) if x == SAMPLE.file else
                               str(sample[x]) for x in displayKeys])
