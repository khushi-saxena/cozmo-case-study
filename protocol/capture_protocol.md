# Capture protocol - one page

Anyone can follow this. No engineering knowledge needed.

## Install the app (one time, needs a Mac)

    git clone <repo>
    open ios/CozmoCapture/CozmoCapture.xcodeproj

In Xcode: Signing & Capabilities → Team → your Apple ID (a free one works).
Change the Bundle Identifier to something unique. Plug in the iPhone, select
it as the run target, press Cmd-R.

First launch will refuse: on the phone go to Settings → General → VPN &
Device Management → Developer App → tap your Apple ID → Trust. Press Cmd-R
again. Under 10 minutes on a Mac that already has Xcode.

## Before you record

**Open every interior door.** This matters more than anything else on this
page. A closed door reads as solid wall to the laser and will not be found.

Pull furniture away from walls if it moves easily. Furniture against a wall
looks like a hole in the wall.

Turn the lights on.

Open the app and wait until the line at the bottom says `tracking: normal`.
Do not start while it says `limited_initializing`.

## Recording

1. Type a room name in the text field.
2. Stand in the doorway of the first room. Tap **Record**.
3. Walk the edge of the room, phone held at chest height, screen facing you,
   camera pointing at the wall ahead.
4. **Go slowly. About one step per second.** Fast movement halves the depth
   quality - measured, not guessed.
5. Along each wall, tilt the phone down to catch where the wall meets the
   floor, then up to catch where it meets the ceiling. Both edges are needed.
6. Turn corners by pivoting slowly. Do not swing the phone.
7. Come back to the exact spot you started. This closes the loop and is what
   the drift correction uses.
8. For more rooms: walk through the doorway slowly, phone pointing forward
   through the opening, then repeat steps 3-7. Do not stop recording between
   rooms.
9. Before stopping, stand still in each room and tap **Shutter** 4 times from
   4 different positions, covering the whole room between them. These become
   the photo tier.
10. Tap **Stop**, then **Export**, then AirDrop the zip to a Mac.

Roughly 60-90 seconds of walking per room.

## Watch for

`tracking: limited_excessive_motion` - you are moving too fast, slow down.

`dropped:` climbing past about 20 - the phone cannot keep up writing; slow
down or free up storage.

## What you get

One zip per capture, containing RGB frames, depth maps and confidence maps
(Pro devices), per-frame camera poses and intrinsics, the stills in per-room
folders, and a manifest describing the device and formats.

## Running the pipeline

    python3 scripts/run.py --capture <unzipped folder> --tier lidar

Also `--tier video` and `--tier photo` on the same capture. Outputs
`output.json` and `plan.svg`.
