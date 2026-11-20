"""探针证据领域的数据模型。

全部模型都是不可变值对象（``frozen=True``），证据一旦生成就不允许就地修改：
许可变更后只能追加新批次，旧批次保留当时确认的许可版本与归属，供回查。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any


class FieldStatus(str, enum.Enum):
    """字段在一次探针批次中的验收状态。

    - ``DELIVERED``：许可覆盖且探针实际采到可用原值，可作为选择器发布证据。
    - ``PENDING_PERMISSION``：模板需要该字段，但当前许可版本未授权，原值被拦截，
      尚无可用证据，需要先补许可。
    - ``NO_MATCH``：许可已授权，但选择器在样本上没有命中任何节点。
    - ``SAMPLE_MISSING``：样本归属正确，但样本里根本没有该字段的数据。
    """

    DELIVERED = "已采证"
    PENDING_PERMISSION = "待许可"
    NO_MATCH = "未命中"
    SAMPLE_MISSING = "样本缺字段"

    @property
    def usable(self) -> bool:
        """只有实际采到原值的字段才算得到可用证据。"""
        return self is FieldStatus.DELIVERED


class FieldVerdict(str, enum.Enum):
    """发布闸口对模板单个字段的核对结论。"""

    PUBLISHABLE = "可发布"        # 选择器有本站点已采证证据支撑
    EVIDENCE_PENDING = "证据待验收"  # 字段还停留在待许可/未命中，不能发布
    SELECTOR_MISMATCH = "选择器不一致"  # 证据选择器与模板登记的选择器不符


@dataclass(frozen=True)
class PageSample:
    """采样页的一个版本样本。

    同一 URL 的不同 ``sample_version`` 视为不同样本；批次按站点 + 页面 + 样本
    版本 + 许可版本归并，避免把不同版本样本的证据混进同一批。
    """

    page_id: str
    url: str
    sample_version: str
    title: str
    # 字段名 -> 页面上该字段的原始值；探针只能从这里取值。
    values: dict[str, str]
    # 字段名 -> 样本页面上确认可命中的选择器。
    selectors: dict[str, str]
    page_owner: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "url": self.url,
            "sample_version": self.sample_version,
            "title": self.title,
            "values": dict(self.values),
            "selectors": dict(self.selectors),
            "page_owner": self.page_owner,
        }


@dataclass(frozen=True)
class PermissionVersion:
    """某站点一个版本的采样许可，许可范围精确到字段。

    许可与站点、字段绑定；不在 ``allowed_fields`` 内的字段原值一律拦截，
    即使样本页面上存在该字段也不允许采集。
    """

    site: str
    version: int
    allowed_fields: frozenset[str]
    note: str = ""
    issued_at: str = ""

    def permits(self, field_name: str) -> bool:
        return field_name in self.allowed_fields

    def to_dict(self) -> dict[str, Any]:
        return {
            "site": self.site,
            "version": self.version,
            "allowed_fields": sorted(self.allowed_fields),
            "note": self.note,
            "issued_at": self.issued_at,
        }


@dataclass(frozen=True)
class FieldEvidence:
    """单字段的探针证据，记录实际交付的字段及样本出处。"""

    field_name: str
    status: FieldStatus
    selector: str
    # 实际交付的原值；待许可等拦截场景下为 None，原值不会离开探针。
    raw_value: str | None
    sample_ref: str          # 样本出处：page_id@sample_version
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "status": self.status.value,
            "usable": self.status.usable,
            "selector": self.selector,
            "raw_value": self.raw_value,
            "sample_ref": self.sample_ref,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class EvidenceBatch:
    """一批站点证据：同站点、同采样页、同样本版本、同许可版本只产出一批。

    批次不可变，并固化采样时确认的许可版本号与授权快照，
    之后许可再变更也不会影响本批的归属与已交付字段。
    """

    batch_id: str
    site: str
    page_id: str
    sample_version: str
    permission_version: int
    # 采样时冻结的许可快照，用于事后核对本批是在什么授权下产出的。
    allowed_fields_snapshot: frozenset[str]
    fields: tuple[FieldEvidence, ...]
    template_ids: tuple[int, ...]
    created_at: str
    coalesced: bool = False  # 是否由并发请求合并产出（同一批只实际采样一次）

    @property
    def sample_ref(self) -> str:
        return f"{self.page_id}@{self.sample_version}"

    def evidence_for(self, field_name: str) -> FieldEvidence | None:
        for item in self.fields:
            if item.field_name == field_name:
                return item
        return None

    @property
    def delivered_fields(self) -> list[str]:
        return [item.field_name for item in self.fields if item.status.usable]

    @property
    def blocked_fields(self) -> list[str]:
        return [item.field_name for item in self.fields if not item.status.usable]

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "site": self.site,
            "page_id": self.page_id,
            "sample_ref": self.sample_ref,
            "sample_version": self.sample_version,
            "permission_version": self.permission_version,
            "allowed_fields_snapshot": sorted(self.allowed_fields_snapshot),
            "template_ids": list(self.template_ids),
            "created_at": self.created_at,
            "coalesced": self.coalesced,
            "delivered_fields": self.delivered_fields,
            "blocked_fields": self.blocked_fields,
            "fields": [item.to_dict() for item in self.fields],
        }


@dataclass(frozen=True)
class ManifestRecord:
    """模板证据清单中的一条登记，指向某批次里某字段的证据出处。"""

    template_id: int
    site: str
    page_id: str
    sample_version: str
    field_name: str
    selector: str
    status: FieldStatus
    batch_id: str
    raw_value: str | None
    sample_ref: str
    permission_version: int
    recorded_at: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "site": self.site,
            "page_id": self.page_id,
            "sample_ref": self.sample_ref,
            "sample_version": self.sample_version,
            "field_name": self.field_name,
            "selector": self.selector,
            "status": self.status.value,
            "usable": self.status.usable,
            "batch_id": self.batch_id,
            "raw_value": self.raw_value,
            "permission_version": self.permission_version,
            "recorded_at": self.recorded_at,
            "reason": self.reason,
        }
