#!/usr/bin/env python3
import argparse
import profileLib

parser = argparse.ArgumentParser(description="Create cache for elf files")
parser.add_argument("elf", help="executable to create cache")
parser.add_argument("-n", "--name", help="choose a different name for this executable", default=None)
parser.add_argument("-d", "--dynmap", help="provide dynamic branch informations as csv", default=None)
parser.add_argument("-s", "--search-path", help="add search path for source code files", action="append", default=[])
parser.add_argument("--no-source", help="do not include source code", action="store_true", default=False)
parser.add_argument("--no-basic-block-reconstruction", help="do not try to reconstruct basic blocks", action="store_true", default=False)
args = parser.parse_args()

if profileLib.disableCache:
    print('INFO: cache is disabled, nothing will be written to disc')

cache = profileLib.elfCache();
cache.createCache(args.elf, name=args.name, sourceSearchPaths = args.search_path, dynmapfile=args.dynmap, includeSource=not args.no_source, basicblockReconstruction=not args.no_basic_block_reconstruction);
