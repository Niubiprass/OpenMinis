#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[T-crash-report-groups] Contract tests for grouped crash reports.

The Logs page used to render every crash-*.log as its own row. The reported
device had 15+ files after a day of testing. The new shape is:

    Logs -> one "崩溃报告 N 份" row -> groups by cause -> individual files

Grouping is inspired by Sentry's crash fingerprint / FaST (MIT) trace
alignment, but Minis crash logs are custom text, so the parser is independent.
These tests pin the source contracts; they do not run SwiftUI.
"""
import unittest
from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
SRC = (ROOT / 'src/ios/Views/Settings/LogManagementView.swift').read_text()


class Grouping(unittest.TestCase):
    def test_one_entry_in_logs_page(self):
        # The old per-file ForEach must be gone; one NavigationLink remains.
        self.assertIn('Section("Crash Reports")', SRC)
        self.assertNotIn('ForEach(vm.crashFiles)', SRC)
        self.assertIn('CrashReportGroupsView(groups: vm.crashGroups)', SRC)
        self.assertIn('已按原因合并', SRC)

    def test_grouped_view_and_detail(self):
        for name in ('struct CrashReportGroupsView', 'struct CrashReportGroupDetailView'):
            self.assertIn(name, SRC)
        self.assertIn('按原因分组', SRC)
        self.assertIn('发送最新崩溃到会话', SRC)
        self.assertIn('点一组看具体是哪几次', SRC)
        self.assertNotIn('struct CrashReportAnalysisView', SRC)

    def test_categories_cover_the_reported_crashes(self):
        for text in ('主线程等锁', '消息列表卡顿', '前台被杀', '后台被回收', '启动闪退', '其他崩溃'):
            self.assertIn(text, SRC)
        self.assertIn('providermultikeymanager', SRC.lower())
        self.assertIn('collectionviewmessagelist', SRC.lower())
        self.assertIn('savemainstate', SRC.lower())
        self.assertIn('sigkill', SRC.lower())

    def test_type_wins_for_sigkill(self):
        # A SIGKILL report has no stack of its own; the embedded
        # "Last HangDetector Stacks" may describe an older hang. The type
        # must be checked before the stack so 190122 is not mis-grouped.
        i = SRC.index('static func category(type: String, text: String)')
        j = SRC.index('static func keyFrames', i)
        body = SRC[i:j]
        self.assertLess(body.index('sigkill'), body.index('hasHang'))
        self.assertIn('return .foregroundKill', body)

    def test_groups_are_newest_first(self):
        self.assertIn('$0.latest?.date ?? .distantPast', SRC)
        self.assertIn('$0.date > $1.date', SRC)

    def test_one_row_shows_count_and_latest(self):
        self.assertIn('vm.crashFiles.count', SRC)
        self.assertIn('vm.crashGroups.first?.latest?.date', SRC)
        self.assertIn('crashTimeText', SRC)

    def test_send_to_session_reuses_share_pipeline(self):
        # No separate analyzer: move the file into a chat through the existing
        # share pipeline, then let the AI read it there.
        self.assertIn('ExternalFileImporter.ingest(entry.url, into: ShareCoordinator.shared, accompanyingText:', SRC)
        self.assertIn('ExternalFileImporter.ingest(url, into: ShareCoordinator.shared, accompanyingText:', SRC)
        self.assertIn('发送到会话', SRC)
        self.assertIn('发送最新崩溃到会话', SRC)


if __name__ == '__main__':
    unittest.main(verbosity=2)