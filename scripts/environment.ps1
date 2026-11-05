# Shared helpers for the launchers. Dot-source this file; do not run it directly.
param([switch]$PrintCarlaRoot)
$script:ProjectRoot = Split-Path -Parent $PSScriptRoot

function Get-ProjectSettings {
    Get-Content -LiteralPath (Join-Path $script:ProjectRoot 'config\runtime.json') -Raw | ConvertFrom-Json
}

function Resolve-CarlaRoot([string]$ExplicitRoot = '') {
    # Precedence: explicit -CarlaRoot, then the CARLA_ROOT variable, then config\runtime.json.
    if ($ExplicitRoot) { return [IO.Path]::GetFullPath($ExplicitRoot) }
    if ($env:CARLA_ROOT) { return [IO.Path]::GetFullPath($env:CARLA_ROOT) }
    return [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables((Get-ProjectSettings).carla_root))
}

function Get-CarlaPython([string]$CarlaRoot) {
    # The project's own Python environment lives inside the CARLA installation.
    Join-Path $CarlaRoot 'carla_env\Scripts\python.exe'
}

function Get-DefaultPolicyPath {
    # Use the same resolved-path containment check as Python, including links.
    $pythonExe = Get-CarlaPython (Resolve-CarlaRoot)
    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
        throw "CARLA Python environment is missing: $pythonExe"
    }
    $result = & $pythonExe -I -B -c "import sys; sys.path.insert(0,sys.argv[1]); from runtime.paths import default_policy_path; print(default_policy_path())" (Join-Path $script:ProjectRoot 'app')
    if ($LASTEXITCODE -ne 0 -or -not $result) { throw 'Invalid local model configuration (config\runtime.json legacy_policy_candidates).' }
    return $result
}

if ($PrintCarlaRoot) { Resolve-CarlaRoot }
