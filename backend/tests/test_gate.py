"""发布闸口：用探针实际采到的字段核对选择器能否发布。"""
from __future__ import annotations

from app.probe_evidence.models import FieldVerdict
from tests.support import ProbeEvidenceTestCase


class PublishGateTest(ProbeEvidenceTestCase):
    def test_before_trial_everything_is_pending(self) -> None:
        report = self.service.check_template_publish(self.template_a)
        self.assertFalse(report.publishable)
        self.assertEqual(list(report.blocked_fields), [self.title, self.price])
        self.assertTrue(
            all(item.verdict is FieldVerdict.EVIDENCE_PENDING for item in report.fields))

    def test_after_trial_title_publishable_price_blocked(self) -> None:
        self.service.run_template_trial(self.template_a)
        report = self.service.check_template_publish(self.template_a)
        verdicts = {item.field_name: item.verdict for item in report.fields}
        self.assertEqual(verdicts[self.title], FieldVerdict.PUBLISHABLE)
        self.assertEqual(verdicts[self.price], FieldVerdict.EVIDENCE_PENDING)
        self.assertFalse(report.publishable)
        self.assertEqual(report.publishable_fields, (self.title,))
        self.assertEqual(report.blocked_fields, (self.price,))
        # 闸口结论带样本出处与批次号，供维护者核对。
        title_check = next(item for item in report.fields if item.field_name == self.title)
        self.assertEqual(title_check.sample_ref, f"{self.page_id}@{self.version}")
        self.assertIsNotNone(title_check.batch_id)

    def test_grant_then_rerun_makes_template_fully_publishable(self) -> None:
        self.service.run_template_trial(self.template_a)
        self.service.update_permission(self.site_a, added=[self.price], note="补齐价格许可")
        self.service.run_template_trial(self.template_a)
        report = self.service.check_template_publish(self.template_a)
        self.assertTrue(report.publishable, report.to_dict())
        # 发布判断对每字段取最新证据，只采用最新许可批次。
        self.assertEqual(len(report.referenced_batches), 1)
        # 清单完整出处保留两个许可批次，可回查证据演变。
        self.assertEqual(len(report.provenance_batches), 2)

    def test_selector_mismatch_is_rejected(self) -> None:
        # 用错误选择器试跑不会产生可用证据；模板发布仍被拦。
        self.service.run_trial(
            site=self.site_a, page_id=self.page_id,
            fields={self.title: "h1.wrong-title"},
            template_ids=[self.template_a])
        report = self.service.check_template_publish(self.template_a)
        title_check = next(item for item in report.fields if item.field_name == self.title)
        self.assertEqual(title_check.verdict, FieldVerdict.EVIDENCE_PENDING)
        self.assertFalse(report.publishable)

    def test_cross_site_evidence_cannot_unblock_publish(self) -> None:
        # 给乙站授权并采到标题证据，甲站模板不能使用乙站证据发布。
        self.service.update_permission(self.site_b, added=[self.title])
        self.service.run_template_trial(self.template_b)
        report_a = self.service.check_template_publish(self.template_a)
        self.assertTrue(
            all(item.verdict is FieldVerdict.EVIDENCE_PENDING for item in report_a.fields))
        report_b = self.service.check_template_publish(self.template_b)
        self.assertEqual(
            next(item for item in report_b.fields
                 if item.field_name == self.title).verdict,
            FieldVerdict.PUBLISHABLE)

    def test_template_selector_changed_after_evidence_detected(self) -> None:
        self.service.run_template_trial(self.template_a)
        # 维护者事后改动模板选择器，与已采证选择器不一致 -> 拦截发布。
        self.service.templates[self.template_a]["fields"][self.title] = "h1.changed"
        report = self.service.check_template_publish(self.template_a)
        title_check = next(item for item in report.fields if item.field_name == self.title)
        self.assertEqual(title_check.verdict, FieldVerdict.SELECTOR_MISMATCH)
