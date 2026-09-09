# Fix loop: before, after, and what I got wrong

## The numbers

Capture `capture_1788930419`, LiDAR tier, same command both runs.

    run                  openings   real found   phantoms
    before                   5        0 of 3        5
    after                    1        0 of 3        1
    predicted in advance     ~1        2 of 3       <=1

Everything else held steady: 2 rooms, 15.48 m2, ceiling 2.430 m both runs.
Runtime went 18.3s -> 13.7s, because the bounded slabs are less work.

Reproduce:

    python3 scripts/run.py --capture benchmark/captures/capture_1788930419 --tier lidar

before/ and after/ bundles are in `benchmark/runs/fix_loop/`.

## What I predicted, and what actually happened

I got the phantom half right. 5 down to 1, which is what I said.

I got the detection half wrong. I predicted 2 of 3 real openings would start
being found, and it is still 0 of 3.

And my root cause was only part of the story. I said the problem was
occlusion - furniture in front of a wall reading as a hole. That is real and
the occlusion test does reject things, but it is not what was doing most of
the damage.

## What the fix loop actually turned up

When I instrumented the detector to print the occlusion and free-space
fractions per candidate, `beyond_fraction` came back as 1.00 on every single
candidate. Every one had points behind it, so the free-space test was passing
everything and rejecting nothing.

The reason is a bug one level up from where I was looking. My walls come from
the floor-footprint polygon, and that polygon has 13 corners because the 8cm
raster leaves a staircase along every wall. So each "wall" is a 1 to 2 metre
fragment. `wall_slab` was then collecting points from that fragment's
*infinite* plane, which runs straight through the rest of the room. "Beyond
the wall" was full of the room itself, and the wall occupancy grid was full of
surfaces metres away.

So the detector was not measuring walls. It was measuring plane slices through
the whole room, and then hunting for gaps in those.

The fix that actually moved the number was bounding each slab to its own
segment along the wall, with a 10cm pad. That is what took phantoms from 5
to 1.

## Why real openings are still not detected

Same root cause, other half of it. A 76cm door does not appear as one clean
gap in any single 1-2m staircase fragment - it gets split across two or three
fragments, and each piece is too small or too ragged to survive the size and
fill filters.

Detecting openings properly needs the walls to be actual walls: merge the
staircase fragments into a handful of real wall planes first, then look for
gaps on those. I tried RANSAC wall extraction earlier (it is still in
`pipeline/geometry/walls.py`) and it kept finding the same wall three or four
times because removing inliers at a 3cm threshold leaves the plane's own noise
behind for the next round. I did not get that solved, so the polygon-edge
route is what shipped.

That is the known failure mode, and it is the first thing I would do next.

## The honest summary

Right about occlusion mattering, wrong about it being the main cause. Half the
prediction landed, half did not. The fix is real and shipped and the phantom
count moved 5x, but the detection rate is unchanged at 0%, against an 85%
gate.

What I would claim from this: the instrumentation was worth more than my
hypothesis. Printing the per-candidate fractions is what exposed the
unbounded-plane bug, and I would not have found it by reasoning about it.
