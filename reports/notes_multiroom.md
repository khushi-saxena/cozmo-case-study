# Multi-room capture, drift and segmentation

Capture 1788930419: bedroom, walk-in closet, attached washroom, one recording,
408 frames, all tracking normal, 49 stills, depth confidence 1.60/2.
Path 19.6 m, returned to within 0.66 m of start.

## Ceiling height

2.430 m. Same answer as the two earlier bedroom captures, to the millimetre,
and the same with drift correction on or off. Interval from plane scatter:
[2.387, 2.473].

## Segmentation

Eroding the floor footprint alone never splits it. A walk-in closet has no
door, just a wide opening, and the room disappears before any neck does.
Cutting the wall cells out of the floor grid first is what separates spaces:
walls are the thing that separates rooms.

Result: 2 rooms. Bedroom plus closet as one 11.9 m2 space, washroom 3.0 m2,
adjacent through the doorway. The closet merges into the bedroom because there
is no wall between them, which is how most floor plans draw a walk-in anyway.

## Drift

Method: linear loop closure. The walker returns to the start; the gap between
first and last pose is accumulated drift, spread back along the path by
cumulative distance. Translation only, horizontal plane. Vertical is
gravity-anchored by ARKit so it is not corrected. Yaw closure is skipped when
start/end heading differ by more than 8 degrees, because that is the walker
facing a different way, not drift; here it was 47 degrees, so skipped.

Ablation on this capture:

    drift correction   total area   rooms   openings
    off (as-is)        13.55 m2     2       3
    on                 14.87 m2     2       4

Moved the footprint by about 10%, did not change room count or ceiling
height. Weak correction. A pose graph with visual loop closures would do
more; this one is deterministic, has no tunables and runs in milliseconds,
which the live walk-in test rewards.

## Openings

Runs, but classification is wrong: every opening comes out as "window" and one
is 2.35 m wide, a phantom. A closed door reads as wall because the leaf sits
inside the wall slab; the protocol now requires interior doors open. Furniture
against a wall reads as an opening from the wall's point of view. Separating
occlusion from opening needs the RGB frames, not geometry.

This is the fix-loop candidate.
