#!/usr/bin/env python3

import sys
import argparse
import bz2
import pickle
import profileLib
import os
import gc
from xopen import xopen

parser = argparse.ArgumentParser(description="Output profile informations.")
parser.add_argument("profiles", help="postprocessed or aggregated profiles", nargs="+")


args = parser.parse_args()

if (not args.profiles) or (len(args.profiles) <= 0):
    print("ERROR: unsufficient amount of profiles passed")
    parser.print_help()
    sys.exit(1)

for i, fileProfile in enumerate(args.profiles):
    if i > 0:
        print("")

    try:
        profile = pickle.load(xopen(fileProfile, mode="rb"))
    except:
        raise Exception(f'Could not read file {fileProfile}')

    if 'version' not in profile:
        raise Exception(f"Could not identify file {fileProfile}")

    if profile['version'] == profileLib.profileVersion:
        print(f"{fileProfile} is a full profile:")
    elif profile['version'] == profileLib.aggProfileVersion:
        print(f"{fileProfile} is an aggregated profile:")
    elif profile['version'] == profileLib.annProfileVersion:
        print(f"{fileProfile} is an annotated profile:")
    elif profile['version'] == profileLib.cacheVersion:
        print(f"{fileProfile} is a cache:")
    else:
        raise Exception(f"Unknown file version {profile['version']} in {fileProfile}")

    if not profile['version'] == profileLib.cacheVersion:
        print(f"    Samples:      {profile['samples']}")
        print(f"    Time:         {profile['samplingTime']} s")
        print(f"    Frequency:    {profile['samples'] / profile['samplingTime']} Hz")
        print(f"    Latency:      {profile['latencyTime']} s")
        print(f"    Energy:       {profile['energy']} J")
        print(f"    Power:        {profile['power']} W")
        print(f"    Name:         {profile['name']}")
        print(f"    Target:       {profile['target']}")

    if profile['version'] == profileLib.profileVersion:
        print(f"    Volts:        {profile['volts']}")
        print(f"    CPUs:         {profile['cpus']}")
        print(f"    Caches:       {profile['cacheMap']}")
    elif profile['version'] == profileLib.aggProfileVersion:
        print(f"    Volts:        {profile['volts']}")
        print(f"    Mean:         {profile['mean']}")
    elif profile['version'] == profileLib.annProfileVersion:
        pass
    elif profile['version'] == profileLib.cacheVersion:
        print(f"    Binary:       {profile['binary']}")
        print(f"    Name:         {profile['name']}")
        print(f"    Arch:         {profile['arch']}")
        print(f"    Date:         {profile['date']}")
        print(f"    Inlines:      {profile['unwindInline']}")
        print(f"    Files:        {', '.join([os.path.basename(x) for x in profile['source']])}")
        #for f in profile['source']:
        #    print(f'File {f} has {len(profile["source"][f])}')
        #    for l in profile["source"][f]:
        #        print(l)
        print(f"    ASM Lines:    {len(profile['asm'])}")
        print(f"    Source Lines: {sum([len(profile['source'][x]) for x in profile['source']])}")

    print(f"    Toolchain:    {profile['toolchain']}")

    del profile
    gc.collect()
