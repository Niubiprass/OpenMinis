import Foundation

struct FixtureFailure: Error, CustomStringConvertible {
    let description: String
}
var assertions = 0
func check(_ condition: @autoclosure () -> Bool, _ label: String) throws {
    guard condition() else { throw FixtureFailure(description: label) }
    assertions += 1
}
func rejects(_ label: String, _ expected: MiniSightWakeName.ValidationError? = nil,
             _ body: () throws -> Void) throws {
    var received: MiniSightWakeName.ValidationError?
    do { try body() } catch let error as MiniSightWakeName.ValidationError { received = error }
    guard let error = received else { throw FixtureFailure(description: "accepted: " + label) }
    if let expected = expected { try check(error == expected, "wrong error: " + label) }
    try check(error.errorDescription?.isEmpty == false, "visible error: " + label)
}
func success(_ name: String, _ reading: String = "", _ visible: String,
             _ tokens: [String], _ vocabulary: Set<String>) throws -> MiniSightWakeName.Prepared {
    let value = try MiniSightWakeName.prepare(name: name, pronunciation: reading, vocabulary: vocabulary)
    let expected = MiniSightWakeName.Prepared(name: name, pronunciation: visible, tokens: tokens,
                                             definition: tokens.joined(separator: " ") + " @minisight")
    try check(value == expected, "prepared mismatch: " + name + " / " + reading)
    try check(value.tokens.allSatisfy({ vocabulary.contains($0) }), "OOV: " + name)
    try check(value.definition.components(separatedBy: "@").count == 2, "extra keyword tag")
    return value
}

func runFixtures(_ directory: String) throws {
    let data = try Data(contentsOf: URL(fileURLWithPath: directory).appendingPathComponent("tokens.txt"))
    let vocabulary = try MiniSightWakeName.vocabulary(from: data)
    try check(vocabulary.count == 227, "actual model token count")
    try check(vocabulary.contains("<blk>") && vocabulary.contains("#29") && vocabulary.contains("○"),
              "actual model special symbols")

    _ = try success("小鱼", "", "xiǎo yú", ["x", "iǎo", "y", "ú"], vocabulary)
    _ = try success("小肥鱼", "", "xiǎo féi yú", ["x", "iǎo", "f", "éi", "y", "ú"], vocabulary)
    _ = try success("小鱼", "XIAO3 YU2", "xiǎo yú", ["x", "iǎo", "y", "ú"], vocabulary)
    _ = try success("小重", "xiao3 chong2", "xiǎo chóng", ["x", "iǎo", "ch", "óng"], vocabulary)
    _ = try success("重行", "zhong4 xing2", "zhòng xíng", ["zh", "òng", "x", "íng"], vocabulary)
    _ = try success("重行", "chóng háng", "chóng háng", ["ch", "óng", "h", "áng"], vocabulary)
    _ = try success("小行", "xiao3 hang2", "xiǎo háng", ["x", "iǎo", "h", "áng"], vocabulary)
    for name in ["小重", "小行", "重行", "小绿", "小乐", "小好", "小龘", "小\u{20000}"] {
        try rejects("review required " + name, .pronunciationRequired) {
            _ = try MiniSightWakeName.prepare(name: name, vocabulary: vocabulary)
        }
    }
    _ = try success("小吕", "xiao3 lv3", "xiǎo lǚ", ["x", "iǎo", "l", "ǚ"], vocabulary)
    _ = try success("小女", "xiao3 nü3", "xiǎo nǚ", ["x", "iǎo", "n", "ǚ"], vocabulary)
    _ = try success("小绿", "xiao3 lü4", "xiǎo lǜ", ["x", "iǎo", "l", "ǜ"], vocabulary)
    _ = try success("小略", "xiao3 lve4", "xiǎo lüè", ["x", "iǎo", "l", "üè"], vocabulary)
    _ = try success("小居", "xiao3 jü1", "xiǎo jū", ["x", "iǎo", "j", "ū"], vocabulary)
    _ = try success("小居", "xiao3 jv1", "xiǎo jū", ["x", "iǎo", "j", "ū"], vocabulary)
    _ = try success("小球", "xiao3 qiu2", "xiǎo qiú", ["x", "iǎo", "q", "iú"], vocabulary)
    _ = try success("小会", "xiao3 hui4", "xiǎo huì", ["x", "iǎo", "h", "uì"], vocabulary)
    _ = try success("小爱", "xiao3 ai4", "xiǎo ài", ["x", "iǎo", "ài"], vocabulary)
    _ = try success("小东", "xiao3 dong1", "xiǎo dōng", ["x", "iǎo", "d", "ōng"], vocabulary)
    _ = try success("小的", "xiao3 de5", "xiǎo de", ["x", "iǎo", "d", "e"], vocabulary)
    _ = try success("小的", "xiao3 de0", "xiǎo de", ["x", "iǎo", "d", "e"], vocabulary)
    _ = try success("小龘", "xiao3 da2", "xiǎo dá", ["x", "iǎo", "d", "á"], vocabulary)
    let longTokens = ["x", "iǎo", "f", "éi"] + Array(repeating: ["y", "ú"], count: 6).flatMap { $0 }
    _ = try success("小肥鱼鱼鱼鱼鱼鱼", "", "xiǎo féi yú yú yú yú yú yú", longTokens, vocabulary)

    let composed = try MiniSightWakeName.prepare(name: "小鱼", pronunciation: "xiǎo yú", vocabulary: vocabulary)
    let decomposed = try MiniSightWakeName.prepare(name: "小鱼", pronunciation: "xia\u{030C}o yu\u{0301}", vocabulary: vocabulary)
    try check(composed == decomposed, "NFC pinyin equivalence")
    let umlaut = try MiniSightWakeName.prepare(name: "小吕", pronunciation: "xiǎo lǚ", vocabulary: vocabulary)
    let decomposedUmlaut = try MiniSightWakeName.prepare(name: "小吕", pronunciation: "xiǎo lu\u{0308}\u{030C}", vocabulary: vocabulary)
    try check(umlaut == decomposedUmlaut, "NFC umlaut equivalence")

    for name in ["", "鱼", "小鱼鱼鱼鱼鱼鱼鱼鱼", "小A", "小1", "小🐟", " 小鱼", "小鱼 ",
                 "小#", "小/", "小:", "小@", "小鱼\n", "小鱼\r", "小鱼\t", "小鱼\u{0000}",
                 "小鱼\u{200B}", "小鱼\u{202E}", "小鱼\u{FE0F}", "小鱼\u{00A0}"] {
        try rejects("name " + name, .invalidName) {
            _ = try MiniSightWakeName.prepare(name: name, vocabulary: vocabulary)
        }
    }
    for reading in [" ", "xiǎo yú\n", "xiǎo yú\r", "xiǎo\tyú", "xiǎo yú\u{0000}",
                    "xiǎo yú\u{200B}", "xiǎo yú @evil", "xiǎo yú #evil", "xiǎo yú:1",
                    "xiǎo yú /evil", "xiǎo 'yú'", "xiao6 yu2", "xiao9 yu2", "xiǎo3 yú",
                    "xǐao yú", "xiáǒ yú", "foo1 bar2", "xiao3yu2", "xiao3 yu2 extra",
                    "xiao3 u:2", String(repeating: "x", count: 257)] {
        try rejects("reading " + reading) {
            _ = try MiniSightWakeName.prepare(name: "小鱼", pronunciation: reading, vocabulary: vocabulary)
        }
    }
    try rejects("one syllable", .syllableCountMismatch(expected: 2, actual: 1)) {
        _ = try MiniSightWakeName.prepare(name: "小鱼", pronunciation: "xiao3", vocabulary: vocabulary)
    }
    try rejects("three syllables", .syllableCountMismatch(expected: 2, actual: 3)) {
        _ = try MiniSightWakeName.prepare(name: "小鱼", pronunciation: "xiao3 yu2 yu2", vocabulary: vocabulary)
    }
    try rejects("empty vocabulary", .invalidVocabulary) {
        _ = try MiniSightWakeName.prepare(name: "小鱼", vocabulary: [])
    }
    for missing in ["x", "iǎo", "y", "ú"] {
        try rejects("missing " + missing, .missingToken(missing)) {
            _ = try MiniSightWakeName.prepare(name: "小鱼", vocabulary: vocabulary.subtracting([missing]))
        }
    }
    try rejects("no full syllable fallback", .missingToken("x")) {
        _ = try MiniSightWakeName.prepare(name: "小鱼", pronunciation: "xiǎo yú", vocabulary: ["xiǎo", "yú"])
    }
    try rejects("no toneless fallback", .missingToken("iǎo")) {
        _ = try MiniSightWakeName.prepare(name: "小鱼", pronunciation: "xiao3 yu2", vocabulary: ["x", "iao", "y", "u"])
    }

    for bad in ["", "x", "x 0\nx 1\n", "x 0\ny 0\n", "x -1\n", "x 1\n", "x 0\ny 2\n",
                "x 0 extra\n", "x 0\n\ny 1\n", "x 0.0\n", "x 1e0\n", "x 2147483648\n",
                "x\u{0000} 0\n", "x\u{00A0}y 0\n", "ǚ 0\nu\u{0308}\u{030C} 1\n"] {
        try rejects("tokens format " + bad, .invalidVocabulary) {
            _ = try MiniSightWakeName.vocabulary(from: Data(bad.utf8))
        }
    }
    try rejects("invalid UTF-8", .invalidVocabulary) {
        _ = try MiniSightWakeName.vocabulary(from: Data([0xFF, 0xFE]))
    }
    try rejects("32KiB bound", .invalidVocabulary) {
        _ = try MiniSightWakeName.vocabulary(from: Data(repeating: 0x61, count: 32769))
    }
    let text = String(decoding: data, as: UTF8.self)
    let crlf = try MiniSightWakeName.vocabulary(from: Data(text.replacingOccurrences(of: "\n", with: "\r\n").utf8))
    try check(crlf == vocabulary, "CRLF model vocabulary")
    let noTrailingNewline = try MiniSightWakeName.vocabulary(from: Data(text.dropLast().utf8))
    try check(noTrailingNewline == vocabulary, "optional final newline")
    let normalizedVocabulary = try MiniSightWakeName.vocabulary(from: Data("u\u{0308}\u{030C} 0\n".utf8))
    try check(normalizedVocabulary == Set(["ǚ"]), "NFC vocabulary symbol")
    print("PASS native Swift behavior: \(assertions) assertions; actual model vocabulary")
}

do {
    guard CommandLine.arguments.count == 2 else {
        throw FixtureFailure(description: "expected fixture directory")
    }
    try runFixtures(CommandLine.arguments[1])
} catch {
    fputs("FAIL native Swift behavior: \(error)\n", stderr)
    exit(1)
}
