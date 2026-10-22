#!/usr/bin/env python3
"""Source contracts for direct session/group persona entries."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHAT = (ROOT / "src/ios/Views/Chat/AIChatView.swift").read_text(encoding="utf-8")
SKILLS = (ROOT / "src/ios/Views/Chat/SessionSkillsView.swift").read_text(encoding="utf-8")
CONTENT = (ROOT / "src/ios/Views/ContentView.swift").read_text(encoding="utf-8")


class PersonaEntry(unittest.TestCase):
    def test_session_persona_is_a_first_level_menu_item(self):
        self.assertIn("onPersona", CHAT)
        self.assertIn('Label(AppLocalized("会话人格"), systemImage: "person.crop.circle")', CHAT)
        self.assertIn("showSessionPersona = true", CHAT)
        self.assertIn("PersonaPickerSheet(sessionId: vm.sessionId", CHAT)

    def test_picker_is_internal_for_reuse(self):
        self.assertIn("struct PersonaPickerSheet: View", SKILLS)
        self.assertNotIn("private struct PersonaPickerSheet", SKILLS)

    def test_group_persona_stays_inside_group_config(self):
        # User asked not to move/rename this entry; it remains one item inside
        # the long-press group configuration sheet.
        self.assertIn('Label("分组配置（本机候选）", systemImage: "slider.horizontal.3")', CONTENT)
        self.assertIn("private var personaSection", CONTENT)


if __name__ == "__main__":
    print("SOURCE CONTRACTS ONLY: persona entries; no Swift/device verdict.", flush=True)
    unittest.main(verbosity=2)
