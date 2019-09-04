#!/usr/bin/python3
import sys
import argparse
import profileLib

aggregateKeyNames = ["pc", "binary", "file", "procedure_mangled", "procedure", "line"]

parser = argparse.ArgumentParser(description="Create cache for elf files")
parser.add_argument("elfs", help="executable to create cache", nargs="+")
args = parser.parse_args()

if profileLib.disableCache:
    print("Caching is disabled via environment variable DISABLE_CACHE!");
    sys.exit(1);

for elf in args.elfs:
    cache = profileLib.elfCache();
    cache.openOrCreateCache(elf);
    del cache;
