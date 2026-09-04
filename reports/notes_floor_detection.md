# Floor and ceiling detection

Ground truth for room_01, tape: ceiling height 236 cm, door width 76 cm,
door height 197 cm.

## First capture (capture_1788461277)

Walked at chest height pointing at walls. 534 frames, 40 seconds.

Ceiling plane was clean (y=+1.638, 354 points in a 1 cm bin, 11.65 m2).
Floor was not resolvable: candidate horizontal surfaces every 10-14 cm from
-1.00 to -0.28, all with comparable support and comparable area, so neither
"lowest", "strongest" nor "largest area" picked the right one.

Ceiling height came out 248.7 cm at stride 4, but the answer moved between
239 and 270 cm depending on frame stride. Vertical smear about +/-10 cm
against a 1.5 cm gate.

Causes:
- floor only ever seen at a grazing angle, never viewed directly
- depth confidence was low on essentially every pixel (mean 0.03 of 2)
- 32 m of walk pooled into one cloud, so pose drift is baked into every plane

## Second capture (capture_1788475750)

Same room, deliberate floor and ceiling sweeps along each wall, slower walk.
302 frames.

Depth confidence: mean 1.70 of 2. The low confidence in the first capture was
motion, not a bug. Slowing the walk fixed it with no app change.

Cloud is much tighter: 231k voxels from 75 frames against 1.0M from 133 frames
in the first capture, so points from different frames now coincide instead of
smearing.

Three horizontal planes detected instead of seven:

    floor    y=-0.826  support 2531  area 11.56 m2
    ceiling  y=+1.604  support 1931  area 11.00 m2
    table    y=-0.286  support  382  area  4.59 m2

Floor support up 17x.

Ceiling height 2.430 m against 2.36 m tape, so +7.0 cm.
Repeatable to 1 cm across 8 stride and voxel settings (first capture: 31 cm).

Plane thickness is 1.6 cm on the floor and 1.9 cm on the ceiling. That is the
sensor noise floor and it sits right at the 1.5 cm gate, so a trimmed mean over
a height band is not going to be good enough.

## Where this leaves the gate

Repeatable-but-biased, not unrepeatable. The case study asks which one you
have, and this is the fixable half.

Bias candidates, in order of suspicion:

1. The refinement takes a trimmed mean of points within a 4 cm window. If the
   point distribution around a plane is asymmetric, and it will be since depth
   error grows with distance and grazing angle, that estimator is biased. A
   least-squares plane fit and its offset should remove it.
2. ARKit depth has a positive bias at grazing angles. The floor is still seen
   shallowly even with sweeps.
3. Ground truth. 236 cm is an unusual ceiling height. Needs a re-measure at
   two more spots on different walls.

Carpet or a rug would put the LiDAR floor above the structural floor, but that
lowers the measured height, so it cannot explain a positive bias.
