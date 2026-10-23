# Maps and recovered download

## October 1, 2026 check

`run_large_map.cmd -MaxRuntimeSeconds 15` loaded Town13, completed nearby tile
warm-up, kept Epic rendering and wind 65, and exited cleanly. Its stationary
native viewport reported about 27.6 to 29.2 FPS. The test did not drive across
Town13 or prove that later tile transitions are stall-free. CARLA large maps
stream nearby tiles; loading every distant tile at once is not required for
full scenery and would increase memory pressure on this PC. Evidence:
`logs/20261001-120947-driving.log`.

## Repair update — 2026-09-24

Town13 passed a brake-held eight-second live test on the isolated, official
CARLA Python 3.12 client. The log confirms `Carla/Maps/Town13/Town13`, successful
tile warm-up, approximately 23.7 FPS while stationary, Epic scenery and wind 65,
followed by a clean launcher exit. Evidence: `logs/20260924-010114-driving.log`.
This is startup/stationary evidence, not a full-map driving or traffic benchmark.

**Remaining limitation:** subsequent encrypted-gateway tests were not reliable.
Seed 7 reached hero tile warm-up but exceeded the 60-second initial tick
(`logs/20260924-010808-driving.log`). A fixed-spawn retry then exceeded the
90-second map load before spawning (`logs/20260924-011512-driving.log`).
The launcher exited with failure and cleaned up its owned simulator processes;
neither run trained a model. Root cause of the remaining intermittent stalls
is not established. Town13 is not the first-connection baseline: use Town02_Opt.

All 339 Town13 files in the retained AdditionalMaps ZIP matched installed sizes
and CRCs. No map assets needed replacement. The preceding native crash was in
`libcarla.cp311-win_amd64.pyd` (Windows exception 0xc0000005); the external legacy
environment was left intact. The isolated bundled client also parsed the full
89 MB Town13 OpenDRIVE definition offline successfully.

The host now disables unused-spectator tile loading, streams a 650 m region
around its hero vehicle, uses a 350 m actor-active radius and warms tiles with
the brakes held before normal short-deadline driving begins. All scenery
layers and full rendering remain enabled; distant tiles load as the hero moves.
Large-map streaming is described in the
[CARLA large-map guide](https://carla.readthedocs.io/en/latest/large_map_overview/).
Map parsing is reused instead of repeated during tile warm-up, and map-transfer
files are cached inside this host's own folder. Native fault diagnostics are
enabled. No installed map/configuration file was overwritten or deleted.

Positional and temporary engine map overrides were ignored by this Windows
shipping build, so those ineffective launch arguments were removed. Map
selection remains through the CARLA API with the large-map streaming setup.

The earlier findings below are retained as history. The mixed current results
above supersede any older all-failed or all-ready interpretation.

Checked 2026-09-23 against the installed Windows CARLA 0.9.16 tree.

## Large map already installed

Town12 and Town13 assets are present. Town13 contains 49 `.umap` files and 339
files total (844,394,387 bytes inside its own map directory; shared assets are
additional). Its root world is `Town13/Town13.umap`. CARLA describes Town13 as
a 10 by 10 kilometre Large Map in the
[official release announcement](https://carla.org/2023/11/10/release-0.9.15/).

`run_large_map.cmd` selects Town13 with the existing full-graphics manual
profile. The default small-map launch remains unchanged; a large map can be
much more demanding on memory and the integrated GPU.

Live check: Town13 appeared in CARLA's available-map list, but its map-load
request timed out after 90 seconds on this laptop with the Epic profile.
The managed launcher shut down its owned simulator processes. Thus Town13 is
installed but **not yet verified usable**. The cause is not established; do
not interpret asset presence as a successful full-graphics large-map run.
The `run_large_map.cmd` launcher is an explicit test option, not a changed default.

## Download recovered, not installed

An existing Windows BITS job named `CARLA Tartu city map 0.9.16` had already
transferred all bytes but had not finalized its destination. It was completed
without restarting the download or overwriting an existing file:

- File: `C:/Users/medha/Documents/CARLA/downloads/tartu_demo_v0.9.16.tar.gz`
- Size: 1,577,425,960 bytes
- SHA-256: `628051e77e3ff2d7c5538716240aa15a14dd76f1fee609b6b8a1b188cc7306ab`
- Source: [University of Tartu map release](https://github.com/UT-ADL/carla_tartu_demo/releases/tag/v0.9.16)

The hash is a local integrity identifier, not a verified publisher checksum.
The publisher's [installation instructions](https://github.com/UT-ADL/carla_tartu_demo)
describe Linux import/start scripts; Windows cooked-asset compatibility has not
been established. The archive also contains shared weather/assets. Do not
extract it over the working installation without a compatibility check and an
explicit overwrite plan. No map package was installed or deleted in this pass.
The older download-status text has been updated to reflect finalization.

No duplicate large download is necessary for Town13. Existing CARLA and
AdditionalMaps archives are retained unchanged.
