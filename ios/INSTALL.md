# Installing the capture app

Everything in the troubleshooting section below was hit for real while building
this, in roughly the order it happened. If something fails, it is probably
there.

## What you need

- A Mac with Xcode installed (Xcode 16 or newer)
- An iPhone 15 or newer. Pro models have LiDAR; non-Pro run the video and
  photo tiers only
- A USB cable that carries data, not just charge
- Any Apple ID. A free one is fine, no paid developer account needed

## Install, step by step

**1. Open the project**

    open ios/CozmoCapture/CozmoCapture.xcodeproj

**2. Add your Apple ID to Xcode** if it is not already there

Xcode menu -> Settings -> Accounts -> `+` -> Apple ID -> sign in. Close
Settings.

**3. Set the signing team**

Click the blue project icon at the top of the left sidebar. Under TARGETS pick
**CozmoCapture**. Open the **Signing & Capabilities** tab.

- Tick **Automatically manage signing** if it is not ticked
- **Team**: pick your own name. It will say "(Personal Team)" on a free account

**4. Change the bundle identifier**

Still on Signing & Capabilities. It is `com.khushi-saxena.CozmoCapture`, which
is tied to my team and will not sign under yours. Change it to anything
unique:

    com.yourname.cozmocapture

The Status line should go green. If not, see troubleshooting.

**5. Pick your phone and run**

Plug the iPhone in. Unlock it, leave the screen on. In the device dropdown at
the top of the Xcode window, select your iPhone by name - **not** a simulator.
ARKit does not exist in the simulator; the app will build and then do nothing.

Press **Cmd-R**.

**6. Trust the developer certificate**

The first run installs the app but refuses to launch it. On the phone:

Settings -> General -> VPN & Device Management -> Developer App -> tap your
Apple ID -> **Trust**

Press Cmd-R again, or open the app from the home screen.

You should get a live camera view with Record, Shutter and Export buttons and
a `tracking:` line at the bottom.

---

## When it does not work

### "Failed to install the app on the device" / "not a valid bundle"

The build produced an app with no executable in it. Check:

    ls -la ~/Library/Developer/Xcode/DerivedData/CozmoCapture-*/Build/Products/Debug-iphoneos/CozmoCapture.app/

If you see only `Info.plist`, `PkgInfo` and `embedded.mobileprovision` and no
`CozmoCapture` executable, the Compile Sources phase is empty.

Fix: project icon -> CozmoCapture target -> **Build Phases** -> expand
**Compile Sources**. It must list three files:

    CozmoCaptureApp.swift
    ContentView.swift
    CaptureRecorder.swift

If any are missing: `+` -> **Add Other...** -> go to
`ios/CozmoCapture/CozmoCapture/` -> select them -> in the dialog, leave
**Copy items if needed** unticked and **Create groups** selected -> Finish.

Then Product -> Clean Build Folder (Shift-Cmd-K) and run again.

### Build succeeds but install still fails

Stale build cache. Quit Xcode, then:

    rm -rf ~/Library/Developer/Xcode/DerivedData/CozmoCapture-*

Reopen, plug in, Cmd-R.

Still failing: delete the app from the phone (long-press icon -> Remove App ->
Delete App), reboot the phone, unplug and replug the cable, try again. A stale
install with a dead certificate blocks a new one.

### "Signing for CozmoCapture requires a development team"

Team is None. Go back to step 3. If the dropdown offers nothing but None, quit
Xcode entirely (Cmd-Q) and reopen - it often does not refresh the account list
until restart.

### "codesign wants to access key ... in your keychain"

Type your **Mac login password**, not your Apple ID password. Click
**Always Allow**, or it asks on every build.

### The phone says "CozmoCapture is no longer available"

Free Apple ID builds expire after 7 days. Normal, not a bug. Plug in and press
Cmd-R to reinstall. You may need to trust the developer again.

### "iPhone is not available because pairing is in progress"

Unlock the phone and leave it unlocked. If a "Trust This Computer?" alert
appears, tap Trust and enter the passcode. Wait 30-60 seconds. Check
Window -> Devices and Simulators until it shows as connected.

### Xcode sits on "Copying shared cache symbols from iPhone"

Normal on first run with a new device or after an iOS update. A few GB of
debug symbols, 5-15 minutes, happens once. Do not cancel, do not unplug.

### The app crashes immediately on launch

Camera permission missing. Project icon -> CozmoCapture target -> **Info** tab
-> hover a row, click `+`, add **Privacy - Camera Usage Description** with any
text.

It is already set in this repo. If it is missing, that is a bug worth telling
me about.

---

## Using it

Full instructions in `protocol/capture_protocol.md`. Short version:

1. **Open every interior door first.** A closed door reads as solid wall to
   the LiDAR and will never be found as an opening.
2. Wait until the bottom line says `tracking: normal` before recording.
3. Type a room name in the text field.
4. Record. Walk the perimeter slowly, about one step per second, phone at
   chest height pointing at the wall ahead. Sweep down at the wall-floor join
   and up at the wall-ceiling join along each wall. Walking fast halves the
   depth confidence - measured, not a guess.
5. Return to the exact spot you started. That closes the loop, which the drift
   correction uses.
6. Before stopping, stand still and tap **Shutter** 4 times from four
   different positions. Those become the photo tier.
7. Stop, then Export, then AirDrop the zip to a Mac.

Watch two things while walking. `tracking: limited_excessive_motion` means
slow down. `dropped:` climbing past about 20 means the phone cannot keep up
writing to disk - slow down or free up storage.

## Getting the data into the pipeline

    unzip -o capture_XXXXXXXXX.zip -d benchmark/captures/
    python3 scripts/run.py --capture benchmark/captures/capture_XXXXXXXXX --tier lidar

Also `--tier video` and `--tier photo` on the same capture.

## What lands on disk

    capture_1788930419/
    manifest.json          device, resolutions, formats, frame counts
    frames/000000.jpg      RGB at 6 fps
    depth/000000.bin       float32 metres, row-major (Pro devices)
    depth/000000_conf.bin  uint8 confidence per pixel
    poses.jsonl            per frame: transform, intrinsics, tracking state
    stills/<room>/         full-res photos, no poses, no depth by design
