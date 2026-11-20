"""采样页目录：登记采样页及其版本样本，提供数据归属与可用字段校验。

一个采样页（URL）可以同时被多个站点的模板引用，目录本身不归属任何站点；
归属问题发生在证据侧——探针产出的证据永远归发起站点所有。目录负责回答：

1. 模板引用的页面/样本版本是否存在（样本归属校验）；
2. 该样本上实际有哪些字段、哪些选择器可命中（可用字段校验）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.probe_evidence.models import PageSample


class CatalogError(KeyError):
    """采样页或样本版本不存在、模板引用无法落地时抛出。"""


@dataclass(frozen=True)
class SamplingPlan:
    """一次试跑的采样计划：模板字段经归属/可用字段校验后的落地结果。"""

    site: str
    page_id: str
    url: str
    sample_version: str
    sample: PageSample
    # 模板要求的字段 -> 模板登记的选择器（可能为空字符串）。
    requested: dict[str, str]
    # 样本实际可提供的字段（无论是否被许可，许可由探针侧判定）。
    available_fields: frozenset[str]

    @property
    def sample_ref(self) -> str:
        return f"{self.page_id}@{self.sample_version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "site": self.site,
            "page_id": self.page_id,
            "url": self.url,
            "sample_ref": self.sample_ref,
            "sample_version": self.sample_version,
            "requested_fields": list(self.requested),
            "available_fields": sorted(self.available_fields),
            "missing_in_sample": sorted(set(self.requested) - self.available_fields),
        }


class PageCatalog:
    """采样页与版本样本的内存目录（真实项目可换成数据库/对象存储）。"""

    def __init__(self) -> None:
        self._pages: dict[str, list[PageSample]] = {}

    # ---- 登记侧 -------------------------------------------------------
    def register_page(self, sample: PageSample) -> None:
        versions = self._pages.setdefault(sample.page_id, [])
        if any(item.sample_version == sample.sample_version for item in versions):
            raise CatalogError(
                f"采样页 {sample.page_id} 的样本版本 {sample.sample_version} 已存在"
            )
        versions.append(sample)

    def page_exists(self, page_id: str) -> bool:
        return page_id in self._pages

    def get_sample(self, page_id: str, sample_version: str) -> PageSample:
        for sample in self._pages.get(page_id, ()):
            if sample.sample_version == sample_version:
                return sample
        raise CatalogError(f"采样页 {page_id} 不存在样本版本 {sample_version}")

    def latest_version(self, page_id: str) -> str:
        versions = self._pages.get(page_id)
        if not versions:
            raise CatalogError(f"采样页 {page_id} 未登记任何样本")
        return versions[-1].sample_version

    def available_fields(self, page_id: str, sample_version: str) -> frozenset[str]:
        sample = self.get_sample(page_id, sample_version)
        return frozenset(sample.values)

    def list_pages(self) -> list[dict[str, Any]]:
        return [
            {
                "page_id": page_id,
                "url": samples[-1].url,
                "page_owner": samples[-1].page_owner,
                "versions": [item.sample_version for item in samples],
                "available_fields": sorted(samples[-1].values),
            }
            for page_id, samples in sorted(self._pages.items())
        ]


class SamplingPlanner:
    """把模板的试跑请求解析成经过归属与可用字段校验的采样计划。"""

    def __init__(self, catalog: PageCatalog) -> None:
        self._catalog = catalog

    def plan(
        self,
        *,
        site: str,
        page_id: str,
        sample_version: str | None,
        fields: dict[str, str],
    ) -> SamplingPlan:
        if not site:
            raise CatalogError("采样计划必须指明适用站点")
        if not page_id or not self._catalog.page_exists(page_id):
            raise CatalogError(f"采样页 {page_id or '（空）'} 未登记，无法校验数据归属")
        version = sample_version or self._catalog.latest_version(page_id)
        sample = self._catalog.get_sample(page_id, version)
        return SamplingPlan(
            site=site,
            page_id=page_id,
            url=sample.url,
            sample_version=version,
            sample=sample,
            requested=dict(fields),
            available_fields=frozenset(sample.values),
        )
