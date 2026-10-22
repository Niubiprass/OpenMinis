//
//  CrashIPSSymbolicator.swift
//  MinisApp
//
//  Minimal reader for Apple `.ips` crash reports. Apple has no public parser
//  for this format; the report is a header JSON line followed by a payload
//  JSON line (newer tools sometimes emit one object). We only resolve frames
//  whose image UUID matches an image already loaded in this process, so an
//  address from a different build is never guessed into a plausible symbol.
//

import Foundation
import Darwin
import MachO

struct CrashIPSFrame {
    let imageName: String
    let imageUUID: String
    let imageBase: UInt64
    let imageOffset: UInt64
    let address: UInt64
    let inlineSymbol: String?
    var symbol: String?

    var display: String {
        let location = String(format: "0x%llx", imageOffset)
        if let symbol, !symbol.isEmpty {
            return "\(imageName)  \(symbol) + \(location)"
        }
        if let inlineSymbol, !inlineSymbol.isEmpty {
            return "\(imageName)  \(inlineSymbol) + \(location)"
        }
        return "\(imageName)  \(location)"
    }
}

struct CrashIPSReport {
    let fileName: String
    let date: Date
    let bugType: String
    let exceptionType: String
    let terminationReason: String
    let faultingThread: Int
    var frames: [CrashIPSFrame]

    var displayLines: [String] {
        var lines = ["\(bugType) · \(exceptionType)"]
        if !terminationReason.isEmpty {
            lines.append("Termination: \(terminationReason)")
        }
        lines.append("Faulting thread: \(faultingThread)")
        lines.append("")
        if frames.isEmpty {
            lines.append("No frames in this report.")
        } else {
            for (index, frame) in frames.enumerated() {
                lines.append(String(format: "%2d  %@", index, frame.display))
            }
        }
        return lines
    }
}

enum CrashIPSParser {
    static func parse(url: URL) -> CrashIPSReport? {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return nil }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        var header: [String: Any] = [:]
        var payload: [String: Any] = [:]
        let lines = text.split(separator: "\n", maxSplits: 1, omittingEmptySubsequences: false)
        if lines.count >= 2,
           let first = jsonObject(String(lines[0])),
           let second = jsonObject(String(lines[1])) {
            header = first
            payload = second
        } else if let single = jsonObject(trimmed) {
            payload = single
            header = single
        } else {
            return nil
        }

        let usedImages = payload["usedImages"] as? [[String: Any]] ?? []
        let threads = payload["threads"] as? [[String: Any]] ?? []
        let faulting = intValue(payload["faultingThread"]) ?? 0
        let thread = threads.indices.contains(faulting) ? threads[faulting] : threads.first
        let rawFrames = thread?["frames"] as? [[String: Any]] ?? []

        var frames: [CrashIPSFrame] = []
        for raw in rawFrames {
            guard frames.count < 80 else { break }
            let imageIndex = intValue(raw["imageIndex"]) ?? -1
            guard usedImages.indices.contains(imageIndex) else { continue }
            let image = usedImages[imageIndex]
            let base = uint64Value(image["base"]) ?? 0
            let imageOffset = uint64Value(raw["imageOffset"])
                ?? uint64Value(raw["imageAddress"]).map { $0 >= base ? $0 - base : 0 }
                ?? 0
            let name = image["name"] as? String ?? image["path"] as? String ?? "unknown"
            let uuid = image["uuid"] as? String ?? ""
            frames.append(CrashIPSFrame(
                imageName: name,
                imageUUID: uuid,
                imageBase: base,
                imageOffset: imageOffset,
                address: base &+ imageOffset,
                inlineSymbol: raw["symbol"] as? String,
                symbol: nil))
        }

        let exception = payload["exception"] as? [String: Any] ?? [:]
        let term = payload["termination"] as? [String: Any] ?? [:]
        let exceptionType = [exception["type"] as? String, exception["signal"] as? String]
            .compactMap { $0 }
            .filter { !$0.isEmpty }
            .joined(separator: " / ")
        let terminationReason = [term["indicator"] as? String,
                                 intValue(term["code"]).map { "code \($0)" }]
            .compactMap { $0 }
            .joined(separator: " · ")
        let bugType = header["bug_type"] as? String
            ?? payload["bug_type"] as? String
            ?? "ips"
        let date = parseDate(header["timestamp"] as? String ?? payload["timestamp"] as? String)
            ?? (try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate)
            ?? Date()

        return CrashIPSReport(
            fileName: url.lastPathComponent,
            date: date,
            bugType: bugType,
            exceptionType: exceptionType.isEmpty ? bugType : exceptionType,
            terminationReason: terminationReason,
            faultingThread: faulting,
            frames: frames)
    }

    private static func jsonObject(_ text: String) -> [String: Any]? {
        guard let data = text.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data),
              let dictionary = object as? [String: Any] else { return nil }
        return dictionary
    }

    private static func intValue(_ value: Any?) -> Int? {
        if let number = value as? NSNumber { return number.intValue }
        if let string = value as? String { return Int(string) }
        return nil
    }

    private static func uint64Value(_ value: Any?) -> UInt64? {
        if let number = value as? NSNumber { return number.uint64Value }
        if let string = value as? String { return UInt64(string) }
        return nil
    }

    private static func parseDate(_ value: String?) -> Date? {
        guard let value else { return nil }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        for format in ["yyyy-MM-dd HH:mm:ss.SS Z", "yyyy-MM-dd HH:mm:ss Z"] {
            formatter.dateFormat = format
            if let date = formatter.date(from: value) { return date }
        }
        return ISO8601DateFormatter().date(from: value)
    }
}

enum CrashSymbolicator {
    private struct LoadedImage {
        let name: String
        let uuid: String
        let slide: Int64
        let textVMAddr: UInt64
    }

    /// Resolve only images loaded in this process. Matching by UUID is the
    /// guard against symbolizing a frame from a different build.
    static func symbolicate(_ report: CrashIPSReport) -> CrashIPSReport {
        let images = loadedImages()
        var result = report
        result.frames = report.frames.map { frame in
            guard let loaded = images.first(where: { image in
                if !frame.imageUUID.isEmpty && !image.uuid.isEmpty {
                    return image.uuid.caseInsensitiveCompare(frame.imageUUID) == .orderedSame
                }
                return image.name == frame.imageName || image.name.hasSuffix("/" + frame.imageName)
            }) else { return frame }

            let runtime = loaded.slide &+ Int64(bitPattern: loaded.textVMAddr) &+ Int64(frame.imageOffset)
            guard runtime > 0, let pointer = UnsafeRawPointer(bitPattern: Int(runtime)) else {
                return frame
            }
            var info = Dl_info()
            guard dladdr(pointer, &info) != 0, let name = info.dli_sname else { return frame }
            var resolved = frame
            resolved.symbol = String(cString: name)
            return resolved
        }
        return result
    }

    private static func loadedImages() -> [LoadedImage] {
        var result: [LoadedImage] = []
        for index in 0..<_dyld_image_count() {
            guard let header = _dyld_get_image_header(index) else { continue }
            let raw = UnsafeRawPointer(header)
            guard let info = imageInfo(raw), let name = _dyld_get_image_name(index) else { continue }
            result.append(LoadedImage(name: String(cString: name),
                                      uuid: info.uuid,
                                      slide: Int64(_dyld_get_image_vmaddr_slide(index)),
                                      textVMAddr: info.textVMAddr))
        }
        return result
    }

    private static func imageInfo(_ header: UnsafeRawPointer) -> (uuid: String, textVMAddr: UInt64)? {
        let magic = header.load(as: UInt32.self)
        let is64 = magic == 0xfeedfacf
        guard magic == 0xfeedfacf || magic == 0xfeedface else { return nil }
        let headerSize = is64 ? 32 : 28
        let ncmds = Int(header.load(fromByteOffset: 16, as: UInt32.self))
        var command = header.advanced(by: headerSize)
        var uuid = ""
        var textVMAddr: UInt64 = 0

        for _ in 0..<ncmds {
            let cmd = command.load(as: UInt32.self)
            let size = Int(command.load(fromByteOffset: 4, as: UInt32.self))
            guard size >= 8 else { break }
            if cmd == 0x1b { // LC_UUID
                let bytes = UnsafeRawBufferPointer(start: command.advanced(by: 8), count: 16)
                uuid = bytes.map { String(format: "%02X", $0) }.joined()
            } else if is64 && cmd == 0x19 { // LC_SEGMENT_64
                let nameBytes = UnsafeRawBufferPointer(start: command.advanced(by: 8), count: 16)
                let name = String(bytes: nameBytes, encoding: .utf8)?.trimmingCharacters(in: CharacterSet(charactersIn: "\0")) ?? ""
                if name == "__TEXT" {
                    textVMAddr = command.load(fromByteOffset: 24, as: UInt64.self)
                }
            } else if !is64 && cmd == 0x1 { // LC_SEGMENT
                let nameBytes = UnsafeRawBufferPointer(start: command.advanced(by: 8), count: 16)
                let name = String(bytes: nameBytes, encoding: .utf8)?.trimmingCharacters(in: CharacterSet(charactersIn: "\0")) ?? ""
                if name == "__TEXT" {
                    textVMAddr = UInt64(command.load(fromByteOffset: 24, as: UInt32.self))
                }
            }
            command = command.advanced(by: size)
        }
        guard !uuid.isEmpty, textVMAddr > 0 else { return nil }
        return (uuid, textVMAddr)
    }
}