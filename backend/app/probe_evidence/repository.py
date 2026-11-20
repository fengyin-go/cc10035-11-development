"""探针证据数据集与模板证据清单的存储。

- ``EvidenceRepository``：分站点的探针证据数据集。每个站点一个 JSON 文件，
  站点之间物理隔离；批次只追加、不可变，批次内固化采样时确认的许可版本。
- ``ManifestRepository``：模板证据清单，回写每个模板实际交付的字段及其样本
  出处（批次号、样本引用、选择器、原值、许可版本）。

同一批次被多个模板/多次请求引用时，清单按 (模板, 批次, 字段) 幂等去重，
不会重复登记。
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from app.probe_evidence.models import (
    EvidenceBatch,
    FieldEvidence,
    FieldStatus,
    ManifestRecord,
)


def _atomic_write_json(path: str, payload: Any) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _batch_from_dict(data: dict[str, Any]) -> EvidenceBatch:
    return EvidenceBatch(
        batch_id=data["batch_id"],
        site=data["site"],
        page_id=data["page_id"],
        sample_version=data["sample_version"],
        permission_version=data["permission_version"],
        allowed_fields_snapshot=frozenset(data["allowed_fields_snapshot"]),
        fields=tuple(
            FieldEvidence(
                field_name=item["field_name"],
                status=FieldStatus(item["status"]),
                selector=item["selector"],
                raw_value=item["raw_value"],
                sample_ref=item["sample_ref"],
                reason=item.get("reason", ""),
            )
            for item in data["fields"]
        ),
        template_ids=tuple(data.get("template_ids", [])),
        created_at=data["created_at"],
        coalesced=data.get("coalesced", False),
    )


class EvidenceRepository:
    """分站点证据数据集：``<data_dir>/datasets/<site>.json``。"""

    def __init__(self, data_dir: str) -> None:
        self._data_dir = data_dir
        self._datasets_dir = os.path.join(data_dir, "datasets")
        os.makedirs(self._datasets_dir, exist_ok=True)
        self._cache: dict[str, list[EvidenceBatch]] = {}

    # ---- 站点隔离的文件读写 -------------------------------------------
    def _site_path(self, site: str) -> str:
        return os.path.join(self._datasets_dir, f"{site}.json")

    def _load(self, site: str) -> list[EvidenceBatch]:
        if site in self._cache:
            return self._cache[site]
        path = self._site_path(site)
        if not os.path.exists(path):
            self._cache[site] = []
            return self._cache[site]
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        batches = [_batch_from_dict(item) for item in payload.get("batches", [])]
        self._cache[site] = batches
        return batches

    def _flush(self, site: str) -> None:
        batches = self._cache.setdefault(site, [])
        payload = {
            "site": site,
            "batch_count": len(batches),
            "batches": [batch.to_dict() for batch in batches],
        }
        _atomic_write_json(self._site_path(site), payload)

    # ---- 写入 ---------------------------------------------------------
    def add_batch(self, batch: EvidenceBatch) -> None:
        batches = self._load(batch.site)
        if any(item.batch_id == batch.batch_id for item in batches):
            raise ValueError(f"证据批次 {batch.batch_id} 已存在，批次不可覆盖")
        batches.append(batch)
        self._flush(batch.site)

    # ---- 查询 ---------------------------------------------------------
    def list_sites(self) -> list[str]:
        if not os.path.isdir(self._datasets_dir):
            return []
        return sorted(
            filename[:-5]
            for filename in os.listdir(self._datasets_dir)
            if filename.endswith(".json")
        )

    def list_batches(self, site: str) -> list[EvidenceBatch]:
        return list(self._load(site))

    def get_batch(self, site: str, batch_id: str) -> EvidenceBatch | None:
        for batch in self._load(site):
            if batch.batch_id == batch_id:
                return batch
        return None

    def find_batch(
        self,
        site: str,
        *,
        page_id: str,
        sample_version: str,
        permission_version: int,
    ) -> EvidenceBatch | None:
        """按合批键精确查找已有批次（同站同样本同许可版本只产出一批）。"""
        for batch in self._load(site):
            if (
                batch.page_id == page_id
                and batch.sample_version == sample_version
                and batch.permission_version == permission_version
            ):
                return batch
        return None

    def dataset_summary(self, site: str) -> dict[str, Any]:
        batches = self._load(site)
        delivered = sum(len(batch.delivered_fields) for batch in batches)
        blocked = sum(len(batch.blocked_fields) for batch in batches)
        return {
            "site": site,
            "batch_count": len(batches),
            "delivered_field_evidences": delivered,
            "blocked_field_evidences": blocked,
            "batches": [batch.batch_id for batch in batches],
        }


class ManifestRepository:
    """模板证据清单：``<data_dir>/manifest.json``，按模板登记字段证据出处。"""

    def __init__(self, data_dir: str) -> None:
        self._path = os.path.join(data_dir, "manifest.json")
        os.makedirs(data_dir, exist_ok=True)
        self._records: list[ManifestRecord] = self._read()

    def _read(self) -> list[ManifestRecord]:
        if not os.path.exists(self._path):
            return []
        with open(self._path, encoding="utf-8") as handle:
            payload = json.load(handle)
        records: list[ManifestRecord] = []
        for item in payload.get("records", []):
            records.append(
                ManifestRecord(
                    template_id=item["template_id"],
                    site=item["site"],
                    page_id=item["page_id"],
                    sample_version=item["sample_version"],
                    field_name=item["field_name"],
                    selector=item["selector"],
                    status=FieldStatus(item["status"]),
                    batch_id=item["batch_id"],
                    raw_value=item["raw_value"],
                    sample_ref=item["sample_ref"],
                    permission_version=item["permission_version"],
                    recorded_at=item["recorded_at"],
                    reason=item.get("reason", ""),
                )
            )
        return records

    def _flush(self) -> None:
        payload = {
            "record_count": len(self._records),
            "records": [record.to_dict() for record in self._records],
        }
        _atomic_write_json(self._path, payload)

    def write_back(self, batch: EvidenceBatch, template_id: int, recorded_at: str) -> list[ManifestRecord]:
        """把一个批次对某模板的字段证据回写到清单，重复登记自动跳过。"""
        added: list[ManifestRecord] = []
        existing = {
            (record.template_id, record.batch_id, record.field_name)
            for record in self._records
        }
        for evidence in batch.fields:
            key = (template_id, batch.batch_id, evidence.field_name)
            if key in existing:
                continue
            record = ManifestRecord(
                template_id=template_id,
                site=batch.site,
                page_id=batch.page_id,
                sample_version=batch.sample_version,
                field_name=evidence.field_name,
                selector=evidence.selector,
                status=evidence.status,
                batch_id=batch.batch_id,
                raw_value=evidence.raw_value,
                sample_ref=evidence.sample_ref,
                permission_version=batch.permission_version,
                recorded_at=recorded_at,
                reason=evidence.reason,
            )
            self._records.append(record)
            existing.add(key)
            added.append(record)
        if added:
            self._flush()
        return added

    def list_for_template(self, template_id: int) -> list[ManifestRecord]:
        return [record for record in self._records if record.template_id == template_id]

    def latest_for_field(self, template_id: int, field_name: str) -> ManifestRecord | None:
        matches = [
            record for record in self._records
            if record.template_id == template_id and record.field_name == field_name
        ]
        return matches[-1] if matches else None

    def all_records(self) -> list[ManifestRecord]:
        return list(self._records)
