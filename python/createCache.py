#!/usr/bin/env python3
import argparse
import profileLib

parser = argparse.ArgumentParser(description="Create cache for elf files")
parser.add_argument("elfs", help="executables to create cache", nargs="+")
parser.add_argument("-f", "--force", default=False, action="store_true", help="forces rebuild of cache")
parser.add_argument("-n", "--name", help="choose a different name for this executable", default=None)
parser.add_argument("-d", "--dynmap", help="provide dynamic branch informations as csv", default=None)
parser.add_argument("-s", "--search-path", help="add search path for source code files", action="append", default=[])
parser.add_argument("--unwind-inline", help="unwind inlined functions", action="store_true", default=False)
parser.add_argument("--with-sources", help="do not include source code", action="store_true", default=False)
parser.add_argument("--no-basic-block-reconstruction", help="do not try to reconstruct basic blocks", action="store_true", default=False)
args = parser.parse_args()

if args.unwind_inline:
    profileLib.unwindInline = True

if profileLib.disableCache:
    print('INFO: cache is disabled, nothing will be written to disc')

cache = profileLib.elfCache();

for elf in args.elfs:
    if cache.cacheAvailable(elf) and not args.force:
        print(f'INFO: cache for file {elf} already available at {cache.getCacheFile(elf)}, force rebuild via --force')
    else:
        cache.createCache(elf, name=args.name, sourceSearchPaths = args.search_path, dynmapfile=args.dynmap, includeSource=args.with_sources, basicblockReconstruction=not args.no_basic_block_reconstruction);
    cache.closeCache(elf)
