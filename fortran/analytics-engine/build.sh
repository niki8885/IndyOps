#!/bin/sh

set -e
d="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$d/bin" "$d/build"

gcc -O2 -c "$d/src/compat.c" -o "$d/build/compat.o"

FLAGS="-O2 -fwrapv -std=f2008 -Wall -J$d/build -I$d/build"

# analytics-engine: indicators / risk / index report
gfortran $FLAGS \
    "$d/src/json.f90" "$d/src/sort_stats.f90" "$d/src/rng.f90" \
    "$d/src/indicators.f90" "$d/src/risk.f90" "$d/src/report.f90" \
    "$d/app/main.f90" "$d/build/compat.o" \
    -o "$d/bin/analytics-engine"
echo "built $d/bin/analytics-engine"

# profit-sim: Monte-Carlo profit simulator (reuses json / sort_stats / rng)
gfortran $FLAGS \
    "$d/src/json.f90" "$d/src/sort_stats.f90" "$d/src/rng.f90" \
    "$d/src/distrib.f90" "$d/src/montecarlo.f90" "$d/app/profitsim.f90" \
    "$d/build/compat.o" \
    -o "$d/bin/profit-sim"
echo "built $d/bin/profit-sim"

# scenario-sim: Scenario Simulation engine
gfortran $FLAGS \
    "$d/src/json.f90" "$d/src/sort_stats.f90" "$d/src/rng.f90" \
    "$d/src/distrib.f90" "$d/src/scenario.f90" "$d/app/scenariosim.f90" \
    "$d/build/compat.o" \
    -o "$d/bin/scenario-sim"
echo "built $d/bin/scenario-sim"
