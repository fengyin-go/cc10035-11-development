"""许可版本链：站点/字段范围、补许可、历史版本保留。"""
from __future__ import annotations

from app.probe_evidence.permissions import PermissionError
from tests.support import ProbeEvidenceTestCase


class PermissionRegistryTest(ProbeEvidenceTestCase):
    def test_initial_permission_scope(self) -> None:
        current_a = self.service.current_permission(self.site_a)
        self.assertEqual(current_a["version"], 1)
        self.assertEqual(current_a["allowed_fields"], [self.title])
        self.assertTrue(
            self.service.permissions.is_allowed(self.site_a, self.title))
        self.assertFalse(
            self.service.permissions.is_allowed(self.site_a, self.price))

    def test_permission_is_site_scoped(self) -> None:
        # 甲站获准的标题不代表乙站获准。
        self.assertTrue(
            self.service.permissions.is_allowed(self.site_a, self.title))
        self.assertFalse(
            self.service.permissions.is_allowed(self.site_b, self.title))

    def test_update_appends_new_version_and_keeps_history(self) -> None:
        updated = self.service.update_permission(
            self.site_a, added=[self.price], note="补齐价格字段许可")
        self.assertEqual(updated["version"], 2)
        self.assertCountEqual(updated["allowed_fields"], [self.title, self.price])
        # 历史版本 v1 仍可回查，且 v1 下价格依旧未授权。
        v1 = self.service.permissions.version_at(self.site_a, 1)
        self.assertFalse(v1.permits(self.price))
        self.assertFalse(
            self.service.permissions.is_allowed(self.site_a, self.price, version=1)
        )
        history = self.service.permission_history(self.site_a)
        self.assertEqual([item["version"] for item in history], [1, 2])

    def test_revoke_permission(self) -> None:
        self.service.update_permission(self.site_a, removed=[self.title])
        self.assertFalse(
            self.service.permissions.is_allowed(self.site_a, self.title))
        self.assertEqual(
            self.service.current_permission(self.site_a)["version"], 2)

    def test_unknown_site_raises(self) -> None:
        with self.assertRaises(PermissionError):
            self.service.current_permission("丙站")
