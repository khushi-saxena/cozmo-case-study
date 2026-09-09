# Fix declaration

Written and committed before I made the fix.

## 1. Worst gate, and the number

Openings. The gate wants widths within 2cm on 85% of openings, and it scores
detection too - miss one or invent one and both count against you.

Capture `capture_1788930419` is my bedroom, walk-in closet and attached
washroom. It has three openings: the bedroom door (76cm wide, 197cm tall,
measured with tape), the closet entry (no door leaf, just an opening), and the
washroom door.

My pipeline found five openings and got none of them right. All five came out
labelled "window". Not one door, even though the bedroom door is 76cm and
reaches the floor. The widths ran 0.55m to 2.35m, so my widest detection is
three times wider than anything actually in the room.

So: 0 of 3 found, 5 invented. 0% against an 85% gate.

Video tier is worse, 7 openings.

Everything else in the benchmark is in much better shape - ceiling height is
1.7cm off magicplan on this room and repeats to 1cm across eight different
parameter settings. Openings are the outlier by a long way.

One thing worth saying: magicplan found 0 doors and 0 windows on this same
room (screenshot in `benchmark/incumbent/`). So the incumbent fails this row
too, just by giving up instead of guessing. Doesn't get me off the hook, but
it does tell me the row is hard.

## 2. Why I think it's broken

My detector finds gaps in the wall and calls them openings. But a gap only
means "no laser came back from the wall here", and there are three ways that
happens:

- there's a real hole in the wall (the one I want)
- something solid is parked in front of the wall, so the laser hit that instead
- I never pointed the phone at that bit of wall from a useful angle

The code can't tell these apart. It treats all three as openings.

What makes me think furniture is the main culprit:

The one detection still surviving after I tightened the thresholds is 0.55m
wide, 0.70m tall, sitting 0.25m off the floor, on the wall with the bedroom
door. That is a nightstand or a chair back. A window with a 25cm sill would be
strange; furniture at that height is not.

The 2.35m one is wider than any opening in the room and matches the run of
furniture along one wall.

An earlier phantom was 1.65m wide, 0.35m tall, 2.05m up - that was wall I
never looked at, near the ceiling. The ceiling-margin filter killed it, which
fits.

And the detection count on one wall went 2 -> 1 just from changing thresholds,
without the underlying data changing at all. Something that actually works
doesn't wobble like that.

There's a second, separate problem: the bedroom door was shut when I captured.
A closed door sits a few cm behind its frame, which is inside my 10cm wall
slab, so it reads as solid wall. The opening I should have been most sure
about was invisible. I found this on Sep 8 and the capture protocol now says
open all interior doors first, but this capture came before that.

## 3. What I'm fixing, and the number I expect after

Fix: don't call an empty wall region an opening unless the camera frames back
it up, and throw out regions that something closer explains.

Two parts:

- Occlusion check. Take each candidate gap, project it back into the frames
  that saw that patch of wall, and look for points sitting in front of the
  wall plane along those rays. If most of the views that saw it were blocked
  by something nearer, it's furniture. This goes straight at the root cause -
  it's the difference between "nothing there" and "something in the way".
- Free space check. A real doorway has floor running through it and space on
  the far side. If a candidate reaches the floor and has points beyond it at
  greater depth, it's a door or a pass-through. If there's nothing beyond it,
  it isn't an opening. This should fix the labelling too, since floor-reaching
  plus space beyond is basically what a door is.

What I expect after, same capture, LiDAR tier:

- phantoms: 5 -> 1 or fewer
- real openings found: 0 -> 2 of 3 (closet and washroom; the bedroom door
  stays invisible because it was shut)
- detection rate: 0% -> 67%

67% still fails the 85% gate and I'm saying that up front rather than
predicting a pass I don't believe in. I can't get to 85% on this capture while
one of the three openings physically can't be seen. What I can do is stop the
pipeline inventing openings that aren't there, which is the part that's my
code's fault rather than the capture's.

Widths won't get to 2cm either. My wall raster is 5cm, so 2cm is finer than
the method can resolve. That needs sub-cell edge fitting against the raw
depth, which is a bigger job than this fix loop - it's in the known failure
modes instead.
