import Foundation

/// Offline WenetSpeech ppinyin (strict=false) preparation; no I/O or audio side effects.
/// Display Prepared.pronunciation for human review. A spelling/count check is not
/// proof that a reading is the intended reading of every Chinese character.
enum MiniSightWakeName {
    struct Prepared: Equatable {
        let name: String
        let pronunciation: String
        let tokens: [String]
        let definition: String
    }

    enum ValidationError: Error, Equatable, LocalizedError {
        case invalidName
        case invalidVocabulary
        case invalidPronunciation
        case pronunciationRequired
        case syllableCountMismatch(expected: Int, actual: Int)
        case missingToken(String)

        var errorDescription: String? {
            switch self {
            case .invalidName: return "名字须为 2–8 个汉字，不能含空格、标点或控制字符。"
            case .invalidVocabulary: return "本地模型词表无效或缺失。"
            case .invalidPronunciation: return "请填写逐字拼音，如 xiao3 yu2 或 xiǎo yú；不支持标点及控制字符。"
            case .pronunciationRequired: return "该名字需校读，请逐字填写并确认拼音。"
            case let .syllableCountMismatch(expected, actual):
                return "名字有 \(expected) 个汉字，但读音有 \(actual) 个音节。"
            case let .missingToken(token): return "模型不支持拼音 token：\(token)，请校读或换名。"
            }
        }
    }

    /// Strict tokens.txt reader: UTF-8, <=32 KiB, two columns, unique symbols/IDs,
    /// nonnegative contiguous IDs starting at zero. No whitespace/control in symbols.
    static func vocabulary(from data: Data) throws -> Set<String> {
        guard !data.isEmpty, data.count <= 32 * 1024,
              let text = String(data: data, encoding: .utf8) else {
            throw ValidationError.invalidVocabulary
        }
        var rows = text.components(separatedBy: "\n")
        if rows.last == "" { rows.removeLast() }
        var symbols = Set<String>()
        var ids = Set<Int>()
        for var row in rows {
            if row.hasSuffix("\r") { row.removeLast() }
            let columns = row.split(whereSeparator: { $0 == " " || $0 == "\t" })
            guard columns.count == 2 else { throw ValidationError.invalidVocabulary }
            let symbol = String(columns[0]).precomposedStringWithCanonicalMapping
            let idText = columns[1]
            guard !symbol.isEmpty, symbol.utf8.count <= 64,
                  symbol.unicodeScalars.allSatisfy({
                      !CharacterSet.whitespacesAndNewlines.contains($0) &&
                      !CharacterSet.controlCharacters.contains($0) &&
                      !CharacterSet.illegalCharacters.contains($0)
                  }),
                  idText.utf8.allSatisfy({ (48...57).contains($0) }),
                  let id = Int(idText), id <= Int(Int32.max),
                  symbols.insert(symbol).inserted, ids.insert(id).inserted else {
                throw ValidationError.invalidVocabulary
            }
        }
        guard !symbols.isEmpty, ids == Set(0..<symbols.count) else {
            throw ValidationError.invalidVocabulary
        }
        return symbols
    }

    static func prepare(name: String, pronunciation: String = "",
                        vocabulary: Set<String>) throws -> Prepared {
        guard name.utf8.count <= 128 else { throw ValidationError.invalidName }
        let normalizedName = name.precomposedStringWithCanonicalMapping
        let count = normalizedName.unicodeScalars.count
        guard (2...8).contains(count), normalizedName.count == count,
              normalizedName.unicodeScalars.allSatisfy({ isHan($0.value) }) else {
            throw ValidationError.invalidName
        }
        guard !vocabulary.isEmpty else { throw ValidationError.invalidVocabulary }
        guard pronunciation.utf8.count <= 256 else {
            throw ValidationError.invalidPronunciation
        }
        let reading: String
        if pronunciation.isEmpty {
            // Auto mode is deliberately limited to reviewed common characters.
            // A deny-list alone cannot safely cover all polyphonic/rare characters.
            guard normalizedName.allSatisfy({ automaticCharacters.contains($0) }),
                  let latin = normalizedName.applyingTransform(.toLatin, reverse: false) else {
                throw ValidationError.pronunciationRequired
            }
            reading = latin
        } else {
            reading = pronunciation
        }
        let input = reading.precomposedStringWithCanonicalMapping.lowercased()
        guard !input.isEmpty, input.unicodeScalars.allSatisfy({
            readingAlphabet.unicodeScalars.contains($0)
        }) else { throw ValidationError.invalidPronunciation }
        let syllables = input.split(separator: " ", omittingEmptySubsequences: true)
        guard syllables.count == count else {
            throw ValidationError.syllableCountMismatch(expected: count, actual: syllables.count)
        }
        var visible = [String]()
        var tokens = [String]()
        for syllable in syllables {
            let (canonical, parts) = try parseSyllable(String(syllable))
            for token in parts {
                guard vocabulary.contains(token) else { throw ValidationError.missingToken(token) }
            }
            visible.append(canonical)
            tokens.append(contentsOf: parts)
        }
        return Prepared(name: normalizedName, pronunciation: visible.joined(separator: " "),
                        tokens: tokens, definition: tokens.joined(separator: " ") + " @minisight")
    }

    private static func isHan(_ value: UInt32) -> Bool {
        // Unified ideographs only: no compatibility glyphs, selectors, or punctuation.
        return (0x3400...0x4DBF).contains(value) || (0x4E00...0x9FFF).contains(value) ||
            (0x20000...0x2A6DF).contains(value) || (0x2A700...0x2B73F).contains(value) ||
            (0x2B740...0x2B81F).contains(value) || (0x2B820...0x2CEAF).contains(value) ||
            (0x2CEB0...0x2EBEF).contains(value) || (0x30000...0x323AF).contains(value)
    }

    // Modern common readings only; unlisted characters require explicit user input.
    // This is a review gate, NOT a Chinese-to-pinyin replacement dictionary.
    private static let automaticCharacters = Set("小鱼魚肥猫貓狗兔米豆花桃星雪冬夏秋春海林晨辰欣鑫宇羽嘉佳婷鹏鵬敏梦夢玲秀英君梅丹晓曉皓昊璐心光田山江泉阳陽洋月圆圓萱薇彤琦琪珂菁静靜婧怡恩甜明安萌宝寶贝貝")
    private static let readingAlphabet = "abcdefghijklmnopqrstuvwxyzüāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ012345 "
    private static let accents: [Character: [Character]] = [
        "a": Array("āáǎà"), "e": Array("ēéěè"), "i": Array("īíǐì"),
        "o": Array("ōóǒò"), "u": Array("ūúǔù"), "ü": Array("ǖǘǚǜ")
    ]

    private static func parseSyllable(_ input: String) throws -> (String, [String]) {
        var body = input.replacingOccurrences(of: "v", with: "ü")
        var number: Int?
        if let last = body.last, "012345".contains(last), let value = last.wholeNumberValue {
            number = value == 5 ? 0 : value
            body.removeLast()
        }
        guard !body.isEmpty else { throw ValidationError.invalidPronunciation }
        var plain = ""
        var markedTone: Int?
        for character in body {
            var base = character
            for (vowel, marks) in accents {
                if let index = marks.firstIndex(of: character) {
                    guard markedTone == nil, number == nil else {
                        throw ValidationError.invalidPronunciation
                    }
                    markedTone = index + 1
                    base = vowel
                }
            }
            guard "abcdefghijklmnopqrstuvwxyzü".contains(base) else {
                throw ValidationError.invalidPronunciation
            }
            plain.append(base)
        }
        let tone = number ?? markedTone ?? 0
        // Reject misplaced accents instead of silently changing the visible reading.
        if markedTone != nil, try applyTone(plain, tone: tone) != body {
            throw ValidationError.invalidPronunciation
        }
        let initial: String
        if plain.hasPrefix("zh") || plain.hasPrefix("ch") || plain.hasPrefix("sh") {
            initial = String(plain.prefix(2))
        } else if let first = plain.first, finals[String(first)] != nil {
            initial = String(first)
        } else {
            initial = ""
        }
        var final = String(plain.dropFirst(initial.count))
        // pypinyin strict=false uses written u after j/q/x/y, but ü after n/l.
        if ["j", "q", "x", "y"].contains(initial), final.hasPrefix("ü") {
            final = "u" + String(final.dropFirst())
        }
        guard let allowed = finals[initial], allowed.split(separator: " ").contains(Substring(final)) else {
            throw ValidationError.invalidPronunciation
        }
        let canonical = try applyTone(initial + final, tone: tone)
        let finalToken = String(canonical.dropFirst(initial.count))
        return (canonical, initial.isEmpty ? [finalToken] : [initial, finalToken])
    }

    private static func applyTone(_ plain: String, tone: Int) throws -> String {
        guard (0...4).contains(tone) else { throw ValidationError.invalidPronunciation }
        if tone == 0 { return plain }
        var letters = Array(plain)
        let index = letters.firstIndex(of: "a") ?? letters.firstIndex(of: "e") ??
            (plain.contains("ou") ? letters.firstIndex(of: "o") : nil) ??
            letters.lastIndex(where: { accents[$0] != nil })
        guard let position = index, let marks = accents[letters[position]] else {
            throw ValidationError.invalidPronunciation
        }
        letters[position] = marks[tone - 1]
        return String(letters).precomposedStringWithCanonicalMapping
    }

    // Legal written Mandarin syllables, not vocabulary-driven greedy segmentation.
    // Actual model tokens must contain BOTH the deterministic initial and toned final.
    private static let finals: [String: String] = [
        "": "a ai an ang ao e ei en eng er o ou",
        "b": "a ai an ang ao ei en eng i ian iao ie in ing o u",
        "p": "a ai an ang ao ei en eng i ian iao ie in ing o ou u",
        "m": "a ai an ang ao e ei en eng i ian iao ie in ing iu o ou u",
        "f": "a an ang ei en eng o ou u",
        "d": "a ai an ang ao e ei en eng i ia ian iao ie ing iu ong ou u uan ui un uo",
        "t": "a ai an ang ao e eng i ian iao ie ing ong ou u uan ui un uo",
        "n": "a ai an ang ao e ei en eng i ian iang iao ie in ing iu ong ou u uan un uo ü üe",
        "l": "a ai an ang ao e ei eng i ia ian iang iao ie in ing iu o ong ou u uan un uo ü üe",
        "g": "a ai an ang ao e ei en eng ong ou u ua uai uan uang ui un uo",
        "k": "a ai an ang ao e ei en eng ong ou u ua uai uan uang ui un uo",
        "h": "a ai an ang ao e ei en eng ong ou u ua uai uan uang ui un uo",
        "j": "i ia ian iang iao ie in ing iong iu u uan ue un",
        "q": "i ia ian iang iao ie in ing iong iu u uan ue un",
        "x": "i ia ian iang iao ie in ing iong iu u uan ue un",
        "zh": "a ai an ang ao e ei en eng i ong ou u ua uai uan uang ui un uo",
        "ch": "a ai an ang ao e en eng i ong ou u ua uai uan uang ui un uo",
        "sh": "a ai an ang ao e ei en eng i ou u ua uai uan uang ui un uo",
        "r": "an ang ao e en eng i ong ou u ua uan ui un uo",
        "z": "a ai an ang ao e ei en eng i ong ou u uan ui un uo",
        "c": "a ai an ang ao e en eng i ong ou u uan ui un uo",
        "s": "a ai an ang ao e en eng i ong ou u uan ui un uo",
        "y": "a an ang ao e i in ing o ong ou u uan ue un",
        "w": "a ai an ang ei en eng o u"
    ]
}
