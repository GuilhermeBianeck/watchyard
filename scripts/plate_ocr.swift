import Foundation
import Vision

// Return candidates by frame so several observations of one frame never count twice.
var frames = [[String]]()
for path in CommandLine.arguments.dropFirst() {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    let handler = VNImageRequestHandler(url: URL(fileURLWithPath: path))
    do {
        try handler.perform([request])
        frames.append((request.results ?? []).compactMap { observation in
            guard let result = observation.topCandidates(1).first, result.confidence >= 0.5,
                  observation.boundingBox.height > 0,
                  observation.boundingBox.width / observation.boundingBox.height >= 1.8 else { return nil }
            return result.string
        })
    } catch {
        frames.append([])
    }
}
FileHandle.standardOutput.write(try JSONEncoder().encode(frames))
