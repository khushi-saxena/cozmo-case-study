import ARKit
import CoreImage
import SwiftUI
import simd
internal import Combine

/// Records one ARKit session to disk: RGB frames, LiDAR depth + confidence,
/// per-frame camera poses and intrinsics, plus separate full-resolution stills
/// that carry no pose information.
///
/// One session produces all three input tiers. The tier split happens later,
/// on the Mac, in tierize.py:
///   lidar -> frames + depth + poses
///   video -> frames + poses, depth ignored
///   photo -> stills only, poses and depth never read
final class CaptureRecorder: NSObject, ObservableObject, ARSessionDelegate {

    // MARK: UI state

    @Published var isRecording = false
    @Published var frameCount = 0
    @Published var stillCount = 0
    @Published var droppedFrames = 0
    @Published var trackingState = "not started"
    @Published var roomName = "room_01"
    @Published var statusLine = "ready"
    @Published var exportURL: URL?

    // MARK: session

    let session = ARSession()
    private let io = DispatchQueue(label: "cozmo.capture.io", qos: .userInitiated)
    private let ciContext = CIContext()

    // MARK: capture state

    private var captureRoot: URL?
    private var poseHandle: FileHandle?
    private var startedAt: Date?
    private var lastFrameTime: TimeInterval = 0
    private var ioBusy = false
    private var shutterRequested = false

    private var rgbWidth = 0, rgbHeight = 0
    private var depthWidth = 0, depthHeight = 0
    private var hasDepth = false

    /// Frames per second written to disk. ARKit delivers 60; we do not need
    /// 60 nearly identical views, and the write path cannot keep up with it.
    private let targetFPS: Double = 6

    override init() {
        super.init()
        session.delegate = self
    }

    // MARK: lifecycle

    func startSession() {
        let config = ARWorldTrackingConfiguration()
        // Gravity alignment means world Y is up. Floor and ceiling planes are
        // then horizontal by construction, which the pipeline relies on.
        config.worldAlignment = .gravity
        config.environmentTexturing = .none
        if ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth) {
            config.frameSemantics.insert(.sceneDepth)
            hasDepth = true
        }
        session.run(config, options: [.resetTracking, .removeExistingAnchors])
        statusLine = hasDepth ? "session running, depth available" : "session running, no depth on this device"
    }

    func startRecording() {
        guard !isRecording else { return }
        let id = "capture_\(Int(Date().timeIntervalSince1970))"
        let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(id, isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: root.appendingPathComponent("frames"),
                                                    withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: root.appendingPathComponent("depth"),
                                                    withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: root.appendingPathComponent("stills"),
                                                    withIntermediateDirectories: true)
            let poses = root.appendingPathComponent("poses.jsonl")
            FileManager.default.createFile(atPath: poses.path, contents: nil)
            poseHandle = try FileHandle(forWritingTo: poses)
        } catch {
            statusLine = "could not create capture folder: \(error.localizedDescription)"
            return
        }
        captureRoot = root
        startedAt = Date()
        frameCount = 0
        stillCount = 0
        droppedFrames = 0
        lastFrameTime = 0
        isRecording = true
        statusLine = "recording \(id)"
    }

    func stopRecording() {
        guard isRecording, let root = captureRoot else { return }
        isRecording = false
        io.sync { }                       // let queued writes finish
        try? poseHandle?.close()
        poseHandle = nil
        writeManifest(root: root)
        statusLine = "stopped, \(frameCount) frames, \(stillCount) stills"
    }

    /// Photo tier. Writes one full-resolution still into stills/<room>/ and
    /// deliberately records no pose, no depth and no intrinsics for it.
    func takeStill() {
        guard isRecording else {
            statusLine = "start recording before taking stills"
            return
        }
        shutterRequested = true
    }

    // MARK: ARSessionDelegate

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        trackingState = describe(frame.camera.trackingState)
        guard isRecording, let root = captureRoot else { return }

        if shutterRequested {
            shutterRequested = false
            writeStill(frame: frame, root: root)
        }

        // Throttle to targetFPS.
        let now = frame.timestamp
        guard now - lastFrameTime >= 1.0 / targetFPS else { return }

        // If the write queue has not drained, drop this frame rather than
        // queueing an unbounded backlog. Dropped frames are counted and
        // reported, so the benchmark can account for them.
        guard !ioBusy else {
            droppedFrames += 1
            return
        }
        lastFrameTime = now

        let index = frameCount
        frameCount += 1

        let pixelBuffer = frame.capturedImage
        rgbWidth = CVPixelBufferGetWidth(pixelBuffer)
        rgbHeight = CVPixelBufferGetHeight(pixelBuffer)

        // Depth buffers are small; copy them synchronously so ARKit can recycle
        // its pool immediately.
        var depthBytes: Data?
        var confBytes: Data?
        if let sceneDepth = frame.sceneDepth {
            depthWidth = CVPixelBufferGetWidth(sceneDepth.depthMap)
            depthHeight = CVPixelBufferGetHeight(sceneDepth.depthMap)
            depthBytes = copyBuffer(sceneDepth.depthMap, bytesPerPixel: 4)
            if let conf = sceneDepth.confidenceMap {
                confBytes = copyBuffer(conf, bytesPerPixel: 1)
            }
        }

        let poseLine = poseJSON(frame: frame, index: index)

        ioBusy = true
        io.async { [weak self] in
            guard let self else { return }
            let name = String(format: "%06d", index)

            if let jpeg = self.jpeg(from: pixelBuffer, quality: 0.85) {
                try? jpeg.write(to: root.appendingPathComponent("frames/\(name).jpg"))
            }
            if let depthBytes {
                try? depthBytes.write(to: root.appendingPathComponent("depth/\(name).bin"))
            }
            if let confBytes {
                try? confBytes.write(to: root.appendingPathComponent("depth/\(name)_conf.bin"))
            }
            if let line = (poseLine + "\n").data(using: .utf8) {
                self.poseHandle?.write(line)
            }

            DispatchQueue.main.async { self.ioBusy = false }
        }
    }

    func session(_ session: ARSession, didFailWithError error: Error) {
        statusLine = "session error: \(error.localizedDescription)"
    }

    // MARK: writing

    private func writeStill(frame: ARFrame, root: URL) {
        let room = roomName.isEmpty ? "room_unnamed" : roomName
        let dir = root.appendingPathComponent("stills/\(room)", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let index = stillCount
        stillCount += 1
        let pixelBuffer = frame.capturedImage
        io.async { [weak self] in
            guard let self, let jpeg = self.jpeg(from: pixelBuffer, quality: 0.95) else { return }
            let name = String(format: "still_%03d.jpg", index)
            try? jpeg.write(to: dir.appendingPathComponent(name))
        }
    }

    private func poseJSON(frame: ARFrame, index: Int) -> String {
        let t = frame.camera.transform
        let rows = (0..<4).map { r in
            [t.columns.0[r], t.columns.1[r], t.columns.2[r], t.columns.3[r]]
                .map { String(format: "%.6f", $0) }.joined(separator: ",")
        }.map { "[\($0)]" }.joined(separator: ",")

        let k = frame.camera.intrinsics
        let kRows = (0..<3).map { r in
            [k.columns.0[r], k.columns.1[r], k.columns.2[r]]
                .map { String(format: "%.6f", $0) }.joined(separator: ",")
        }.map { "[\($0)]" }.joined(separator: ",")

        let res = frame.camera.imageResolution
        return """
        {"index":\(index),"timestamp":\(frame.timestamp),\
        "transform_rows":[\(rows)],"intrinsics_rows":[\(kRows)],\
        "image_width":\(Int(res.width)),"image_height":\(Int(res.height)),\
        "tracking_state":"\(describe(frame.camera.trackingState))"}
        """
    }

    private func writeManifest(root: URL) {
        var sys = utsname(); uname(&sys)
        let model = withUnsafePointer(to: &sys.machine) {
            $0.withMemoryRebound(to: CChar.self, capacity: 1) { String(cString: $0) }
        }
        let manifest: [String: Any] = [
            "capture_id": root.lastPathComponent,
            "app_version": "0.1.0",
            "device_model": model,
            "system_version": UIDevice.current.systemVersion,
            "world_alignment": "gravity",
            "started_at": ISO8601DateFormatter().string(from: startedAt ?? Date()),
            "frame_count": frameCount,
            "still_count": stillCount,
            "dropped_frames": droppedFrames,
            "target_fps": targetFPS,
            "rgb_width": rgbWidth,
            "rgb_height": rgbHeight,
            "depth_available": hasDepth,
            "depth_width": depthWidth,
            "depth_height": depthHeight,
            "depth_format": "float32_meters_row_major",
            "confidence_format": "uint8_row_major",
            "pose_convention": "transform_rows is row-major; world = T * camera",
            "notes": "stills/ carry no poses, no depth and no intrinsics by design"
        ]
        if let data = try? JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted]) {
            try? data.write(to: root.appendingPathComponent("manifest.json"))
        }
    }

    // MARK: helpers

    /// Copies a CVPixelBuffer row by row, discarding any row padding, so the
    /// bytes on disk are a dense row-major array the pipeline can read directly.
    private func copyBuffer(_ buffer: CVPixelBuffer, bytesPerPixel: Int) -> Data? {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { return nil }
        let width = CVPixelBufferGetWidth(buffer)
        let height = CVPixelBufferGetHeight(buffer)
        let stride = CVPixelBufferGetBytesPerRow(buffer)
        let rowBytes = width * bytesPerPixel
        var out = Data(capacity: rowBytes * height)
        for row in 0..<height {
            let start = base.advanced(by: row * stride)
            out.append(Data(bytes: start, count: rowBytes))
        }
        return out
    }

    private func jpeg(from buffer: CVPixelBuffer, quality: CGFloat) -> Data? {
        let image = CIImage(cvPixelBuffer: buffer)
        guard let cg = ciContext.createCGImage(image, from: image.extent) else { return nil }
        return UIImage(cgImage: cg, scale: 1, orientation: .right)
            .jpegData(compressionQuality: quality)
    }

    private func describe(_ state: ARCamera.TrackingState) -> String {
        switch state {
        case .normal: return "normal"
        case .notAvailable: return "not_available"
        case .limited(let reason):
            switch reason {
            case .initializing: return "limited_initializing"
            case .excessiveMotion: return "limited_excessive_motion"
            case .insufficientFeatures: return "limited_insufficient_features"
            case .relocalizing: return "limited_relocalizing"
            @unknown default: return "limited_unknown"
            }
        }
    }

    // MARK: export

    /// Zips the capture folder using NSFileCoordinator so no third-party
    /// dependency is needed, then hands the zip to the share sheet.
    func exportLatest() {
        guard let root = captureRoot else {
            statusLine = "nothing to export yet"
            return
        }
        io.async { [weak self] in
            var error: NSError?
            var produced: URL?
            NSFileCoordinator().coordinate(readingItemAt: root,
                                           options: [.forUploading],
                                           error: &error) { zipURL in
                let dest = FileManager.default.temporaryDirectory
                    .appendingPathComponent("\(root.lastPathComponent).zip")
                try? FileManager.default.removeItem(at: dest)
                try? FileManager.default.copyItem(at: zipURL, to: dest)
                produced = dest
            }
            DispatchQueue.main.async {
                if let produced {
                    self?.exportURL = produced
                    self?.statusLine = "ready to share"
                } else {
                    self?.statusLine = "zip failed: \(error?.localizedDescription ?? "unknown")"
                }
            }
        }
    }
}
