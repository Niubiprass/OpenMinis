#!/usr/bin/env python3
"""Source-contract tests for [T-115-model-catalog]: read-only global catalog.

Entry lives in ProviderInstancesView (NOT the guarded UnifiedModelPicker
toolbar). The catalog has zero write paths: no selection/save/refresh that
could disturb saved provider configs, model groups or routing.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
VIEW = (ROOT / 'src/ios/Views/Providers/ProviderInstancesView.swift').read_text()


class ModelCatalogSource(unittest.TestCase):
    """[T-115-model-catalog] Source-wiring contracts."""

    def test_catalog_view_exists_with_entry(self):
        self.assertIn('struct ModelCatalogView: View', VIEW)
        self.assertIn('NavigationLink {\n                    ModelCatalogView()', VIEW)
        self.assertIn('Label("Model Catalog", systemImage: "books.vertical")', VIEW)

    def test_grouping_and_search(self):
        # Grouped by provider instance, ordered like the picker, searchable.
        self.assertIn('ProviderConfigStore.sortedByReleaseRank(store.entries(for: instance.id))', VIEW)
        self.assertIn('store.instances.compactMap', VIEW)
        self.assertIn('@State private var query = ""', VIEW)
        self.assertIn('.searchable(text: $query', VIEW)

    def test_metadata_badges_only_when_known(self):
        # No fabricated capabilities: chips render only for reported fields.
        self.assertIn('if let ctx = m.contextWindow', VIEW)
        self.assertIn('if let out = m.maxOutputTokens', VIEW)
        self.assertIn('if m.supportsReasoning == true', VIEW)
        self.assertIn('if let modality = m.modalityOverride', VIEW)
        self.assertIn('Explicit modality flags only', VIEW)

    def test_modality_badges_explicit_flags_only(self):
        self.assertIn('static func modalityBadges(_ m: ModelModality) -> [String]', VIEW)
        self.assertIn('if m.contains(.imageInput) { out.append("vision") }', VIEW)
        # Legacy alias must not fabricate vision from nothing.
        self.assertNotIn('textOnly', VIEW[VIEW.index('static func modalityBadges'):])

    def test_catalog_has_zero_write_paths(self):
        # Read-only v1: no selection, save, override, hide, group or refresh
        # anywhere in the catalog section of the file.
        section = VIEW[VIEW.index('struct ModelCatalogView'):]
        for forbidden in ['onAddMulti', 'updateGroup', 'save(', 'setCustom',
                          'isHidden', 'refreshModels', 'toggleHidden',
                          'ProviderConfigStore.shared.save']:
            self.assertNotIn(forbidden, section,
                             f'catalog must not contain write path: {forbidden}')

    def test_empty_states(self):
        self.assertIn('"No models available"', VIEW)
        self.assertIn('"No matches"', VIEW)


if __name__ == '__main__':
    unittest.main(verbosity=2)