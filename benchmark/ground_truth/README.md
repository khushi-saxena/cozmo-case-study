# Ground truth

What was measured by hand, and what was not.

## room_01 (bedroom, `capture_1788930419` and `capture_1788475750`)

`room_01.csv`. Tape measure only - I had no laser measurer.

Ceiling height was measured twice, at different spots on different walls, and
the two passes disagree by 4 cm (236 and 240). A steel tape held vertically
bows, which traces a longer path than the true vertical and reads long by a
variable amount. 4 cm of measurement noise cannot resolve a 1.5 cm gate, so
the ceiling-height gate in the benchmark report is scored against magicplan
2026.35.0 rather than against this tape. Both numbers are recorded above
rather than one being quietly dropped.

No wall lengths were measured. That is a real gap in this deliverable: wall
length accuracy is only ever compared against magicplan, never against a
direct measurement.

## Study (`capture_1789080432`, the walk-in dry run)

No tape measurements. The room is in another building and I had no measuring
tape with me. Reference values come from magicplan on the same room, in
`../incumbent/magicplan_room_01.csv` and the study screenshots.

## Why magicplan is used as the reference

It measures the same rooms with the same LiDAR sensor, its internal numbers
are self-consistent (volume divided by floor area returns its stated ceiling
height to within 2 mm), and it is a shipping commercial product rather than
something I wrote. It is not truth. It is a second independent instrument, and
where my pipeline and magicplan agree to 1.7 cm on a ceiling that my own tape
put somewhere between 236 and 240, the tape is the thing that looks wrong.

Files:

    room_01.csv                  bedroom tape measurements
    ../incumbent/               magicplan values and screenshots, both rooms
