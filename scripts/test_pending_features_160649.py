from pathlib import Path
root=Path(__file__).resolve().parents[1]
picker=(root/'src/ios/Views/Providers/UnifiedModelPicker.swift').read_text()
detail=(root/'src/ios/Views/Providers/ModelGroupDetailView.swift').read_text()
key=(root/'src/ios/Views/Providers/MultiKeyManagerView.swift').read_text()
mem=(root/'src/ios/Views/Chat/ScopedMemoryLibraryView.swift').read_text()
assert 'toggleAllEntries(in:' in picker
assert 'selectableEntryIds(in:' in picker
assert 'existing.contains($0.id)' in picker
assert 'showImportGroup' in detail and 'importMembers(from:' in detail
assert 'existing.insert($0).inserted' in detail
assert '.onTapGesture { editingKey = k }' in key
assert 'Label("删除", systemImage: "trash")' in key
assert '.contentShape(Rectangle())' in mem
print('pending feature contracts: PASS')
