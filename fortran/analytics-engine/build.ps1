$ErrorActionPreference = "Stop"
if (Test-Path "C:\msys64\ucrt64\bin") { $env:Path = "C:\msys64\ucrt64\bin;" + $env:Path }

$d = $PSScriptRoot
New-Item -ItemType Directory -Force "$d\bin", "$d\build" | Out-Null

& gcc -O2 -c "$d\src\compat.c" -o "$d\build\compat.o"
if ($LASTEXITCODE -ne 0) { throw "compat.c build failed ($LASTEXITCODE)" }

$flags = @("-O2", "-fwrapv", "-std=f2008", "-Wall", "-static",
           "-J", "$d\build", "-I", "$d\build")

# analytics-engine: indicators / risk / index report
$sources = @(
    "src\json.f90", "src\sort_stats.f90", "src\rng.f90",
    "src\indicators.f90", "src\risk.f90", "src\report.f90", "app\main.f90"
) | ForEach-Object { Join-Path $d $_ }
& gfortran @flags @sources "$d\build\compat.o" -o "$d\bin\analytics-engine.exe"
if ($LASTEXITCODE -ne 0) { throw "analytics-engine build failed ($LASTEXITCODE)" }
Write-Host "built $d\bin\analytics-engine.exe"

# profit-sim: Monte-Carlo profit simulator (reuses json / sort_stats / rng)
$sim = @(
    "src\json.f90", "src\sort_stats.f90", "src\rng.f90",
    "src\distrib.f90", "src\montecarlo.f90", "app\profitsim.f90"
) | ForEach-Object { Join-Path $d $_ }
& gfortran @flags @sim "$d\build\compat.o" -o "$d\bin\profit-sim.exe"
if ($LASTEXITCODE -ne 0) { throw "profit-sim build failed ($LASTEXITCODE)" }
Write-Host "built $d\bin\profit-sim.exe"

# scenario-sim: Scenario Simulation engine
$scn = @(
    "src\json.f90", "src\sort_stats.f90", "src\rng.f90",
    "src\distrib.f90", "src\scenario.f90", "app\scenariosim.f90"
) | ForEach-Object { Join-Path $d $_ }
& gfortran @flags @scn "$d\build\compat.o" -o "$d\bin\scenario-sim.exe"
if ($LASTEXITCODE -ne 0) { throw "scenario-sim build failed ($LASTEXITCODE)" }
Write-Host "built $d\bin\scenario-sim.exe"

# portfolio-opt: Markowitz mean-variance optimiser (reuses json only)
$port = @(
    "src\json.f90", "src\portfolio.f90", "app\portfolioopt.f90"
) | ForEach-Object { Join-Path $d $_ }
& gfortran @flags @port "$d\build\compat.o" -o "$d\bin\portfolio-opt.exe"
if ($LASTEXITCODE -ne 0) { throw "portfolio-opt build failed ($LASTEXITCODE)" }
Write-Host "built $d\bin\portfolio-opt.exe"
