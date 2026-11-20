"""模板发布闸口：用探针实际采到的证据核对选择器是否能发布。

维护者在补许可之前也能区分两类字段：

- 已经得到可用证据（``已采证`` 且选择器一致）→ 可发布；
- 仍未验收（待许可/未命中/样本缺字段）→ 证据待验收，禁止发布；
- 证据选择器与模板登记的选择器不一致 → 选择器不一致，禁止发布。

闸口只读取归属于模板所在站点的证据数据集，跨站点证据不可用于发布。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.probe_evidence.models import FieldStatus, FieldVerdict, ManifestRecord
from app.probe_evidence.repository import EvidenceRepository, ManifestRepository


@dataclass(frozen=True)
class FieldCheck:
    field_name: str
    template_selector: str
    verdict: FieldVerdict
    status: FieldStatus | None
    batch_id: str | None
    sample_ref: str | None
    permission_version: int | None
    raw_value: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "template_selector": self.template_selector,
            "verdict": self.verdict.value,
            "evidence_status": self.status.value if self.status else None,
            "batch_id": self.batch_id,
            "sample_ref": self.sample_ref,
            "permission_version": self.permission_version,
            "raw_value": self.raw_value,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TemplateCheckReport:
    template_id: int
    site: str
    publishable: bool
    fields: tuple[FieldCheck, ...]
    publishable_fields: tuple[str, ...]
    blocked_fields: tuple[str, ...]
    # 本次发布判断实际采用的证据批次（每字段取最新一条）。
    referenced_batches: tuple[str, ...]
    # 模板证据清单里全部历史批次，供回查证据演变轨迹。
    provenance_batches: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "site": self.site,
            "publishable": self.publishable,
            "publishable_fields": list(self.publishable_fields),
            "blocked_fields": list(self.blocked_fields),
            "referenced_batches": list(self.referenced_batches),
            "provenance_batches": list(self.provenance_batches),
            "fields": [item.to_dict() for item in self.fields],
        }


class PublishGate:
    def __init__(self, evidence_repo: EvidenceRepository,
                 manifest_repo: ManifestRepository) -> None:
        self._evidence = evidence_repo
        self._manifest = manifest_repo

    def check_template(
        self,
        *,
        template_id: int,
        site: str,
        fields: dict[str, str],
    ) -> TemplateCheckReport:
        checks: list[FieldCheck] = []
        batches: set[str] = set()
        for field_name, template_selector in fields.items():
            checks.append(self._check_field(template_id, site, field_name,
                                            template_selector, batches))
        publishable_fields = tuple(
            item.field_name for item in checks if item.verdict is FieldVerdict.PUBLISHABLE
        )
        blocked_fields = tuple(
            item.field_name for item in checks if item.verdict is not FieldVerdict.PUBLISHABLE
        )
        provenance_batches = tuple(sorted({
            record.batch_id
            for record in self._manifest.list_for_template(template_id)
            if record.site == site
        }))
        return TemplateCheckReport(
            template_id=template_id,
            site=site,
            publishable=not blocked_fields,
            fields=tuple(checks),
            publishable_fields=publishable_fields,
            blocked_fields=blocked_fields,
            referenced_batches=tuple(sorted(batches)),
            provenance_batches=provenance_batches,
        )

    def _check_field(
        self,
        template_id: int,
        site: str,
        field_name: str,
        template_selector: str,
        batches: set[str],
    ) -> FieldCheck:
        record = self._manifest.latest_for_field(template_id, field_name)

        # 归属校验：清单记录必须属于模板所在站点，防止跨站点证据串用。
        if record is None or record.site != site:
            return FieldCheck(
                field_name, template_selector, FieldVerdict.EVIDENCE_PENDING, None,
                None, None, None, None,
                "尚无归属于本站点的探针证据，字段未验收",
            )

        batches.add(record.batch_id)
        # 二次核对证据批次仍在本站点数据集内（不可变存储下的归属兜底）。
        batch = self._evidence.get_batch(site, record.batch_id)
        if batch is None:
            return FieldCheck(
                field_name, template_selector, FieldVerdict.EVIDENCE_PENDING,
                record.status, record.batch_id, record.sample_ref,
                record.permission_version, record.raw_value,
                "证据批次不在本站点探针证据数据集内，归属无法确认",
            )

        if not record.status.usable:
            label = record.status.value
            return FieldCheck(
                field_name, template_selector, FieldVerdict.EVIDENCE_PENDING,
                record.status, record.batch_id, record.sample_ref,
                record.permission_version, None,
                f"字段证据状态为「{label}」（{record.reason}），补许可并重新采样后再发布",
            )

        effective_selector = template_selector or record.selector
        if effective_selector != record.selector:
            return FieldCheck(
                field_name, template_selector, FieldVerdict.SELECTOR_MISMATCH,
                record.status, record.batch_id, record.sample_ref,
                record.permission_version, record.raw_value,
                f"模板选择器 {effective_selector} 与采证选择器 {record.selector} 不一致",
            )

        return FieldCheck(
            field_name, template_selector, FieldVerdict.PUBLISHABLE,
            record.status, record.batch_id, record.sample_ref,
            record.permission_version, record.raw_value,
            f"选择器经样本 {record.sample_ref} 采证可用，可发布",
        )
