#!/usr/bin/env python

import sys
import argparse
import bz2
import pickle
import profileLib


parser = argparse.ArgumentParser(description="Output profile informations.")
parser.add_argument("profiles", help="postprocessed or aggregated profiles", nargs="+")


args = parser.parse_args()

if (not args.profiles) or (len(args.profiles) <= 0):
    print("ERROR: unsufficient amount of profiles passed")
    parser.print_help()
    sys.exit(1)

i = 1
for fileProfile in args.profiles:
    if i != 1:
        print("")

    i += 1
    profile = {}
    if fileProfile.endswith(".bz2"):
        profile = pickle.load(bz2.BZ2File(fileProfile, mode="rb"))
    else:
        profile = pickle.load(open(fileProfile, mode="rb"))

    if 'aggregated' in profile:
        if 'version' not in profile or profile['version'] != profileLib.aggProfileVersion:
            raise Exception(f"Incompatible profile version (required: {profileLib.profileVersion})")
        print(f"{fileProfile}: aggregated profile:")
        print(f"    Samples:   {profile['samples']}")
        print(f"    Time:      {profile['samplingTime']}s")
        print(f"    Latency:   {profile['latencyTime']}s")
        print(f"    Volts:     {profile['volts']}")
        print(f"    Name:      {profile['name']}")
        print(f"    Target:    {profile['target']}")
        print(f"    Mean:      {profile['mean']}")
        if 'toolchain' in profile:
            print(f"    toolchain: {profile['toolchain']}")
    else:
        if 'version' not in profile or profile['version'] != profileLib.profileVersion:
            raise Exception(f"Incompatible profile version (required: {profileLib.profileVersion})")
        print(f"{fileProfile}: single profile:")
        print(f"    Samples:   {profile['samples']}")
        print(f"    Time:      {profile['samplingTime']}s")
        print(f"    Latency:   {profile['latencyTime']}s")
        print(f"    Volts:     {profile['volts']}")
        print(f"    CPUs:      {profile['cpus']}")
        print(f"    Name:      {profile['name']}")
        print(f"    Target:    {profile['target']}")
        if 'toolchain' in profile:
            print(f"    toolchain: {profile['toolchain']}")
