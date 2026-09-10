# Cozmo case study

Takes a handheld iPhone capture of a property and produces a dimensioned
floor plan: per-room polygons with wall lengths and ceiling heights, rooms
stitched with adjacency, openings, and a confidence interval on every
measurement. Photo, video and LiDAR inputs all run through the same pipeline.

## Run it

Needs Python 3.11+ and a Mac or Linux box. About 5 minutes from clone to a
plan, most of it downloading model weights the first time.

    git clone https://github.com/khushi-saxena/cozmo-case-study && cd cozmo-case-study
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    bash scripts/fetch_weights.sh

    python3 scripts/run.py --capture benchmark/captures/capture_1788930419 --tier lidar

Outputs `output.json` and `plan.svg` under `benchmark/runs/`.

Same capture, other tiers:

    python3 scripts/run.py --capture benchmark/captures/capture_1788930419 --tier video
    python3 scripts/run.py --capture benchmark/captures/capture_1788930419 --tier photo

Drift ablation:

    python3 scripts/run.py --capture benchmark/captures/capture_1788930419 --tier lidar --no-drift-correction

Score everything against the gates:

    python3 benchmark/harness/gates.py

## Capture app

`ios/CozmoCapture/`. Records RGB frames, LiDAR depth and confidence, per-frame
poses and intrinsics, plus separate stills that deliberately carry no pose or
depth.

Install: open the xcodeproj in Xcode, set Signing → Team to any free Apple ID,
change the bundle identifier, plug in an iPhone, Cmd-R. First launch needs
Settings → General → VPN & Device Management → trust the developer. Under 10
minutes on a Mac with Xcode already installed.

No TestFlight, so this assumes a Mac with Xcode. Stated up front rather than
discovered later. Full walkthrough in `protocol/capture_protocol.md`.

## Layout

    ios/CozmoCapture/     capture app (Swift, ARKit)
    pipeline/ingest/      per-tier front ends: lidar, video, photo, monodepth
    pipeline/geometry/    planes, outline, rooms, openings, drift, walls
    pipeline/render/      SVG plan
    pipeline/schema/      published output contract
    benchmark/captures/   raw captures (fetched separately, see below)
    benchmark/ground_truth/  tape measurements
    benchmark/incumbent/  magicplan comparison, screenshots
    benchmark/harness/    gate scoring
    benchmark/runs/       pipeline outputs, including the fix loop before/after
    protocol/             capture protocol, device matrix
    reports/              technical report, fix declaration, fix loop post-mortem
    COMPLIANCE.csv        requirement → file → artifact → status

## Raw captures

Captures are 200-400 MB each and are not in git. Fetch them:

    bash scripts/fetch_captures.sh


Download: https://drive.google.com/file/d/16VfuW4t1hZvr9IrdqhAt4pZuEEVgnZdO/view

If the script trips over Google Drive's virus-scan page, grab the zip from that
link by hand and `unzip -o cozmo-captures.zip -d benchmark/`.

| folder | what it is |
|---|---|
| `capture_1788930419` | bedroom, walk-in closet, attached washroom - the multi-space capture |
| `capture_1789080432` | a study in another building - the walk-in dry run, unseen room |
| `capture_1788475750` | bedroom, second capture, for the repeatability gate |
| `capture_1788461277` | bedroom, first capture, before floor sweeps were in the protocol |
| `capture_1788482793` | open-plan living space |

Everything in `benchmark/runs/` regenerates from them with the commands above.

## Results in one table

Capture `capture_1788930419`: bedroom, walk-in closet, attached washroom.

| tier | rooms | floor area | ceiling height | openings | runtime |
|---|---|---|---|---|---|
| LiDAR | 2 | 15.48 m2 | 2.430 m | 1 | 17.9 s |
| video | 2 | 13.84 m2 | 2.040 m | 0 | 29.1 s |
| photo | 1 | 10.99 m2 | 2.247 m | 0 | 20.3 s |

magicplan 2026.35.0 on the same room: ceiling 2.413 m, floor area 15.36 m2.
So 1.7 cm and 0.8% apart on the two shared dimensions.

Repeatability, two separate captures of the same room: 2.430 m both times.

A clean clone reproduces all three tiers to the same figures: fresh checkout,
fresh venv, weights fetched by script, 18.6 s wall clock to a LiDAR plan.

Openings are the weak row and the subject of the fix loop. Details and every
other known failure mode are in `reports/technical_report.md` section 8.

## Disclosure

One pretrained model: `depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf`,
fetched once by script. Nothing calls external infrastructure at inference
time.
