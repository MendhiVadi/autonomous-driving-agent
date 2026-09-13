param([string]$CarlaRoot = "C:\CARLA\CARLA_0.9.16")
$ErrorActionPreference = "Stop"
if (!(Test-Path -LiteralPath $CarlaRoot)) { throw "Set -CarlaRoot to the Device 2 CARLA folder." }
$python = Join-Path $CarlaRoot "carla_env\Scripts\python.exe"
if (!(Test-Path -LiteralPath $python)) { throw "CARLA Python environment not found: $python" }
& $python -m pip install -r (Join-Path $PSScriptRoot "device2_requirements.txt")
& $python -c "import carla, numpy, torch, cv2, PIL; print('Device 2 imports: OK'); print('torch='+torch.__version__)"
