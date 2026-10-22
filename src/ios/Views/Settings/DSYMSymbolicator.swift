//
//  DSYMSymbolicator.swift
//  MinisApp
//
//  Minimal, read-only dSYM symbol table reader for `.ips` crash frames.
//
//  This module deliberately does one thing: read the Mach-O symbol table
//  (`LC_SYMTAB` / `nlist_64`) from a `.dSYM` bundle and answer "which function
//  starts at or before this address?". It does not parse DWARF line tables,
//  does not use any third-party code, and has no UI.
//
//  Everything here is best effort. A truncated, fat, encrypted or otherwise
//  unusual file must return nil instead of trapping, so every field read is
//  bounds checked and byte-wise (no unaligned `load(as:)`).
//

import Foundation
import MachO

// MARK: - Public data

struct DSYMSymbol {
    let start: UInt64
    let end: UInt64
    let name: String
}

/// A parsed `.dSYM` symbol table for one Mach-O slice.
///
/// `uuid` is the canonical dashed uppercase UUID from `LC_UUID`, so it can be
/// compared with the `uuid` field of an `.ips` `usedImages` entry.
final class DSYMStore {
    private(set) var uuid: String = ""
    private(set) var symbols: [DSYMSymbol] = []

    /// vmaddr of the `__TEXT` segment. 0 when the slice has no `__TEXT`.
    /// Some dSYMs use image-relative addresses (0) and some use the linked
    /// vmaddr (for example 0x100000000); the symbolicator uses this only as a
    /// fallback when a direct image-offset lookup finds nothing.
    private(set) var textVMAddress: UInt64 = 0

    // MARK: Loading

    /// Accepts either the `.dSYM` directory itself or one of the Mach-O files
    /// inside `Contents/Resources/DWARF/`.
    init?(dsymURL: URL) {
        guard let parsed = DSYMStore.load(dsymURL) else { return nil }
        self.uuid = parsed.uuid
        self.symbols = parsed.symbols
        self.textVMAddress = parsed.textVMAddress
    }

    /// Nearest symbol whose `start` is less than or equal to `address`.
    /// Classic binary search; returns nil below the first symbol.
    func symbol(at address: UInt64) -> String? {
        guard !symbols.isEmpty else { return nil }

        var low = 0
        var high = symbols.count - 1
        var match: Int?

        while low <= high {
            let mid = low + (high - low) / 2
            if symbols[mid].start <= address {
                match = mid
                low = mid + 1
            } else {
                high = mid - 1
            }
        }

        guard let index = match else { return nil }
        return symbols[index].name
    }

    /// Case-insensitive UUID match. Hyphens are ignored so both
    /// `AAAAAAAA-BBBB-...` (`.ips`) and `AAAAAAAABBBB...` are accepted.
    func matches(uuid other: String) -> Bool {
        guard !uuid.isEmpty, !other.isEmpty else { return false }
        let mine = uuid.replacingOccurrences(of: "-", with: "")
        let theirs = other.replacingOccurrences(of: "-", with: "")
        return mine.caseInsensitiveCompare(theirs) == .orderedSame
    }

    // MARK: Candidate discovery

    private static func load(_ url: URL) -> ParsedDSYM? {
        let candidates = binaryCandidates(at: url)
        guard !candidates.isEmpty else { return nil }

        var best: ParsedDSYM?

        for candidate in candidates {
            guard let data = try? Data(contentsOf: candidate, options: .mappedIfSafe) else {
                continue
            }

            let parsed = data.withUnsafeBytes { (raw: UnsafeRawBufferPointer) -> ParsedDSYM? in
                guard raw.count >= 4 else { return nil }
                let view = MachOView(bytes: raw)

                // FAT binaries are stored big-endian. Only FAT_MAGIC is
                // handled; a little-endian FAT (FAT_CIGAM) is not an iOS
                // dSYM layout we care about.
                if let magic = view.uint32BE(at: 0), magic == fatMagic {
                    return parseFat(view)
                }

                // A thin 64-bit Mach-O on iOS/arm64 is MH_MAGIC_64 in
                // little-endian byte order.
                if let magic = view.uint32LE(at: 0), magic == mhMagic64 {
                    return parseThin(view, offset: 0, size: raw.count)
                }

                return nil
            }

            guard let parsed = parsed else { continue }
            if let current = best {
                if parsed.rank > current.rank { best = parsed }
            } else {
                best = parsed
            }
        }

        return best
    }

    private static func binaryCandidates(at url: URL) -> [URL] {
        let manager = FileManager.default
        var isDirectory: ObjCBool = false
        guard manager.fileExists(atPath: url.path, isDirectory: &isDirectory) else {
            return []
        }
        if !isDirectory.boolValue { return [url] }

        let dwarf = url
            .appendingPathComponent("Contents", isDirectory: true)
            .appendingPathComponent("Resources", isDirectory: true)
            .appendingPathComponent("DWARF", isDirectory: true)

        let directory: URL
        if isDirectoryAt(dwarf) {
            directory = dwarf
        } else if url.lastPathComponent == "DWARF" && isDirectoryAt(url) {
            directory = url
        } else {
            return []
        }

        guard let entries = try? manager.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]) else {
            return []
        }

        return entries
            .filter { isRegularFileAt($0) }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    private static func isDirectoryAt(_ url: URL) -> Bool {
        var isDirectory: ObjCBool = false
        return FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory)
            && isDirectory.boolValue
    }

    private static func isRegularFileAt(_ url: URL) -> Bool {
        var isDirectory: ObjCBool = false
        return FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory)
            && !isDirectory.boolValue
    }

    // MARK: Mach-O constants

    private static let mhMagic64: UInt32 = 0xfeedfacf // MH_MAGIC_64
    private static let fatMagic: UInt32 = 0xcafebabe  // FAT_MAGIC (big-endian)
    private static let fatArchSize = 20
    private static let maxFatArchitectures = 128
    private static let machHeader64Size = 32
    private static let nlist64Size = 16
    private static let section64Size = 80
    private static let nSect: UInt8 = 0x0e          // N_SECT
    private static let nStabMask: UInt8 = 0xe0      // N_STAB
    private static let nTypeMask: UInt8 = 0x0e      // N_TYPE
    private static let cpuTypeARM64: UInt32 = 0x0100_000c
    private static let cpuTypeARM64_32: UInt32 = 0x0200_000c

    private enum LoadCommand {
        static let uuid: UInt32 = 0x1b        // LC_UUID
        static let symtab: UInt32 = 0x2      // LC_SYMTAB
        static let segment64: UInt32 = 0x19  // LC_SEGMENT_64
    }
}

// MARK: - Bounds-checked byte reader

/// Reads multi-byte integers byte by byte. This avoids both out-of-bounds
/// reads and unaligned `UnsafeRawPointer.load`, which can trap on some CPUs.
private struct MachOView {
    let bytes: UnsafeRawBufferPointer

    var count: Int { return bytes.count }

    func contains(_ offset: Int, _ length: Int) -> Bool {
        guard offset >= 0, length >= 0, offset <= count else { return false }
        return length <= count - offset
    }

    func uint8(at offset: Int) -> UInt8? {
        guard contains(offset, 1) else { return nil }
        return bytes[offset]
    }

    func uint32LE(at offset: Int) -> UInt32? {
        guard let b0 = uint8(at: offset),
              let b1 = uint8(at: offset + 1),
              let b2 = uint8(at: offset + 2),
              let b3 = uint8(at: offset + 3) else { return nil }
        return UInt32(b0)
            | (UInt32(b1) << 8)
            | (UInt32(b2) << 16)
            | (UInt32(b3) << 24)
    }

    func uint32BE(at offset: Int) -> UInt32? {
        guard let b0 = uint8(at: offset),
              let b1 = uint8(at: offset + 1),
              let b2 = uint8(at: offset + 2),
              let b3 = uint8(at: offset + 3) else { return nil }
        return (UInt32(b0) << 24)
            | (UInt32(b1) << 16)
            | (UInt32(b2) << 8)
            | UInt32(b3)
    }

    func uint64LE(at offset: Int) -> UInt64? {
        guard let low = uint32LE(at: offset),
              let high = uint32LE(at: offset + 4) else { return nil }
        return UInt64(low) | (UInt64(high) << 32)
    }

    /// Fixed-width C string (segment/section names): stops at the first NUL.
    func fixedString(at offset: Int, length: Int) -> String? {
        guard contains(offset, length) else { return nil }
        let slice = bytes[offset..<(offset + length)]
        let end = slice.firstIndex(of: 0) ?? slice.endIndex
        return String(decoding: slice[slice.startIndex..<end], as: UTF8.self)
    }

    /// NUL-terminated string inside `[offset, limit)`, capped to `maxLength`.
    /// Requires a terminator; a malformed table therefore skips the symbol.
    func cString(at offset: Int, limit: Int, maxLength: Int = 4096) -> String? {
        guard offset >= 0, offset < limit, limit <= count else { return nil }
        let stop = min(limit, offset + maxLength)
        var cursor = offset
        while cursor < stop && bytes[cursor] != 0 {
            cursor += 1
        }
        guard cursor < stop else { return nil }
        return String(decoding: bytes[offset..<cursor], as: UTF8.self)
    }
}// MARK: - Parsed slice

private struct ParsedDSYM {
    let uuid: String
    let symbols: [DSYMSymbol]
    let textVMAddress: UInt64
    let rank: Int
}

private struct ParsedSegment64 {
    let segmentNames: [String]
    let sectionNames: [String]
    let isText: Bool
    let vmaddr: UInt64
    let vmsize: UInt64
}

// MARK: - Mach-O parsing

private extension DSYMStore {
    /// Parse a big-endian FAT_MAGIC container and return the best 64-bit
    /// slice. Slices are scanned in file order; an arm64e/arm64 slice wins
    /// over any other architecture, and the first one wins ties.
    static func parseFat(_ view: MachOView) -> ParsedDSYM? {
        guard let count = view.uint32BE(at: 4),
              count > 0,
              count <= UInt32(maxFatArchitectures),
              view.contains(8, Int(count) * fatArchSize) else {
            return nil
        }

        var best: ParsedDSYM?

        for index in 0..<Int(count) {
            let base = 8 + index * fatArchSize
            guard let offset = view.uint32BE(at: base + 8),
                  let size = view.uint32BE(at: base + 12),
                  size > 0 else { continue }

            let sliceOffset = Int(offset)
            let sliceSize = Int(size)
            guard view.contains(sliceOffset, sliceSize) else { continue }
            guard let parsed = parseThin(view, offset: sliceOffset, size: sliceSize) else {
                continue
            }

            if let current = best {
                if parsed.rank > current.rank { best = parsed }
            } else {
                best = parsed
            }
        }

        return best
    }

    static func parseThin(_ view: MachOView, offset: Int, size: Int) -> ParsedDSYM? {
        guard offset >= 0,
              size >= machHeader64Size,
              view.contains(offset, size) else {
            return nil
        }

        guard let magic = view.uint32LE(at: offset), magic == mhMagic64,
              let cpuType = view.uint32LE(at: offset + 4),
              let cpuSubtype = view.uint32LE(at: offset + 8),
              let commandCount = view.uint32LE(at: offset + 16),
              let commandBytes = view.uint32LE(at: offset + 20) else {
            return nil
        }

        guard commandCount > 0, commandCount <= 100_000,
              Int(commandBytes) <= size - machHeader64Size else {
            return nil
        }

        let commandsStart = offset + machHeader64Size
        let commandsEnd = commandsStart + Int(commandBytes)
        guard commandsEnd <= offset + size else { return nil }

        var uuid: String?
        var symtab: (symoff: UInt32, nsyms: UInt32, stroff: UInt32, strsize: UInt32)?
        var sectionSegments: [String] = []
        var sectionNames: [String] = []
        var textStart: UInt64 = 0
        var textEnd: UInt64 = 0

        var cursor = commandsStart
        for _ in 0..<Int(commandCount) {
            guard cursor < commandsEnd,
                  let command = view.uint32LE(at: cursor),
                  let commandSize = view.uint32LE(at: cursor + 4),
                  commandSize >= 8,
                  Int(commandSize) <= commandsEnd - cursor else {
                return nil
            }

            switch command {
            case LoadCommand.uuid:
                guard commandSize >= 24,
                      let parsed = uuidString(view, at: cursor + 8) else { return nil }
                uuid = parsed

            case LoadCommand.symtab:
                guard commandSize >= 24,
                      let symoff = view.uint32LE(at: cursor + 8),
                      let nsyms = view.uint32LE(at: cursor + 12),
                      let stroff = view.uint32LE(at: cursor + 16),
                      let strsize = view.uint32LE(at: cursor + 20) else {
                    return nil
                }
                symtab = (symoff, nsyms, stroff, strsize)

            case LoadCommand.segment64:
                guard let segment = parseSegment64(
                    view,
                    commandOffset: cursor,
                    commandSize: Int(commandSize)) else {
                    return nil
                }
                sectionSegments.append(contentsOf: segment.segmentNames)
                sectionNames.append(contentsOf: segment.sectionNames)

                if segment.isText {
                    if textStart == 0 || segment.vmaddr < textStart {
                        textStart = segment.vmaddr
                    }
                    let end = segment.vmaddr &+ segment.vmsize
                    guard end >= segment.vmaddr else { return nil }
                    if end > textEnd { textEnd = end }
                }

            default:
                break
            }

            cursor += Int(commandSize)
        }

        guard cursor <= commandsEnd, let parsedUUID = uuid, !parsedUUID.isEmpty,
              let table = symtab else {
            return nil
        }

        guard let parsedSymbols = parseSymbols(
            view,
            sliceOffset: offset,
            sliceSize: size,
            table: table,
            sectionSegments: sectionSegments,
            sectionNames: sectionNames,
            textEnd: textEnd) else {
            return nil
        }

        return ParsedDSYM(
            uuid: parsedUUID,
            symbols: parsedSymbols,
            textVMAddress: textStart,
            rank: architectureRank(cpuType: cpuType, cpuSubtype: cpuSubtype))
    }

    static func parseSegment64(
        _ view: MachOView,
        commandOffset: Int,
        commandSize: Int) -> ParsedSegment64? {
        guard commandSize >= 72,
              let segmentName = view.fixedString(at: commandOffset + 8, length: 16),
              let vmaddr = view.uint64LE(at: commandOffset + 24),
              let vmsize = view.uint64LE(at: commandOffset + 32),
              let sectionCount = view.uint32LE(at: commandOffset + 64) else {
            return nil
        }

        let count = Int(sectionCount)
        guard count <= (commandSize - 72) / section64Size else { return nil }

        var segmentNames: [String] = []
        var sectionNames: [String] = []
        segmentNames.reserveCapacity(count)
        sectionNames.reserveCapacity(count)

        for index in 0..<count {
            let base = commandOffset + 72 + index * section64Size
            guard let sectionName = view.fixedString(at: base, length: 16) else {
                return nil
            }
            // The section's segment name is the enclosing segment's name.
            segmentNames.append(segmentName)
            sectionNames.append(sectionName)
        }

        return ParsedSegment64(
            segmentNames: segmentNames,
            sectionNames: sectionNames,
            isText: segmentName == "__TEXT" || segmentName == "__TEXT_EXEC",
            vmaddr: vmaddr,
            vmsize: vmsize)
    }

    /// Read `nlist_64` entries whose section belongs to `__TEXT`/`__TEXT_EXEC`.
    static func parseSymbols(
        _ view: MachOView,
        sliceOffset: Int,
        sliceSize: Int,
        table: (symoff: UInt32, nsyms: UInt32, stroff: UInt32, strsize: UInt32),
        sectionSegments: [String],
        sectionNames: [String],
        textEnd: UInt64) -> [DSYMSymbol]? {
        let symbolOffset = Int(table.symoff)
        let symbolCount = Int(table.nsyms)
        let stringOffset = Int(table.stroff)
        let stringSize = Int(table.strsize)

        guard symbolCount > 0, stringSize > 0,
              symbolCount <= Int.max / nlist64Size,
              symbolOffset <= sliceSize,
              stringOffset <= sliceSize else {
            return nil
        }

        let symbolBytes = symbolCount * nlist64Size
        guard symbolBytes <= sliceSize - symbolOffset,
              stringSize <= sliceSize - stringOffset else {
            return nil
        }

        let symbolBase = sliceOffset + symbolOffset
        let stringBase = sliceOffset + stringOffset
        let stringEnd = stringBase + stringSize
        guard stringEnd <= sliceOffset + sliceSize else { return nil }

        var raw: [(start: UInt64, name: String)] = []
        raw.reserveCapacity(min(symbolCount, 200_000))

        for index in 0..<symbolCount {
            let base = symbolBase + index * nlist64Size
            guard let stringIndex = view.uint32LE(at: base),
                  let type = view.uint8(at: base + 4),
                  let section = view.uint8(at: base + 5),
                  let value = view.uint64LE(at: base + 8) else {
                continue
            }

            // N_SECT only; N_STAB entries are debugging records, not symbols.
            guard (type & nStabMask) == 0,
                  (type & nTypeMask) == nSect,
                  section > 0 else {
                continue
            }

            let sectionIndex = Int(section) - 1
            guard sectionIndex < sectionSegments.count,
                  sectionIndex < sectionNames.count else {
                continue
            }

            let segment = sectionSegments[sectionIndex]
            let sectionName = sectionNames[sectionIndex]
            guard segment == "__TEXT" || segment == "__TEXT_EXEC"
                || sectionName == "__TEXT" || sectionName == "__TEXT_EXEC" else {
                continue
            }

            let nameIndex = Int(stringIndex)
            guard nameIndex > 0, nameIndex < stringSize else { continue }
            guard let name = view.cString(at: stringBase + nameIndex, limit: stringEnd),
                  !name.isEmpty else {
                continue
            }

            raw.append((start: value, name: name))
        }

        guard !raw.isEmpty else { return nil }

        // Sort by address; names break ties so the result is deterministic.
        raw.sort { lhs, rhs in
            if lhs.start == rhs.start { return lhs.name < rhs.name }
            return lhs.start < rhs.start
        }

        // Aliases can share an address. Keep one entry per start so `end` is
        // always greater than `start` and binary search is unambiguous.
        var unique: [(start: UInt64, name: String)] = []
        unique.reserveCapacity(raw.count)
        for item in raw {
            if let last = unique.last, last.start == item.start { continue }
            unique.append(item)
        }

        var symbols: [DSYMSymbol] = []
        symbols.reserveCapacity(unique.count)

        for index in 0..<unique.count {
            let item = unique[index]
            let end: UInt64

            if index + 1 < unique.count {
                end = unique[index + 1].start
            } else if textEnd > item.start {
                end = textEnd
            } else {
                end = item.start == UInt64.max ? UInt64.max : item.start + 1
            }

            symbols.append(DSYMSymbol(start: item.start, end: end, name: item.name))
        }

        return symbols
    }

    static func architectureRank(cpuType: UInt32, cpuSubtype: UInt32) -> Int {
        if cpuType == cpuTypeARM64 {
            // CPU_SUBTYPE_ARM64E == 2; the high bits carry the ABI variant.
            return (cpuSubtype & 0x00ff_ffff) == 2 ? 3 : 2
        }
        if cpuType == cpuTypeARM64_32 { return 1 }
        return 0
    }

    static func uuidString(_ view: MachOView, at offset: Int) -> String? {
        guard view.contains(offset, 16) else { return nil }

        var bytes: [UInt8] = []
        bytes.reserveCapacity(16)
        for index in 0..<16 {
            guard let byte = view.uint8(at: offset + index) else { return nil }
            bytes.append(byte)
        }

        let hex = bytes.map { String(format: "%02X", Int($0)) }.joined()
        guard hex.count == 32 else { return nil }

        let first = String(hex.prefix(8))
        let second = String(hex.dropFirst(8).prefix(4))
        let third = String(hex.dropFirst(12).prefix(4))
        let fourth = String(hex.dropFirst(16).prefix(4))
        let fifth = String(hex.dropFirst(20).prefix(12))
        return "\(first)-\(second)-\(third)-\(fourth)-\(fifth)"
    }
}

// MARK: - Crash report integration

enum DSYMSymbolicator {
    /// Returns a copy of `report` whose matching, still-empty frames carry a
    /// dSYM symbol. Frames whose UUID differs, or that already have a symbol,
    /// are copied through untouched.
    static func symbolicate(_ report: CrashIPSReport, store: DSYMStore) -> CrashIPSReport {
        var result = report
        var frames: [CrashIPSFrame] = []
        frames.reserveCapacity(report.frames.count)

        for frame in report.frames {
            frames.append(symbolicated(frame, store: store))
        }

        result.frames = frames
        return result
    }

    private static func symbolicated(_ frame: CrashIPSFrame, store: DSYMStore) -> CrashIPSFrame {
        // UUID mismatch means this dSYM is from another build: never guess.
        guard store.matches(uuid: frame.imageUUID) else { return frame }

        // Only fill empty symbols; an existing symbol (or inline symbol) wins.
        if let symbol = frame.symbol, !symbol.isEmpty { return frame }

        var name = store.symbol(at: frame.imageOffset)

        // Some dSYMs store linked vmaddrs (for example 0x100000000) instead
        // of image-relative offsets. Try the __TEXT vmaddr only if the direct
        // lookup failed, so the common image-relative case stays simple.
        if name == nil, store.textVMAddress > 0 {
            let (address, overflow) = store.textVMAddress.addingReportingOverflow(frame.imageOffset)
            if !overflow {
                name = store.symbol(at: address)
            }
        }

        guard let resolved = name, !resolved.isEmpty else { return frame }

        var updated = frame
        updated.symbol = resolved
        return updated
    }
}