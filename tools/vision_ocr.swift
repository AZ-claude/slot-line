// Reads text from image files with macOS Vision (on-device, no network, no LLM).
// Usage: vision_ocr <image> [<image> ...]
// Prints one JSON line per image: {"path": ..., "lines": [{"text": ..., "box": [x0, y0, x1, y1]}, ...]}
// Boxes are in image pixels with the origin at the top left.
import Foundation
import Vision
import AppKit

for path in CommandLine.arguments.dropFirst() {
    var lines: [[String: Any]] = []
    if let image = NSImage(contentsOfFile: path),
       let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) {
        let width = Double(cg.width), height = Double(cg.height)
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["ja-JP", "en-US"]
        request.usesLanguageCorrection = false
        try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([request])
        for observation in request.results ?? [] {
            guard let best = observation.topCandidates(1).first else { continue }
            let r = observation.boundingBox
            lines.append(["text": best.string,
                          "box": [Int(r.minX * width), Int((1 - r.maxY) * height), Int(r.maxX * width), Int((1 - r.minY) * height)]])
        }
    }
    let data = try! JSONSerialization.data(withJSONObject: ["path": path, "lines": lines])
    print(String(data: data, encoding: .utf8)!)
    fflush(stdout)
}
