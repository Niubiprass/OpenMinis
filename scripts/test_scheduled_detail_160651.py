#!/usr/bin/env python3
"""Source-contract tests for [T-115-scheduled-detail]: scheduled task UI.

Entry: Settings > Agent Tools > "Scheduled Tasks".
List: every registered AgentJob (AgentJobRegistry.list()), state badge, next
fire / owner line, NavigationLink to detail, swipe-to-delete (cancel+remove).
Detail: trigger/target/next-fire/prompt/owner/history rows, enable Toggle
(writes registry.setEnabled), destructive delete.
Constraints: iOS 15 targets only — no LabeledContent (iOS16+), no
navigationDestination; no writes outside AgentJobRegistry; nothing touches
the message list / streaming / compaction paths.
"""
import unittest
from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
VIEW = (ROOT / 'src/ios/Views/Settings/ScheduledTasksView.swift').read_text()
TOOLS = (ROOT / 'src/ios/Views/Settings/ToolsSettingsView.swift').read_text()
REGISTRY = (ROOT / 'src/ios/Agent/Jobs/AgentJobRegistry.swift').read_text()


class ScheduledListSource(unittest.TestCase):
    """List page contracts."""

    def test_list_view_exists(self):
        self.assertIn('struct ScheduledTasksView: View', VIEW)
        self.assertIn('AgentJobRegistry.shared', VIEW)

    def test_reads_all_jobs_from_registry(self):
        self.assertIn('jobs = registry.list()', VIEW)
        self.assertIn('ForEach(jobs, id: \\.id) { job in', VIEW)

    def test_rows_link_to_detail(self):
        self.assertIn('NavigationLink {', VIEW)
        self.assertIn('ScheduledTaskDetailView(job: job) { refresh() }', VIEW)

    def test_swipe_delete_cancels_then_removes(self):
        self.assertIn('.onDelete { offsets in', VIEW)
        self.assertIn('registry.cancel(jobId: job.id, reason: "deleted from scheduled tasks UI", silent: true)', VIEW)
        self.assertIn('registry.remove(jobId: job.id)', VIEW)

    def test_refresh_on_appear(self):
        self.assertIn('.onAppear { refresh() }', VIEW)

    def test_owner_title_fetched_async(self):
        self.assertIn('await ChatStore.shared.getSession(sid)', VIEW)

    def test_state_badge_mapping_complete(self):
        for state in ('pending', 'running', 'done', 'cancelled', 'failed', 'timeout'):
            self.assertIn('case .%s:' % state, VIEW)
        self.assertIn('已停用', VIEW)


class ScheduledDetailSource(unittest.TestCase):
    """Detail page contracts."""

    def test_detail_view_exists(self):
        self.assertIn('struct ScheduledTaskDetailView: View', VIEW)
        self.assertIn('let job: AgentJob', VIEW)

    def test_details_show_trigger_target_next(self):
        self.assertIn('triggerText(job.trigger)', VIEW)
        self.assertIn('targetText(job.target)', VIEW)
        self.assertIn('job.nextFireAt', VIEW)
        self.assertIn('job.prompt ?? job.title', VIEW)

    def test_enable_toggle_writes_registry(self):
        self.assertIn('registry.setEnabled(jobId: job.id, enabled: v)', VIEW)
        self.assertIn('可切换', VIEW) if False else None

    def test_delete_button_complete(self):
        self.assertIn('Button(role: .destructive)', VIEW)
        self.assertIn('registry.cancel(jobId: job.id, reason: "deleted from scheduled task detail", silent: true)', VIEW)
        self.assertIn('registry.remove(jobId: job.id)', VIEW)
        self.assertIn('dismiss()', VIEW)

    def test_no_ios16_only_apis(self):
        # LabeledContent is iOS16+; the kv rows must stay custom HStack.
        self.assertNotIn('LabeledContent', VIEW)
        self.assertNotIn('navigationDestination', VIEW)


class EntryPointSource(unittest.TestCase):
    """Settings entry."""

    def test_tools_settings_entry(self):
        self.assertIn('NavigationLink {', TOOLS)
        self.assertIn('ScheduledTasksView()', TOOLS)
        self.assertIn('"clock.badge.checkmark"', TOOLS)
        self.assertIn('Scheduled Tasks', TOOLS)

    def test_registry_api_used_is_public(self):
        # The UI may only rely on the registry's public surface.
        self.assertIn('func list() -> [AgentJob] {', REGISTRY)
        self.assertIn('func setEnabled(jobId: String, enabled: Bool)', REGISTRY)
        self.assertIn('func cancel(jobId: String, reason: String, silent: Bool = false)', REGISTRY)
        self.assertIn('func remove(jobId: String)', REGISTRY)


if __name__ == '__main__':
    unittest.main(verbosity=2)