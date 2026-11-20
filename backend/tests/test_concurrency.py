"""并发合批：同站点同样本版本的并发请求只产出一批站点证据。"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from app.probe_evidence.models import FieldStatus
from tests.support import ProbeEvidenceTestCase


class ConcurrencyTest(ProbeEvidenceTestCase):
    def test_concurrent_requests_coalesce_to_one_batch(self) -> None:
        errors: list[Exception] = []
        results = []
        lock = threading.Lock()

        def fire() -> None:
            try:
                result = self.service.run_template_trial(self.template_a)
                with lock:
                    results.append(result)
            except Exception as exc:  # pragma: no cover - 测试失败路径
                with lock:
                    errors.append(exc)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: fire(), range(16)))

        self.assertFalse(errors)
        self.assertEqual(len(results), 16)
        batch_ids = {result.batch.batch_id for result in results}
        self.assertEqual(len(batch_ids), 1, "并发请求必须合并为同一批次")

        stored = self.service.evidence_repo.list_batches(self.site_a)
        self.assertEqual(len(stored), 1, "站点证据数据集只允许落一批")
        # 清单按 (模板,批次,字段) 幂等，合并不会产生重复登记。
        records = self.service.list_manifest(self.template_a)
        self.assertEqual(len(records), 2)
        self.assertTrue(
            all(record["batch_id"] == stored[0].batch_id for record in records))

    def test_different_sites_do_not_coalesce(self) -> None:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(self.service.run_template_trial, self.template_a),
                pool.submit(self.service.run_template_trial, self.template_a),
                pool.submit(self.service.run_template_trial, self.template_b),
                pool.submit(self.service.run_template_trial, self.template_b),
            ]
            results = [future.result() for future in futures]
        batch_ids = {result.batch.batch_id for result in results}
        self.assertEqual(len(batch_ids), 2, "不同站点各自成批")

    def test_concurrent_trial_keeps_evidence_semantics(self) -> None:
        def fire():
            return self.service.run_template_trial(self.template_a)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = [future.result()
                       for future in [pool.submit(fire) for _ in range(8)]]
        for result in results:
            statuses = {item.field_name: item.status for item in result.batch.fields}
            self.assertEqual(statuses[self.title], FieldStatus.DELIVERED)
            self.assertEqual(statuses[self.price], FieldStatus.PENDING_PERMISSION)
