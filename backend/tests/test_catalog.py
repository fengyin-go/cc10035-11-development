"""采样页目录：数据归属与可用字段校验、同页被两站引用。"""
from __future__ import annotations

from app.probe_evidence.catalog import CatalogError, SamplingPlanner
from tests.support import ProbeEvidenceTestCase


class CatalogValidationTest(ProbeEvidenceTestCase):
    def test_same_page_referenced_by_both_sites(self) -> None:
        # 甲乙两站模板登记指向同一采样页同一样本版本。
        tpl_a = self.service.get_template(self.template_a)
        tpl_b = self.service.get_template(self.template_b)
        self.assertEqual(tpl_a["page_id"], tpl_b["page_id"])
        self.assertEqual(tpl_a["sample_version"], tpl_b["sample_version"])

        planner = SamplingPlanner(self.service.catalog)
        plan_a = planner.plan(
            site=self.site_a, page_id=self.page_id,
            sample_version=self.version, fields=tpl_a["fields"])
        plan_b = planner.plan(
            site=self.site_b, page_id=self.page_id,
            sample_version=self.version, fields=tpl_b["fields"])
        # 采样计划引用同一份样本，但归属站点不同。
        self.assertEqual(plan_a.sample_ref, plan_b.sample_ref)
        self.assertNotEqual(plan_a.site, plan_b.site)
        self.assertIn(self.title, plan_a.available_fields)
        self.assertIn(self.price, plan_a.available_fields)

    def test_validation_reports_available_fields(self) -> None:
        report = self.service.validate_sampling(self.page_id, self.version)
        self.assertEqual(report["sample_ref"], f"{self.page_id}@{self.version}")
        self.assertEqual(report["page_owner"], "平台共享采样池")
        self.assertCountEqual(
            report["available_fields"], [self.title, self.price, "正文"])
        self.assertEqual(
            report["available_selectors"][self.title], "h1.article-title")

    def test_unknown_page_and_version_are_rejected(self) -> None:
        with self.assertRaises(CatalogError):
            self.service.validate_sampling("page-not-exist")
        with self.assertRaises(CatalogError):
            self.service.validate_sampling(self.page_id, "v999")

    def test_plan_marks_fields_missing_in_sample(self) -> None:
        planner = SamplingPlanner(self.service.catalog)
        plan = planner.plan(
            site=self.site_a, page_id=self.page_id, sample_version=self.version,
            fields={"不存在的字段": ".nothing"})
        self.assertEqual(plan.to_dict()["missing_in_sample"], ["不存在的字段"])
