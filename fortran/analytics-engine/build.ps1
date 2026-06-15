$ErrorActionPreference = "Stop"
if (Test-Path "C:\msys64\ucrt64\bin") { $env:Path = "C:\msys64\ucrt64\bin;" + $env:Path }

$d = $PSScriptRoot
New-Item -ItemType Directory -Force "$d\bin", "$d\build" | Out-Null

& gcc -O2 -c "$d\src\compat.c" -o "$d\build\compat.o"
if ($LASTEXITCODE -ne 0) { throw "compat.c build failed ($LASTEXITCODE)" }

$sources = @(
    "src\json.f90", "src\sort_stats.f90", "src\rng.f90",
    "src\indicators.f90", "src\risk.f90", "src\report.f90", "app\main.f90"
) | ForEach-Object { Join-Path $d $_ }

$flags = @("-O2", "-fwrapv", "-std=f2008", "-Wall", "-static",
           "-J", "$d\build", "-I", "$d\build")
& gfortran @flags @sources "$d\build\compat.o" -o "$d\bin\analytics-engine.exe"
if ($LASTEXITCODE -ne 0) { throw "build failed ($LASTEXITCODE)" }
Write-Host "built $d\bin\analytics-engine.exe"
