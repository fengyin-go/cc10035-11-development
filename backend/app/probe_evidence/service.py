"""探针证据应用服务：串联采样页目录、许可、证据数据集、清单与发布闸口。

同时承载「甲乙两站登记指向同页的模板」演示场景的引导数据，
HTTP 路由与端到端演示脚本都通过本服务访问领域能力。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from app.probe_evidence.catalog import PageCatalog, SamplingPlanner
from app.probe_evidence.gate import FieldCheck, PublishGate, TemplateCheckReport
from app.probe_evidence.models import PageSample
from app.probe_evidence.permissions import PermissionError, PermissionRegistry
from app.probe_evidence.repository import EvidenceRepository, ManifestRepository
from app.probe_evidence.runner import ProbeRunner, TrialResult

# 演示场景固定标识，便于测试与文档引用。
SHARED_PAGE_ID = "page-shared-news"
SITE_A = "甲站"
SITE_B = "乙站"
TITLE_FIELD = "标题"
PRICE_FIELD = "价格"
SAMPLE_VERSION = "v1"

DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "probe_evidence",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProbeEvidenceService:
    """对外门面：路由层只做参数解析，所有业务判断收敛在这里。"""

    def __init__(self, data_dir: str | None = None) -> None:
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.catalog = PageCatalog()
        self.permissions = PermissionRegistry(clock=_utc_now)
        self.evidence_repo = EvidenceRepository(self.data_dir)
        self.manifest_repo = ManifestRepository(self.data_dir)
        self.planner = SamplingPlanner(self.catalog)
        self.gate = PublishGate(self.evidence_repo, self.manifest_repo)
        self.runner = ProbeRunner(
            self.planner, self.permissions,
            self.evidence_repo, self.manifest_repo, clock=_utc_now,
        )
        # 模板登记：template_id -> 模板的站点、采样页、字段选择器。
        self.templates: dict[int, dict[str, Any]] = {}
        self._bootstrapped = False

    # ---- 引导数据 -----------------------------------------------------
    def bootstrap_demo_data(self) -> None:
        """建立甲乙两站同页场景与初始许可（幂等）。"""
        if self._bootstrapped:
            return
        # 同一个采样页、同一个版本样本，可被两个站的模板同时引用。
        self.catalog.register_page(PageSample(
            page_id=SHARED_PAGE_ID,
            url="https://example.invalid/news/2026/11/20/template-trial",
            sample_version=SAMPLE_VERSION,
            title="同页采样-资讯详情页",
            values={
                TITLE_FIELD: "双11家电以旧换新政策落地，平台补贴最高加码至20%",
                PRICE_FIELD: "2999",
                "正文": "……（正文原始内容）……",
            },
            selectors={
                TITLE_FIELD: "h1.article-title",
                PRICE_FIELD: "span.price-now",
                "正文": "div.article-body",
            },
            page_owner="平台共享采样池",
        ))
        # 甲站：标题已获准取原值，价格仍待许可。
        self.permissions.grant(SITE_A, {TITLE_FIELD}, note="甲站首轮许可：仅标题可采原值")
        # 乙站：初始无任何字段许可（可用于演示另一站的隔离拦截）。
        self.permissions.grant(SITE_B, set(), note="乙站首轮许可：暂未授权任何字段")

        # 两站模板指向同一采样页；选择器与样本命中选择器一致。
        self.templates[101] = {
            "template_id": 101,
            "name": "甲站-资讯模板",
            "site": SITE_A,
            "page_id": SHARED_PAGE_ID,
            "sample_version": SAMPLE_VERSION,
            "fields": {
                TITLE_FIELD: "h1.article-title",
                PRICE_FIELD: "span.price-now",
            },
        }
        self.templates[102] = {
            "template_id": 102,
            "name": "乙站-资讯模板",
            "site": SITE_B,
            "page_id": SHARED_PAGE_ID,
            "sample_version": SAMPLE_VERSION,
            "fields": {
                TITLE_FIELD: "h1.article-title",
                PRICE_FIELD: "span.price-now",
            },
        }
        self._bootstrapped = True

    # ---- 模板与采样页查询 ---------------------------------------------
    def list_templates(self) -> list[dict[str, Any]]:
        return [
            {**item, "fields": dict(item["fields"])}
            for item in sorted(self.templates.values(), key=lambda row: row["template_id"])
        ]

    def get_template(self, template_id: int) -> dict[str, Any] | None:
        item = self.templates.get(template_id)
        return None if item is None else {**item, "fields": dict(item["fields"])}

    def validate_sampling(self, page_id: str, sample_version: str | None = None) -> dict[str, Any]:
        """校验采样页的数据归属与可用字段。"""
        version = sample_version or self.catalog.latest_version(page_id)
        sample = self.catalog.get_sample(page_id, version)
        return {
            "page_id": page_id,
            "url": sample.url,
            "sample_version": version,
            "sample_ref": f"{page_id}@{version}",
            "page_owner": sample.page_owner,
            "available_fields": sorted(sample.values),
            "available_selectors": dict(sample.selectors),
        }

    def list_pages(self) -> list[dict[str, Any]]:
        return self.catalog.list_pages()

    # ---- 许可管理 -----------------------------------------------------
    def current_permission(self, site: str) -> dict[str, Any]:
        return self.permissions.current(site).to_dict()

    def permission_history(self, site: str) -> list[dict[str, Any]]:
        return self.permissions.history(site)

    def grant_permission(self, site: str, allowed_fields: list[str], note: str = "") -> dict[str, Any]:
        return self.permissions.grant(site, set(allowed_fields), note=note).to_dict()

    def update_permission(
        self, site: str, added: list[str] | None = None,
        removed: list[str] | None = None, note: str = "",
    ) -> dict[str, Any]:
        return self.permissions.update_fields(
            site, set(added or []), set(removed or []), note=note
        ).to_dict()

    # ---- 探针试跑 -----------------------------------------------------
    def run_template_trial(
        self,
        template_id: int,
        *,
        fields: list[str] | None = None,
        sample_version: str | None = None,
    ) -> TrialResult:
        template = self.templates.get(template_id)
        if template is None:
            raise KeyError(f"模板 {template_id} 未登记")
        wanted = fields or list(template["fields"])
        unknown = [name for name in wanted if name not in template["fields"]]
        if unknown:
            raise KeyError(f"模板 {template_id} 不包含字段：{'、'.join(unknown)}")
        field_selectors = {name: template["fields"][name] for name in wanted}
        return self.runner.run_trial(
            site=template["site"],
            page_id=template["page_id"],
            sample_version=sample_version or template["sample_version"],
            fields=field_selectors,
            template_ids=[template_id],
        )

    def run_trial(
        self,
        *,
        site: str,
        page_id: str,
        fields: dict[str, str],
        template_ids: list[int] | None = None,
        sample_version: str | None = None,
    ) -> TrialResult:
        return self.runner.run_trial(
            site=site,
            page_id=page_id,
            sample_version=sample_version,
            fields=fields,
            template_ids=template_ids,
        )

    # ---- 证据数据集与清单查询 -----------------------------------------
    def list_site_batches(self, site: str) -> list[dict[str, Any]]:
        return [batch.to_dict() for batch in self.evidence_repo.list_batches(site)]

    def get_batch(self, site: str, batch_id: str) -> dict[str, Any]:
        batch = self.evidence_repo.get_batch(site, batch_id)
        if batch is None:
            raise KeyError(f"站点 {site} 的证据数据集不存在批次 {batch_id}")
        return batch.to_dict()

    def dataset_summary(self, site: str) -> dict[str, Any]:
        return self.evidence_repo.dataset_summary(site)

    def list_datasets(self) -> list[dict[str, Any]]:
        return [self.evidence_repo.dataset_summary(site)
                for site in self.evidence_repo.list_sites()]

    def list_manifest(self, template_id: int | None = None) -> list[dict[str, Any]]:
        if template_id is None:
            return [record.to_dict() for record in self.manifest_repo.all_records()]
        return [
            record.to_dict()
            for record in self.manifest_repo.list_for_template(template_id)
        ]

    # ---- 发布闸口 -----------------------------------------------------
    def check_template_publish(self, template_id: int) -> TemplateCheckReport:
        template = self.templates.get(template_id)
        if template is None:
            raise KeyError(f"模板 {template_id} 未登记")
        return self.gate.check_template(
            template_id=template_id, site=template["site"], fields=template["fields"]
        )


def bootstrap_demo_data(service: ProbeEvidenceService | None = None) -> ProbeEvidenceService:
    """模块级便捷函数：创建（或复用）单例服务并完成演示数据引导。"""
    global _DEFAULT_SERVICE
    if service is not None:
        _DEFAULT_SERVICE = service
        service.bootstrap_demo_data()
        return service
    if _DEFAULT_SERVICE is None:
        _DEFAULT_SERVICE = ProbeEvidenceService()
        _DEFAULT_SERVICE.bootstrap_demo_data()
    return _DEFAULT_SERVICE


_DEFAULT_SERVICE: ProbeEvidenceService | None = None


def get_service() -> ProbeEvidenceService:
    """FastAPI 依赖入口：惰性初始化默认单例。"""
    if _DEFAULT_SERVICE is None:
        bootstrap_demo_data()
    assert _DEFAULT_SERVICE is not None
    return _DEFAULT_SERVICE


__all__ = [
    "ProbeEvidenceService",
    "bootstrap_demo_data",
    "get_service",
    "PermissionError",
    "FieldCheck",
]
