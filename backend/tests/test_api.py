"""探针证据 HTTP 接口冒烟测试。"""
from __future__ import annotations

import tempfile

from fastapi.testclient import TestClient

from app.main import app
from app.probe_evidence.service import (
    PRICE_FIELD,
    SHARED_PAGE_ID,
    SITE_A,
    TITLE_FIELD,
    ProbeEvidenceService,
    bootstrap_demo_data,
)
from tests.support import ProbeEvidenceTestCase


class ApiTest(ProbeEvidenceTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp_dir = tempfile.TemporaryDirectory()
        service = ProbeEvidenceService(data_dir=cls._tmp_dir.name)
        bootstrap_demo_data(service)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp_dir.cleanup()

    def test_01_page_validation(self) -> None:
        resp = self.client.get(
            f"/api/probe-evidence/pages/{SHARED_PAGE_ID}/validation")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn(TITLE_FIELD, payload["available_fields"])

    def test_02_permission_history(self) -> None:
        resp = self.client.get(f"/api/probe-evidence/permissions/{SITE_A}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["current"]["allowed_fields"], [TITLE_FIELD])

    def test_03_trial_blocks_unpermitted_field(self) -> None:
        resp = self.client.post("/api/probe-evidence/templates/101/trial", json={})
        self.assertEqual(resp.status_code, 200)
        batch = resp.json()["batch"]
        statuses = {item["field_name"]: item["status"] for item in batch["fields"]}
        self.assertEqual(statuses[TITLE_FIELD], "已采证")
        self.assertEqual(statuses[PRICE_FIELD], "待许可")

    def test_04_publish_check_reflects_evidence(self) -> None:
        resp = self.client.get("/api/probe-evidence/templates/101/publish-check")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertFalse(payload["publishable"])
        self.assertEqual(payload["publishable_fields"], [TITLE_FIELD])

    def test_05_update_permission_and_rerun(self) -> None:
        resp = self.client.post(
            f"/api/probe-evidence/permissions/{SITE_A}/update",
            json={"added": [PRICE_FIELD], "note": "补齐价格许可"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["permission"]["version"], 2)
        rerun = self.client.post(
            "/api/probe-evidence/templates/101/trial", json={})
        self.assertEqual(rerun.status_code, 200)
        self.assertCountEqual(
            rerun.json()["batch"]["delivered_fields"], [TITLE_FIELD, PRICE_FIELD])
        check = self.client.get("/api/probe-evidence/templates/101/publish-check")
        self.assertTrue(check.json()["publishable"])

    def test_06_datasets_and_manifest(self) -> None:
        datasets = self.client.get("/api/probe-evidence/datasets")
        sites = {item["site"] for item in datasets.json()["items"]}
        self.assertIn(SITE_A, sites)
        manifest = self.client.get("/api/probe-evidence/manifest?template_id=101")
        self.assertEqual(manifest.status_code, 200)
        self.assertTrue(manifest.json()["items"])

    def test_07_unknown_page_returns_404(self) -> None:
        resp = self.client.get("/api/probe-evidence/pages/no-such-page/validation")
        self.assertEqual(resp.status_code, 404)
