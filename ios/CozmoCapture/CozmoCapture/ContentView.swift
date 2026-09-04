import ARKit
import SwiftUI

/// Live ARKit preview. The session is owned by the recorder, not by this view,
/// so recording keeps running regardless of what the UI does.
struct ARPreview: UIViewRepresentable {
    let session: ARSession

    func makeUIView(context: Context) -> ARSCNView {
        let view = ARSCNView()
        view.session = session
        view.automaticallyUpdatesLighting = true
        return view
    }

    func updateUIView(_ uiView: ARSCNView, context: Context) {}
}

struct ContentView: View {
    @StateObject private var recorder = CaptureRecorder()
    @State private var showShare = false

    var body: some View {
        ZStack(alignment: .bottom) {
            ARPreview(session: recorder.session)
                .ignoresSafeArea()

            VStack(spacing: 12) {
                Spacer()

                HStack {
                    Text("tracking: \(recorder.trackingState)")
                    Spacer()
                    Text("\(recorder.frameCount) frames · \(recorder.stillCount) stills")
                }
                .font(.caption.monospaced())
                .foregroundStyle(.white)

                if recorder.droppedFrames > 0 {
                    Text("dropped: \(recorder.droppedFrames)")
                        .font(.caption.monospaced())
                        .foregroundStyle(.orange)
                }

                HStack {
                    Text("room")
                        .font(.caption)
                        .foregroundStyle(.white)
                    TextField("room_01", text: $recorder.roomName)
                        .textFieldStyle(.roundedBorder)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                }

                HStack(spacing: 12) {
                    Button(recorder.isRecording ? "Stop" : "Record") {
                        recorder.isRecording ? recorder.stopRecording() : recorder.startRecording()
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(recorder.isRecording ? .red : .accentColor)

                    Button("Shutter") { recorder.takeStill() }
                        .buttonStyle(.bordered)
                        .disabled(!recorder.isRecording)

                    Button("Export") {
                        recorder.exportLatest()
                    }
                    .buttonStyle(.bordered)
                    .disabled(recorder.isRecording)
                }

                Text(recorder.statusLine)
                    .font(.caption2.monospaced())
                    .foregroundStyle(.white.opacity(0.8))
                    .lineLimit(2)
            }
            .padding()
            .background(.black.opacity(0.55))
        }
        .onAppear { recorder.startSession() }
        .onChange(of: recorder.exportURL) { _, url in
            if url != nil { showShare = true }
        }
        .sheet(isPresented: $showShare) {
            if let url = recorder.exportURL {
                ShareSheet(items: [url])
            }
        }
    }
}

struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
