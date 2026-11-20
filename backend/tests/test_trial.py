"""探针试跑：许可拦截、字段交付登记、站点隔离、选择器核对。"""
from __future__ import annotations

from app.probe_evidence.models import FieldStatus
from app.probe_evidence.runner import ProbeRunner
from tests.support import ProbeEvidenceTestCase


class ProbeTrialTest(ProbeEvidenceTestCase):
    def test_site_a_trial_delivers_title_and_blocks_price(self) -> None:
        """甲站首轮：标题获准取原值，价格未获准 -> 一交付一拦截。"""
        result = self.service.run_template_trial(self.template_a)
        batch = result.batch

        self.assertTrue(result.new_batch)
        self.assertFalse(result.coalesced)
        self.assertEqual(batch.site, self.site_a)
        self.assertEqual(batch.permission_version, 1)
        self.assertEqual(batch.sample_ref, f"{self.page_id}@{self.version}")

        title = self.field_evidence(batch, self.title)
        self.assertEqual(title.status, FieldStatus.DELIVERED)
        self.assertIsNotNone(title.raw_value)
        self.assertEqual(title.selector, "h1.article-title")

        price = self.field_evidence(batch, self.price)
        self.assertEqual(price.status, FieldStatus.PENDING_PERMISSION)
        # 超出权限的原值必须拦截：证据里不能出现样本原值。
        self.assertIsNone(price.raw_value)
        self.assertIn("未授权", price.reason)

        self.assertEqual(batch.delivered_fields, [self.title])
        self.assertEqual(batch.blocked_fields, [self.price])

    def test_manifest_records_delivered_fields_and_sample_provenance(self) -> None:
        result = self.service.run_template_trial(self.template_a)
        records = {record["field_name"]: record
                   for record in self.service.list_manifest(self.template_a)}
        self.assertEqual(set(records), {self.title, self.price})

        title_record = records[self.title]
        self.assertEqual(title_record["status"], FieldStatus.DELIVERED.value)
        self.assertEqual(title_record["batch_id"], result.batch.batch_id)
        self.assertEqual(title_record["sample_ref"], f"{self.page_id}@{self.version}")
        self.assertEqual(title_record["permission_version"], 1)
        self.assertEqual(title_record["raw_value"],
                         result.batch.evidence_for(self.title).raw_value)
        # 待许可字段同样登记，但明确标注未验收且无原值。
        price_record = records[self.price]
        self.assertEqual(price_record["status"], FieldStatus.PENDING_PERMISSION.value)
        self.assertIsNone(price_record["raw_value"])

    def test_out_of_scope_value_never_leaks_even_if_sample_has_it(self) -> None:
        # 样本里确实有价格原值，但甲站许可不覆盖，任何出口都拿不到原值。
        sample = self.service.catalog.get_sample(self.page_id, self.version)
        self.assertIn(self.price, sample.values)
        result = self.service.run_template_trial(self.template_a)
        blocked = result.batch.evidence_for(self.price)
        self.assertIsNone(blocked.raw_value)
        for record in self.service.list_manifest(self.template_a):
            if record["field_name"] == self.price:
                self.assertIsNone(record["raw_value"])

    def test_site_isolation_same_page_produces_separate_datasets(self) -> None:
        """同页两站：证据按站点分数据集，许可与原值互不可见。"""
        result_a = self.service.run_template_trial(self.template_a)
        result_b = self.service.run_template_trial(self.template_b)

        self.assertNotEqual(result_a.batch.batch_id, result_b.batch.batch_id)
        # 乙站无任何许可：两个字段都应被拦截，没有任何原值交付。
        for evidence in result_b.batch.fields:
            self.assertEqual(evidence.status, FieldStatus.PENDING_PERMISSION)
            self.assertIsNone(evidence.raw_value)

        sites = self.service.evidence_repo.list_sites()
        self.assertCountEqual(sites, [self.site_a, self.site_b])
        # 甲站数据集里查不到乙站批次，反之亦然。
        self.assertIsNone(
            self.service.evidence_repo.get_batch(self.site_a, result_b.batch.batch_id))
        self.assertIsNone(
            self.service.evidence_repo.get_batch(self.site_b, result_a.batch.batch_id))
        # 乙站清单只登记乙站模板，不引用甲站批次。
        b_records = self.service.list_manifest(self.template_b)
        self.assertTrue(b_records)
        self.assertTrue(
            all(record["batch_id"] != result_a.batch.batch_id for record in b_records))

    def test_selector_no_match_blocks_delivery(self) -> None:
        # 甲站标题已授权，但模板若登记错误选择器，探针采不到值 -> 未命中。
        result = self.service.run_trial(
            site=self.site_a, page_id=self.page_id,
            fields={self.title: "h1.wrong-title"},
            template_ids=[self.template_a])
        evidence = result.batch.evidence_for(self.title)
        self.assertEqual(evidence.status, FieldStatus.NO_MATCH)
        self.assertIsNone(evidence.raw_value)

    def test_sample_missing_field(self) -> None:
        # 给甲站补一个样本中不存在的字段许可：授权了但无数据可采。
        self.service.permissions.update_fields(self.site_a, {"幽灵字段"})
        from app.probe_evidence.catalog import SamplingPlanner
        plan = SamplingPlanner(self.service.catalog).plan(
            site=self.site_a, page_id=self.page_id, sample_version=self.version,
            fields={"幽灵字段": ".ghost"})
        permission = self.service.permissions.current(self.site_a)
        evidence = self.service.runner._sample_field(
            "幽灵字段", ".ghost", plan, permission)
        self.assertEqual(evidence.status, FieldStatus.SAMPLE_MISSING)
        self.assertIsNone(evidence.raw_value)

    def test_trial_idempotent_same_permission_returns_same_batch(self) -> None:
        first = self.service.run_template_trial(self.template_a)
        second = self.service.run_template_trial(self.template_a)
        self.assertEqual(first.batch.batch_id, second.batch.batch_id)
        self.assertTrue(second.coalesced)
        self.assertFalse(second.new_batch)
        # 清单幂等：同模板同批次同字段不重复登记。
        records = self.service.list_manifest(self.template_a)
        self.assertEqual(len(records), 2)

    def test_batch_is_immutable_after_permission_change(self) -> None:
        first = self.service.run_template_trial(self.template_a)
        first_batch_id = first.batch.batch_id
        self.service.update_permission(self.site_a, added=[self.price])
        rerun = self.service.run_template_trial(self.template_a)
        # 许可版本变化 -> 新批次；旧批次保留且内容不变。
        self.assertNotEqual(first_batch_id, rerun.batch.batch_id)
        old = self.service.evidence_repo.get_batch(self.site_a, first_batch_id)
        self.assertEqual(old.permission_version, 1)
        self.assertEqual(old.delivered_fields, [self.title])
        self.assertEqual(
            old.evidence_for(self.price).status, FieldStatus.PENDING_PERMISSION)
        new = rerun.batch
        self.assertEqual(new.permission_version, 2)
        self.assertCountEqual(new.delivered_fields, [self.title, self.price])

    def test_permission_version_snapshot_frozen_in_batch(self) -> None:
        result = self.service.run_template_trial(self.template_a)
        self.assertEqual(
            result.batch.allowed_fields_snapshot, frozenset({self.title}))
        # 之后许可扩容不影响旧批次快照。
        self.service.update_permission(self.site_a, added=[self.price])
        old = self.service.evidence_repo.get_batch(
            self.site_a, result.batch.batch_id)
        self.assertEqual(old.allowed_fields_snapshot, frozenset({self.title}))
