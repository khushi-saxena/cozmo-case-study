# Device matrix

## Which tier runs on which hardware

| device | LiDAR tier | video tier | photo tier |
|---|---|---|---|
| iPhone 15, 16, 17 (non-Pro) | not available - no LiDAR | yes | yes |
| iPhone 15, 16, 17 Pro / Pro Max | yes | yes | yes |
| iPad Pro with LiDAR | yes | yes | yes |

The app checks `ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)`
at session start and records the result in the manifest, so a capture always
says whether depth was available.

## What each tier honestly delivers

Measured on `capture_1788930419` (bedroom + walk-in closet + attached
washroom, iPhone 17 Pro), with the LiDAR tier as reference.

| tier | ceiling height | vs LiDAR | floor area | vs LiDAR | rooms | runtime |
|---|---|---|---|---|---|---|
| LiDAR | 2.430 m | - | 15.48 m2 | - | 2 | 7.5 s |
| video | 2.040 m | -16.0% | 13.84 m2 | -10.6% | 2 | 27.5 s |
| photo | 2.247 m | -7.5% | 10.99 m2 | -29.0% | 1 | 20.2 s |

External check on the LiDAR tier: magicplan 2026.35.0 on the same room reports
ceiling 2.413 m (1.7 cm from mine) and floor area 15.36 m2 (0.8% from mine).

## Repeatability

Two separate captures of the same bedroom, LiDAR tier: ceiling height 2.430 m
both times, spread 0.00 cm. Across eight stride and voxel settings on one
capture: 2.430 m every time, 1 cm total spread.

## What to expect per tier

**LiDAR.** Ceiling heights repeatable to the millimetre and within 2 cm of a
commercial product. Floor areas within 1% of that product. Openings unreliable
(see failure modes).

**Video.** Floor plan shape and room count come out right; areas run about 10%
low. Ceiling heights are 16% low and their intervals are too narrow - the
weakest calibration of the three tiers. Slowest tier because monocular depth
runs on every keyframe.

**Photo.** Areas are lower bounds, roughly 30% low, reported with intervals
skewed upward. Ceiling height is the best of the two non-LiDAR tiers at -7.5%,
with a 20 cm interval that reflects how little a single still can know. Does
not split rooms - each still folder becomes one room.

## Not covered

No non-Pro device was available to test on, so the video and photo rows above
were produced on a Pro device with depth deliberately ignored. That is a fair
simulation of the data those tiers get, but it is not the same as running on
the hardware, and the difference is untested.
