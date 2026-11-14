// Compiles the actual production policy; no SwiftUI imitation and no network.
var checks = 0
func check(_ ok: @autoclosure () -> Bool, _ label: String) {
    precondition(ok(), label)
    checks += 1
}
let order = ["A", "B", "C", "D"]
let ranges: [ProviderGroupDragRange] = [
    .init(minY: 30, maxY: 150), .init(minY: 170, maxY: 500),
    .init(minY: 520, maxY: 590), .init(minY: 610, maxY: 900)
]
let top = ProviderGroupDragPolicy.destination(at: -100, ranges: ranges, sourceIndex: 2)
check(top == 0, "above first header -> first slot")
check(ProviderGroupDragPolicy.reordered(order, moving: "C", to: top!) == ["C", "A", "B", "D"], "last to first")
let bottom = ProviderGroupDragPolicy.destination(at: 2_000, ranges: ranges, sourceIndex: 0)
check(bottom == 3, "below last card -> last slot")
check(ProviderGroupDragPolicy.reordered(order, moving: "A", to: bottom!) == ["B", "C", "D", "A"], "first to last")
check(ProviderGroupDragPolicy.reordered(order, moving: "A", to: 1) == ["B", "A", "C", "D"], "adjacent down swap")
check(ProviderGroupDragPolicy.reordered(order, moving: "B", to: 0) == ["B", "A", "C", "D"], "adjacent up swap")
check(ProviderGroupDragPolicy.reordered(order, moving: "B", to: 1) == nil, "unchanged -> no save")
check(ProviderGroupDragPolicy.reordered(order, moving: "missing", to: 0) == nil, "missing source")
check(ProviderGroupDragPolicy.reordered(order, moving: "A", to: -1) == nil, "negative slot")
check(ProviderGroupDragPolicy.reordered(order, moving: "A", to: 4) == nil, "slot out of range")
check(ProviderGroupDragPolicy.reordered(["A", "A"], moving: "A", to: 1) == nil, "duplicate IDs")
check(ProviderGroupDragPolicy.destination(at: .nan, ranges: ranges, sourceIndex: 0) == nil, "invalid touch")
check(ProviderGroupDragPolicy.destination(at: 100, ranges: [], sourceIndex: 0) == nil, "empty geometry")
check(ProviderGroupDragPolicy.destination(at: 100, ranges: [.init(minY: 3, maxY: 3)], sourceIndex: 0) == nil, "zero range")
check(ProviderGroupDragPolicy.destination(at: 100, ranges: [.init(minY: 0, maxY: 200), .init(minY: 100, maxY: 300)], sourceIndex: 0) == nil, "overlap rejects geometry")
// Every source and every final destination: preserve all groups exactly once,
// put the moved group in the requested slot and leave the others in order.
for from in order.indices {
    var previous = -1
    for y in stride(from: -100.0, through: 1100.0, by: 5.0) {
        let slot = ProviderGroupDragPolicy.destination(at: y, ranges: ranges, sourceIndex: from)!
        check(slot >= previous, "touching downward never moves destination upward")
        previous = slot
        let result = ProviderGroupDragPolicy.reordered(order, moving: order[from], to: slot) ?? order
        check(result[slot] == order[from], "actual position equals requested final slot")
        check(result.filter { $0 != order[from] } == order.filter { $0 != order[from] }, "other groups keep order")
        check(Set(result) == Set(order) && result.count == order.count, "no lost or duplicate group")
    }
}
let instances = [ProviderInstance(id: "a1", providerType: .a),
                 ProviderInstance(id: "a2", providerType: .a),
                 ProviderInstance(id: "b1", providerType: .b),
                 ProviderInstance(id: "c1", providerType: .c),
                 ProviderInstance(id: "c2", providerType: .c)]
let types = ProviderGroupOrder.types(in: instances)
for source in types {
    for slot in types.indices {
        let moved = ProviderGroupDragPolicy.reordered(types, moving: source, to: slot) ?? types
        let ids = ProviderGroupOrder.instanceIDs(in: instances, orderedTypes: moved)
        check(ids.count == instances.count && Set(ids) == Set(instances.map(\.id)), "all members move with the group")
        for type in types {
            let expected = instances.filter { $0.providerType == type }.map(\.id)
            check(ids.filter { expected.contains($0) } == expected, "every group keeps its internal order")
        }
    }
}
print("PASS: \(checks) production group-drag policy checks")
