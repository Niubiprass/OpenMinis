// The runner prepends Foundation, minimal model stubs and the actual production enums.
let a1 = ProviderInstance(id: "a1", providerType: .a)
let a2 = ProviderInstance(id: "a2", providerType: .a)
let b1 = ProviderInstance(id: "b1", providerType: .b)
let b2 = ProviderInstance(id: "b2", providerType: .b)
let c1 = ProviderInstance(id: "c1", providerType: .c)
let base = [a1, a2, b1, b2, c1]
var checks = 0
func check(_ input: [ProviderInstance], _ source: [Int], _ destination: Int,
           _ expected: [String]?, _ label: String) {
    let actual = ProviderGroupOrder.reorderedIDs(in: input, from: IndexSet(source), to: destination)
    precondition(actual == expected, "\(label): \(String(describing: actual)) != \(String(describing: expected))")
    checks += 1
}
// Flat positions: A, a1, a2, B, b1, b2, C, c1.
check(base, [0], 4, ["b1", "b2", "a1", "a2", "c1"], "title down into B")
check(base, [0], 8, ["b1", "b2", "c1", "a1", "a2"], "first title to end")
check(base, [6], 0, ["c1", "a1", "a2", "b1", "b2"], "last title to start")
check(base, [0], 3, nil, "title before next title")
check(base, [0, 3], 8, ["c1", "a1", "a2", "b1", "b2"], "multiple titles")
check(base, [1], 8, ["a2", "a1", "b1", "b2", "c1"], "member beyond own group")
check(base, [5], 0, ["a1", "a2", "b2", "b1", "c1"], "member above first title")
check(base, [4], 0, nil, "first member clamped to start")
check(base, [1, 2], 8, nil, "all same-type members retain order")
check(base, [0, 1], 8, nil, "mixed title and member rejected")
check(base, [1, 4], 8, nil, "cross-type members rejected")
check(base, [], 0, nil, "empty selection")
check(base, [8], 0, nil, "source out of bounds")
check(base, [0], -1, nil, "negative destination")
check(base, [0], 9, nil, "destination out of bounds")
check([], [0], 0, nil, "empty data")
check([a1], [0], 2, nil, "single group")
check([a1, a1], [0], 3, nil, "duplicate IDs rejected")
check([a1, b1, a2, b2], [2], 0, ["a2", "b1", "a1", "b2"], "interleaved slots preserved")
check([a1, a2, ProviderInstance(id: "a3", providerType: .a), b1], [1, 3], 4,
      ["a2", "a1", "a3", "b1"], "noncontiguous members keep selection order")
// Exhaust all single-row drops: no loss, no type mutation; member moves cannot
// move other types, and title moves cannot change any group's member sequence.
let flat = ProviderGroupOrder.rows(in: base)
for source in flat.indices {
    for destination in 0...flat.count {
        let ids = ProviderGroupOrder.reorderedIDs(in: base, from: IndexSet(integer: source), to: destination) ?? base.map(\.id)
        precondition(ids.count == base.count && Set(ids) == Set(base.map(\.id)))
        let result = ids.map { id in base.first { $0.id == id }! }
        switch flat[source] {
        case .group:
            for type in ProviderGroupOrder.types(in: base) {
                precondition(result.filter { $0.providerType == type }.map(\.id) == base.filter { $0.providerType == type }.map(\.id))
            }
        case .instance(let moved):
            precondition(ProviderGroupOrder.types(in: result) == ProviderGroupOrder.types(in: base))
            for index in base.indices where base[index].providerType != moved.providerType {
                precondition(ids[index] == base[index].id)
            }
        }
        checks += 1
    }
}
print("PASS: \(checks) production Swift drag checks")
