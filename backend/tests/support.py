"""测试公共夹具：每个用例独立临时数据目录与全新服务实例。"""
from __future__ import annotations

import tempfile
import unittest

from app.probe_evidence.service import (
    PRICE_FIELD,
    SAMPLE_VERSION,
    SHARED_PAGE_ID,
    SITE_A,
    SITE_B,
    TITLE_FIELD,
    ProbeEvidenceService,
)


class ProbeEvidenceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.service = ProbeEvidenceService(data_dir=self._tmp.name)
        self.service.bootstrap_demo_data()
        self.site_a = SITE_A
        self.site_b = SITE_B
        self.page_id = SHARED_PAGE_ID
        self.version = SAMPLE_VERSION
        self.title = TITLE_FIELD
        self.price = PRICE_FIELD
        self.template_a = 101
        self.template_b = 102

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---- 便捷断言 -----------------------------------------------------
    def latest_batch(self, site: str):
        batches = self.service.evidence_repo.list_batches(site)
        self.assertTrue(batches, f"站点 {site} 应至少有一个证据批次")
        return batches[-1]

    def field_evidence(self, batch, field_name: str):
        evidence = batch.evidence_for(field_name)
        self.assertIsNotNone(evidence, f"批次 {batch.batch_id} 缺少字段 {field_name}")
        return evidence

    def manifest_status(self, template_id: int, field_name: str):
        record = self.service.manifest_repo.latest_for_field(template_id, field_name)
        self.assertIsNotNone(record)
        return record.status
