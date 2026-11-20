"""分站点证据数据集的 JSON 持久化与跨进程重开校验。"""
from __future__ import annotations

import json
import os

from app.probe_evidence.models import FieldStatus
from app.probe_evidence.service import ProbeEvidenceService
from tests.support import ProbeEvidenceTestCase


class PersistenceTest(ProbeEvidenceTestCase):
    def test_dataset_written_per_site_as_json(self) -> None:
        self.service.run_template_trial(self.template_a)
        self.service.run_template_trial(self.template_b)
        datasets_dir = os.path.join(self._tmp.name, "datasets")
        self.assertTrue(os.path.exists(os.path.join(datasets_dir, f"{self.site_a}.json")))
        self.assertTrue(os.path.exists(os.path.join(datasets_dir, f"{self.site_b}.json")))

        with open(os.path.join(datasets_dir, f"{self.site_a}.json"), encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertEqual(payload["site"], self.site_a)
        self.assertEqual(payload["batch_count"], 1)
        batch = payload["batches"][0]
        self.assertIn("allowed_fields_snapshot", batch)
        self.assertEqual(batch["permission_version"], 1)

    def test_manifest_json_records_provenance(self) -> None:
        self.service.run_template_trial(self.template_a)
        with open(os.path.join(self._tmp.name, "manifest.json"), encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertEqual(payload["record_count"], 2)
        fields = {item["field_name"]: item for item in payload["records"]}
        self.assertEqual(fields[self.title]["status"], FieldStatus.DELIVERED.value)
        self.assertIsNotNone(fields[self.title]["raw_value"])
        self.assertIsNone(fields[self.price]["raw_value"])

    def test_reopen_service_keeps_batches_and_manifest(self) -> None:
        result = self.service.run_template_trial(self.template_a)
        batch_id = result.batch.batch_id

        # 用同一数据目录重开一个服务实例（不引导演示模板，只验证存储层）。
        reopened = ProbeEvidenceService(data_dir=self._tmp.name)
        batch = reopened.evidence_repo.get_batch(self.site_a, batch_id)
        self.assertIsNotNone(batch)
        self.assertEqual(batch.delivered_fields, [self.title])
        records = reopened.manifest_repo.list_for_template(self.template_a)
        self.assertEqual(len(records), 2)
        # 同许可版本重跑在重开后依然命中同一批次。
        reopened.bootstrap_demo_data()
        rerun = reopened.run_template_trial(self.template_a)
        self.assertEqual(rerun.batch.batch_id, batch_id)
        self.assertTrue(rerun.coalesced)

    def test_batch_id_is_deterministic_for_coalesce_key(self) -> None:
        result = self.service.run_template_trial(self.template_a)
        from app.probe_evidence.runner import ProbeRunner
        key = ProbeRunner.coalesce_key(
            self.site_a, self.page_id, self.version, permission_version=1)
        self.assertEqual(result.batch.batch_id, f"batch-{key}")
