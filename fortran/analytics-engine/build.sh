#!/bin/sh

set -e
d="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$d/bin" "$d/build"

gcc -O2 -c "$d/src/compat.c" -o "$d/build/compat.o"

gfortran -O2 -fwrapv -std=f2008 -Wall -J"$d/build" -I"$d/build" \
    "$d/src/json.f90" "$d/src/sort_stats.f90" "$d/src/rng.f90" \
    "$d/src/indicators.f90" "$d/src/risk.f90" "$d/src/report.f90" \
    "$d/app/main.f90" "$d/build/compat.o" \
    -o "$d/bin/analytics-engine"

echo "built $d/bin/analytics-engine"
