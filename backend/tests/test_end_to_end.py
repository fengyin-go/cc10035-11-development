"""端到端：按需求叙述完整走一遍甲乙两站同页试跑与许可变更回查。"""
from __future__ import annotations

from app.probe_evidence.models import FieldStatus, FieldVerdict
from tests.support import ProbeEvidenceTestCase


class EndToEndScenarioTest(ProbeEvidenceTestCase):
    def test_full_story(self) -> None:
        # ---- 前置：甲乙两站登记指向同一采样页的模板 ------------------
        tpl_a = self.service.get_template(self.template_a)
        tpl_b = self.service.get_template(self.template_b)
        self.assertEqual(tpl_a["page_id"], tpl_b["page_id"])
        validation = self.service.validate_sampling(self.page_id)
        self.assertIn(self.price, validation["available_fields"])

        # ---- 甲站用已获准的标题 + 未获准的另一字段发起试跑 ----------
        first = self.service.run_template_trial(self.template_a)
        first_batch_id = first.batch.batch_id
        self.assertEqual(first.batch.permission_version, 1)

        # ---- 核对模板发布实际采用的证据：标题可发布，价格待验收 -----
        report = self.service.check_template_publish(self.template_a)
        self.assertFalse(report.publishable)
        title_check = next(item for item in report.fields if item.field_name == self.title)
        price_check = next(item for item in report.fields if item.field_name == self.price)
        self.assertEqual(title_check.verdict, FieldVerdict.PUBLISHABLE)
        self.assertEqual(price_check.verdict, FieldVerdict.EVIDENCE_PENDING)
        # 补许可前也能区分：已有可用证据 vs 仍未验收。
        self.assertEqual(
            self.manifest_status(self.template_a, self.title), FieldStatus.DELIVERED)
        self.assertEqual(
            self.manifest_status(self.template_a, self.price), FieldStatus.PENDING_PERMISSION)

        # ---- 乙站同页试跑：无许可，全部拦截，且与甲站批次隔离 -------
        b_result = self.service.run_template_trial(self.template_b)
        self.assertNotEqual(b_result.batch.batch_id, first_batch_id)
        self.assertTrue(
            all(item.status is FieldStatus.PENDING_PERMISSION
                for item in b_result.batch.fields))

        # ---- 改变采样许可（给甲站补价格许可）后重跑 ------------------
        new_perm = self.service.update_permission(
            self.site_a, added=[self.price], note="价格字段许可补齐")
        self.assertEqual(new_perm["version"], 2)
        rerun = self.service.run_template_trial(self.template_a)
        self.assertNotEqual(rerun.batch.batch_id, first_batch_id)
        self.assertEqual(rerun.batch.permission_version, 2)

        # ---- 回查前一批的归属与已交付字段：旧批不可变 ---------------
        old_batch = self.service.get_batch(self.site_a, first_batch_id)
        self.assertEqual(old_batch["site"], self.site_a)
        self.assertEqual(old_batch["permission_version"], 1)
        self.assertEqual(old_batch["delivered_fields"], [self.title])
        self.assertEqual(old_batch["blocked_fields"], [self.price])
        old_price = next(item for item in old_batch["fields"]
                         if item["field_name"] == self.price)
        self.assertIsNone(old_price["raw_value"], "旧批次被拦截的原值不得回填")

        # 新批次两个字段均已交付，且都有样本出处。
        self.assertCountEqual(rerun.batch.delivered_fields, [self.title, self.price])
        for evidence in rerun.batch.fields:
            self.assertEqual(evidence.sample_ref, f"{self.page_id}@{self.version}")
            self.assertIsNotNone(evidence.raw_value)

        # 清单同时保留两批历史，可按字段看到从待许可到已采证的轨迹。
        price_records = [
            item for item in self.service.list_manifest(self.template_a)
            if item["field_name"] == self.price
        ]
        self.assertEqual(len(price_records), 2)
        self.assertEqual(
            [item["status"] for item in price_records],
            [FieldStatus.PENDING_PERMISSION.value, FieldStatus.DELIVERED.value])

        # 闸口现在放行整模板；发布采用最新许可批次，清单出处保留两批历史。
        final_report = self.service.check_template_publish(self.template_a)
        self.assertTrue(final_report.publishable)
        self.assertEqual(len(final_report.referenced_batches), 1)
        self.assertEqual(len(final_report.provenance_batches), 2)

        # ---- 分站点数据集总览 ----------------------------------------
        datasets = {item["site"]: item for item in self.service.list_datasets()}
        self.assertEqual(datasets[self.site_a]["batch_count"], 2)
        self.assertEqual(datasets[self.site_b]["batch_count"], 1)

    def test_revoke_permission_blocks_value_on_next_batch(self) -> None:
        # 先补许可采到价格，再收回许可重跑：新批次重新拦截，旧批次保留原值。
        self.service.run_template_trial(self.template_a)
        self.service.update_permission(self.site_a, added=[self.price])
        granted = self.service.run_template_trial(self.template_a)
        self.assertIn(self.price, granted.batch.delivered_fields)

        self.service.update_permission(self.site_a, removed=[self.price], note="收回价格许可")
        revoked = self.service.run_template_trial(self.template_a)
        self.assertEqual(
            revoked.batch.evidence_for(self.price).status,
            FieldStatus.PENDING_PERMISSION)
        self.assertIsNone(revoked.batch.evidence_for(self.price).raw_value)
        # 历史批次的已交付证据不受许可收回影响。
        historical = self.service.evidence_repo.get_batch(
            self.site_a, granted.batch.batch_id)
        self.assertIsNotNone(historical.evidence_for(self.price).raw_value)
