#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[T-persona-library] Persona library data + Soul page entry.

Phase 1 only: saved personas and the list/editor UI. Session/folder assignment
and persona-memory injection are wired separately so the existing single-SOUL
path is not touched until they are tested.
"""
import unittest
from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
STORE = (ROOT / 'src/ios/Agent/Session/SoulStore.swift').read_text()
VIEW = (ROOT / 'src/ios/Views/Settings/SoulSettingsView.swift').read_text()


class Store(unittest.TestCase):
    def test_persona_model(self):
        for key in ('struct AgentPersona', 'var id: String', 'var name: String',
                    'var style: String', 'var lang: String', 'var body: String',
                    'var createdAt: Date', 'var updatedAt: Date'):
            self.assertIn(key, STORE)

    def test_persona_store_crud(self):
        self.assertIn('final class PersonaStore: ObservableObject', STORE)
        self.assertIn('persona.library.v1', STORE)
        for fn in ('func add(name:', 'func update(_ persona: AgentPersona)',
                   'func delete(id: String)', 'func persona(id: String?)'):
            self.assertIn(fn, STORE)

    def test_store_does_not_touch_soul_md(self):
        i = STORE.index('struct AgentPersona')
        body = STORE[i:]
        self.assertNotIn('SoulStore.save', body)


class UI(unittest.TestCase):
    def test_soul_page_has_persona_entry(self):
        self.assertIn('PersonaListView()', VIEW)
        self.assertIn('人格列表', VIEW)
        self.assertIn('新建会话默认空白', VIEW)

    def test_list_and_editor_exist(self):
        for name in ('struct PersonaListView', 'struct PersonaEditorView'):
            self.assertIn(name, VIEW)
        self.assertIn('onDelete', VIEW)
        self.assertIn('SoulStore.isOverLimit(bodyText)', VIEW)
        self.assertIn('AppLocalized("保存")', VIEW)
        self.assertIn('exportPersonas()', VIEW)
        self.assertIn('JSONEncoder()', VIEW)

    def test_no_new_top_level_navigation(self):
        # Phase 1 adds a row inside the existing Soul Form, not a new tab/sheet.
        self.assertIn('NavigationLink {\n                    PersonaListView()', VIEW)




class Assignment(unittest.TestCase):
    def test_session_persona_key_and_picker(self):
        view = (ROOT / 'src/ios/Views/Chat/SessionSkillsView.swift').read_text()
        self.assertIn('struct PersonaPickerSheet', view)
        self.assertIn('session.persona.id.', view)
        self.assertIn('会话人格', view)
        self.assertIn('无（空白）', view)
        self.assertIn('跟随分组', view)

    def test_runtime_resolves_session_then_folder(self):
        vm = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel+MemoryTools.swift').read_text()
        i = vm.index('var effectiveSoulPrompt')
        j = vm.index('var folderMemoryStatusFragment', i)
        body = vm[i:j]
        self.assertIn('session.persona.id.', body)
        self.assertIn('configuration.personaId', body)
        self.assertLess(body.index('session.persona.id.'), body.index('configuration.personaId'))

    def test_folder_config_has_persona_id(self):
        store = (ROOT / 'src/ios/Agent/Chat/ChatStore.swift').read_text()
        self.assertIn('var personaId: String?', store)
        self.assertIn('forKey: .personaId', store)
        cv = (ROOT / 'src/ios/Views/ContentView.swift').read_text()
        self.assertIn('分组人格', cv)
        self.assertIn('draft.personaId', cv)





class MemoryLayers(unittest.TestCase):
    def test_blank_default_and_persona_memory(self):
        store = (ROOT / 'src/ios/Agent/Session/SoulStore.swift').read_text()
        self.assertIn('blankByDefault', store)
        self.assertIn('persona.blankDefault', store)
        self.assertIn('func memoryURL(for personaId:', store)
        vm = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel+MemoryTools.swift').read_text()
        self.assertIn('loadPersonaMemoryFragment', vm)
        self.assertIn('personaMemoryURL', vm)
        self.assertIn('PersonaStore.shared.blankByDefault', vm)

    def test_memory_page_has_three_sections(self):
        view = (ROOT / 'src/ios/Views/Settings/MemoryManagementView.swift').read_text()
        for text in ('日记忆', '全局记忆', '人格记忆'):
            self.assertIn(text, view)
        self.assertIn('memoryRoots', view)
        self.assertIn('nameFilter', (ROOT / 'src/ios/Agent/Session/MemoryDocumentStore.swift').read_text())
        self.assertIn('loadFolderMemoryRoots', view)
        self.assertIn('分组记忆', view)
        self.assertIn('memoryPolicy == .folder', view)
        store = (ROOT / 'src/ios/Agent/Session/SoulStore.swift').read_text()
        self.assertIn('MemoryMaintenance', store)
        self.assertIn('记忆已用', store)
        self.assertIn('archive/raw/', store)





class HeaderIdentity(unittest.TestCase):
    def test_message_header_uses_session_persona(self):
        src = (ROOT / 'src/ios/Agent/MessageList/CollectionViewMessageListV3.swift').read_text()
        self.assertIn('personaId: headerPersonaId()', src)
        self.assertIn('func headerPersonaId()', src)
        self.assertIn('func refreshPersona()', src)
        self.assertIn('personaDidChange', src)
        self.assertIn('displayName', src)
        self.assertIn('displayIcon', src)





class SharedMemory(unittest.TestCase):
    def test_shared_store_is_read_only_snapshot(self):
        store = (ROOT / 'src/ios/Agent/Session/SoulStore.swift').read_text()
        self.assertIn('struct SharedMemoryRecord', store)
        self.assertIn('final class SharedMemoryStore', store)
        self.assertIn('func share(source:', store)
        self.assertIn('func copyToTarget(', store)
        self.assertIn('shared.memory.v1', store)

    def test_share_ui_and_copy_action(self):
        soul = (ROOT / 'src/ios/Views/Settings/SoulSettingsView.swift').read_text()
        self.assertIn('struct SharedMemoryListView', soul)
        self.assertIn('struct SharedMemoryDetailView', soul)
        self.assertIn('struct PersonaShareSheet', soul)
        self.assertIn('复制到我的记忆', soul)
        mem = (ROOT / 'src/ios/Views/Chat/SessionMemoryView.swift').read_text()
        self.assertIn('PersonaShareSheet(source: persona', mem)
        self.assertIn('分享给其他人格', mem)
        page = (ROOT / 'src/ios/Views/Settings/MemoryManagementView.swift').read_text()
        self.assertIn('SharedMemoryListView()', page)


if __name__ == '__main__':
    unittest.main(verbosity=2)
