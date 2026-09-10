# Cozmo case study - technical report

Khushi Saxena, September 2026. iPhone 17 Pro, MacBook Pro (Apple silicon).

---

## 1. Architecture

One pipeline, three front ends. Every tier produces the same intermediate - a
metric point cloud plus whatever camera information that tier has - and then a
single downstream stack runs on it. That was the first decision I made and the
one I would defend hardest: it is the only reason the same output contract
holds at all three tiers instead of me writing three separate systems that
happen to emit the same JSON keys.

    LiDAR   ARKit depth + poses + intrinsics  ┐
    Video   frames + ARKit poses, mono depth  ├─→  metric point cloud
    Photo   stills only, mono depth           ┘         │
                                                        ▼
                                       gravity-aligned, normals per point
                                       → horizontal planes → floor, ceiling
                                       → rectify to wall heading
                                       → floor footprint raster
                                       → contour trace → room polygon
                                       → walls cut from floor → room split
                                       → adjacency
                                       → openings per wall segment
                                       → intervals on every number
                                       → JSON + SVG plan

One command per capture:

    python3 scripts/run.py --capture <dir> --tier <lidar|video|photo>

Runtime on the target laptop, measured on the multi-space capture: LiDAR
17.9 s, photo 20.3 s, video 29.1 s. LiDAR was 7.5 s before damage detection
was added; painting each wall from the RGB frames is what costs the rest. Nothing
calls out to a network at inference time. Model weights are fetched once by
script into the local cache.

### Capture app

I built the iOS capture app rather than writing a protocol around a stock one
(Route 1). The reason was not the 5% row - it was that owning the sensor path
means the video tier gets ARKit's metric VIO poses, so I never have to solve
scale from motion on two of the three tiers.

The app records at 6 fps, not ARKit's 60. Sixty near-identical views add no
information and the write path cannot keep up. When the IO queue is busy the
app drops the frame and counts it rather than queueing, because an unbounded
backlog corrupts timing and memory. Dropped counts go in the manifest.

Every pose line carries ARKit's tracking state. Frames captured under degraded
tracking are excluded from the cloud, and the count of rejected frames is
reported.

Distribution is the Xcode project, not TestFlight. A free Apple ID signs a dev
build, so the reviewer clones, opens, plugs in a phone and runs. This assumes
they have a Mac with Xcode; that assumption is stated in the README rather
than discovered at the defense.

## 2. Tier design and device matrix

| tier | inputs used | depth from | scale from |
|---|---|---|---|
| LiDAR | frames, depth, confidence, poses, intrinsics | ARKit sceneDepth | sensor, metric |
| Video | frames, poses, intrinsics | Depth Anything V2 Metric Indoor Small | model, cross-checked against VIO motion |
| Photo | stills only | same model | model alone |

| device | LiDAR | video | photo |
|---|---|---|---|
| iPhone 15 / 16 / 17 (non-Pro) | not available | yes | yes |
| iPhone 15 / 16 / 17 Pro | yes | yes | yes |

Photo tier is honestly poseless. The app strips poses, depth and intrinsics
from the stills export by design, so the photo path cannot cheat by reading
data the tier is not supposed to have. Focal length is the one exception: I
pass the iPhone's known focal (1365 px at 1920x1440) as calibration, and
disclose it. That is a device property, not a pose.

Accuracy each tier honestly delivers, measured on `capture_1788930419`
against the LiDAR tier as reference:

| tier | floor area | ceiling height | rooms found | runtime |
|---|---|---|---|---|
| LiDAR | 15.48 m2 | 2.430 m | 2 | 17.9 s |
| Video | 13.84 m2 (-10.6%) | 2.040 m (-16.0%) | 2 | 29.1 s |
| Photo | 10.99 m2 (-29.0%) | 2.247 m (-7.5%) | 1 | 20.3 s |

Photo-tier area is reported as a lower bound with an interval skewed upward,
because a still only ever sees part of a room.

### Depth model choice

I tried Apple Depth Pro first. On this laptop it took 50 s to load, 47-77 s
per image at half precision, and ran out of GPU memory at full precision (MPS
caps allocations at 9 GB). Its focal estimate was also 18% high - it guessed
1608 px where ARKit reports 1365.

Depth Anything V2 Metric Indoor Small loads in seconds and runs at 0.13 s per
image. That is the difference between a photo tier that runs in front of you
and one that does not. Accuracy is lower at the margins; the intervals say so.

## 3. Drift handling

Poses are not used as-is.

The walker returns to where they started, but ARKit's poses say they did not.
That gap is accumulated drift. I spread it back along the path in proportion
to cumulative distance walked, so the first and last poses coincide.

Two constraints from the data:

- Translation only in the horizontal plane. ARKit anchors vertical to gravity,
  so a vertical start/end gap is real height difference, not drift. Correcting
  it made things worse.
- Yaw closure is applied only when start and end headings differ by under 8
  degrees. On `capture_1788930419` they differed by 47 degrees, which is the
  walker facing a different way at the end, not drift. Applying it would have
  rotated the whole cloud.

Ablation, same capture, one flag (`--no-drift-correction`):

| drift correction | total area | rooms | openings |
|---|---|---|---|
| off | 13.55 m2 | 2 | 3 |
| on | 14.87 m2 | 2 | 4 |

Closure was 0.66 m of translation over a 19.6 m path. The correction moves the
footprint by about 10% and does not change the room count or the ceiling
height. It is a weak correction and I would not claim otherwise. A pose graph
with visual loop closures would do more; this one is deterministic, has no
tunable parameters and runs in milliseconds, which the live test rewards.

## 4. Error budget

Where the error in a LiDAR ceiling-height measurement comes from:

| source | magnitude |
|---|---|
| plane fit residual, floor | 1.6 cm sd |
| plane fit residual, ceiling | 1.9 cm sd |
| plane tilt (floor and ceiling both ~0.5 deg) | up to 2 cm across a 4 m room |
| floor raster cell (8 cm) on areas | ~4% on a 12 m2 room |
| carpet: LiDAR sees pile top, tape hook compresses it | ~1 cm, one direction |
| my own tape measurement | 4 cm spread between two passes |

The last row is the binding constraint and it is worth being blunt about: my
ground truth is not good enough to judge a 1.5 cm gate. Two tape passes on the
same ceiling gave 236 cm and 240 cm. A steel tape held vertically bows, which
traces a longer path than the true vertical and reads long by a variable
amount.

Independent evidence that the pipeline is not the problem: magicplan, on the
same room, using the same LiDAR sensor, reports 241.3 cm. My pipeline reports
243.0 cm. Two independent LiDAR systems agree within 1.7 cm and both sit above
both of my tape readings.

So the honest statement is: the ceiling-height gate cannot be resolved with
the instrument I have. The pipeline is repeatable to 0.0 cm and agrees with a
commercial product to 1.7 cm. Whether it is within 1.5 cm of truth is not
something my tape can answer.

## 5. Calibration analysis

Every measurement in the contract carries an interval and the method that
produced it. Intervals are propagated from plane-fit residuals, point support
and a per-tier prior, and they widen as the input thins - which is the
behaviour the case study asks for.

Coverage against what truth I have:

| tier | ceiling height | 90% interval | contains magicplan 241.3 |
|---|---|---|---|
| LiDAR | 243.0 cm | [238.7, 247.3] | yes |
| Photo | 224.7 cm | [204.7, 244.7] | yes |
| Video | 204.0 cm | [198.7, 209.3] | no |

Two of three tiers cover it. The video tier does not, and that is a real
calibration failure: the video interval is 5 cm wide when the error is 37 cm.
The interval is too narrow because it is derived from plane-fit scatter, and a
monocular cloud can be tightly scattered around a plane that is in the wrong
place. Scatter measures precision, not accuracy, and for the video tier I
conflated them.

The photo tier is calibrated the other way and deliberately so: a 20 cm
half-interval on a number derived from single-image depth, and floor areas
reported as lower bounds with upward-skewed intervals. Wide and honest beats
narrow and wrong when the gate scores calibration.

Repeatability, two separate captures of the same bedroom, same tier:

| | capture 1788475750 | capture 1788930419 | spread | gate |
|---|---|---|---|---|
| ceiling height | 243.0 cm | 243.0 cm | 0.00 cm | 1 cm: pass |

Stability across parameters, same capture, eight stride and voxel settings:
2.430 m every time, 1 cm total spread. An earlier version of the floor
detector swung 31 cm across the same settings; the fix was requiring
horizontal planes to be selected by footprint area rather than histogram peak.

## 6. Head to head

magicplan 2026.35.0, Manual-Scan LiDAR mode, same bedroom, free tier.
Screenshots and transcribed values in `benchmark/incumbent/`.

| dimension | mine | magicplan | difference |
|---|---|---|---|
| ceiling height | 2.430 m | 2.413 m | 1.7 cm |
| floor area | 15.48 m2 | 15.36 m2 | 0.8% |
| doors detected | 1 (wrong) | 0 | - |
| windows detected | 0 | 0 | - |

Beat or tie on both shared dimensions available on the free tier.

Polycam was my first choice, named in the case study. Its free tier would not
process Floorplan mode on 2026-09-09 - the scan captured but processing was
gated behind a subscription. I used magicplan instead, which the case study
also names. Cost was not the reason; the free tier genuinely did not have the
feature.

Worth noting that magicplan detected zero doors and zero windows on this room.
The incumbent fails the openings row too, by declining to guess rather than by
hallucinating.

## 7. The fix loop

Full declaration in `reports/fix_declaration.md`, committed before the fix.
Before/after runs in `benchmark/runs/fix_loop/`, both regenerable.

**Worst gate:** openings. Three real openings in the room (bedroom door 76 cm
tape-measured, closet entry, washroom door). Pipeline found five and got none
right; all five labelled "window". 0% against an 85% gate.

**What I predicted:** occlusion was the root cause - furniture in front of a
wall reading as a hole. Predicted phantoms 5 -> 1 and real detections 0 -> 2.

**What happened:** phantoms went 5 -> 1 at the LiDAR tier, as predicted. Real
detections stayed at 0. So half the prediction landed and half did not.

The fix helped more than the declaration claimed, because it applies to every
tier rather than just the one I was measuring. Video went from 7 phantom
openings to 0 on the same capture. Across all three tiers the phantom count
went 12 -> 1.

**What the fix loop actually found**, and this is the part worth reading: when
I instrumented the detector to print occlusion and free-space fractions per
candidate, the free-space fraction came back as 1.00 on every candidate.
Everything had points behind it, so the test rejected nothing.

The cause was a bug one level up. My walls come from the floor-footprint
polygon, which has 13 corners because an 8 cm raster leaves a staircase along
every wall. Each "wall" is therefore a 1-2 m fragment - and I was collecting
points from that fragment's *infinite* plane, which runs straight through the
rest of the room. "Beyond the wall" was full of the room itself.

The detector was never measuring walls. It was measuring plane slices through
the whole room and hunting for gaps in them. Bounding each slab to its own
segment is what took phantoms from 5 to 1.

Real openings still are not detected for the other half of the same reason: a
76 cm door does not appear as one clean gap in any single staircase fragment.
It splits across two or three, and each piece fails the size and fill filters.

The instrumentation was worth more than my hypothesis. I would not have found
the unbounded-plane bug by reasoning about it.

## 7b. Walk-in dry run

Ran the pipeline cold on a room it had never seen - a furnished study in a
different building, captured 2026-09-10, all three tiers, no tuning.

| tier | ceiling height | vs magicplan 2.534 m | floor area | vs magicplan 10.21 m2 |
|---|---|---|---|---|
| LiDAR | 2.500 m | -3.4 cm | 3.19 m2 | -68.8% |
| photo | 2.926 m | +39.2 cm | 4.63 m2 | -54.6% |
| video | 2.030 m | -50.4 cm | 4.11 m2 | -59.7% |

Ceiling height generalises at the LiDAR tier. 3.4 cm on a room the code has
never seen, against 1.7 cm on my own bedroom, so the method is not fitted to
my apartment.

It does not generalise at the other two tiers. Photo is 39 cm high and video
50 cm low on the unseen room. Both are worse than on my own room, and the
photo tier's interval (+/- 20 cm) does not cover the reference either. Running
the harness against each room's own reference rather than against my bedroom's
LiDAR is what exposed this: comparing a tier to my own LiDAR flatters it,
because both share the same errors.

Floor area does not. Two things went wrong and the dry run is the only reason
I know about either.

First, only 4.8 m2 of floor was ever observed in a 10.2 m2 room. It is a
study: a desk, a chair and shelving cover most of the floor, and the LiDAR
cannot see through them. My own bedroom happened to have more open floor.

Second, the observed floor came back as two disconnected pieces and my
footprint code keeps only the largest blob, which threw away a fifth of what
had been seen. Widening the morphological closing from 0.24 m to 0.40 m fixes
that half and is now shipped: 2.71 m2 to 3.19 m2 on this capture.

Openings on this room: 2 detected, both wrong. One classified as a door
reaching the floor - the right shape for the first time - but 2.20 m wide
against a real 1.04 m. The other is a phantom window in a room magicplan says
has none. Consistent with the fix declaration.

The remaining gap is a method limit, not a bug: deriving room area from
observed floor will always underestimate a furnished room. The right fix is to
take the outline from the wall planes and use the floor only to confirm it,
which is the same merged-wall-plane work the openings row needs.

Capture quality was the best of any in the benchmark - 411 frames, tracking
normal throughout, depth confidence 1.78 of 2, loop closed to 0.26 m - so
this is not a bad capture. It is the method meeting a room that is not mine.

## 8. Known failure modes

**Openings, all tiers.** 0 of 3 real openings detected, and 1 phantom
remaining at the LiDAR tier (down from 12 phantoms across tiers before the
fix). The wall planes fed to
the detector are polygon-edge fragments, not merged wall planes. Fixing this
properly needs RANSAC wall extraction that does not re-detect the same wall -
my attempt is still in `pipeline/geometry/walls.py` and found each wall three
or four times, because removing inliers at a 3 cm threshold leaves the plane's
own noise behind for the next round. This is the first thing I would do next.

**Opening widths cannot reach 2 cm.** The wall raster is 5 cm. The gate is
finer than the method's resolution. Needs sub-cell edge fitting against raw
depth.

**Closed doors are invisible.** A closed door leaf sits a few cm behind its
frame, inside the 10 cm wall slab, so it reads as solid wall. The capture
protocol now requires interior doors be opened; the benchmark capture predates
that rule, which is why one of the three openings was unfindable.

**Video tier ceiling height, 16% low.** Monocular depth sees ceilings poorly.
A floor-relative prior (ceiling at least 2 m up) stops it picking a tabletop,
but does not make the estimate good. Its interval is also too narrow, as
section 5 says.

**Photo tier areas are lower bounds.** A still sees part of a room. I take the
best single still's extent rather than mixing spans from different stills,
which stops a 36 m2 answer on a 15 m2 room but leaves a systematic
underestimate.

**Damage detection is unvalidated.** I could not stage damage - I rent a room
in a shared apartment and cannot modify surfaces or capture other people's
rooms.

What is implemented: each wall is painted with the colours seen in the RGB
frames, and regions whose colour departs from that surface's own median by
more than 4 sigma over at least 0.15 m2 are flagged. Working per-surface is
what makes this work at all - a wall is mostly one colour, so "unlike the rest
of this wall" means something, where "unlike the rest of the room" would not.
Brightness delta then splits water staining from burns or holes.

Thresholds are deliberately hard. The loose version returned four regions of
0.05-0.12 m2 on my undamaged bedroom - posters, shadows, a dark curtain. On a
clean room the tightened version returns nothing, which is the right answer.
It will also miss faint staining, and since nothing here has been checked
against real damage, erring toward silence is the only setting I can defend.

The concealed-damage rules and the scope-item generator are deterministic and
self-tested: fed a 0.62 m2 ceiling stain they fire CD-001 and CD-004 and emit
five line items keyed to the surface. But the perception half has never seen
real damage, so treat every extent it produces as unverified.

Damage detection costs runtime: 7.5 s to 33 s on the multi-space capture,
because it reads and reprojects the RGB frames per wall.

**Mirrors, glass, wet-look surfaces, low light: untested.** The washroom in
the multi-space capture has a mirror and glass, and the pipeline segmented it
as a room without failing. That is the extent of the evidence. No controlled
test.

**Benchmark set is two spaces, not three.** Bedroom plus walk-in closet as one
space, attached washroom as the second. Same reason as the damage gap. The
multi-room stitch, adjacency and drift ablation all exercise a real connector,
but with fewer rooms than the case study specifies.

**Floor area underestimates furnished rooms.** Room outline comes from the
observed floor, so anything standing on the floor removes area. On the walk-in
dry run this was -58%. Deriving the outline from wall planes instead would fix
it and is the same work the openings row needs.

**Furniture against walls still causes trouble.** The one surviving phantom is
1.60 m wide with a 0.65 m sill, which is furniture. The occlusion test uses
point-in-front-of-plane geometry; using the RGB frames directly would separate
occlusion from opening far better.

## 9. Disclosure

Pretrained model: `depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf`,
weights fetched once by script to the local cache. No other pretrained models,
datasets or APIs. Nothing calls my infrastructure at any point. Camera focal
length (1365 px at 1920x1440) is passed as a device calibration constant and
is stated in every photo-tier output.
