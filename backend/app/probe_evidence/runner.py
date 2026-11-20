"""探针执行器：试跑采样、许可拦截、并发合批、清单回写。

合批语义（需求：对同一站点同一版本样本的并发请求只产出一批站点证据）：

- 合批键 = 站点 + 采样页 + 样本版本 + 采样时确认的许可版本；
- 每个合批键一把线程锁，锁内二次检查数据集，已存在批次则直接复用，
  保证同一时刻 N 个并发请求只实际采样一次、只落一批证据；
- 许可变更后许可版本号变化，合批键随之变化，重跑产生新批次，
  旧批次不可变，可按批次号回查其归属与当时已交付的字段。
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from app.probe_evidence.catalog import SamplingPlanner, SamplingPlan
from app.probe_evidence.models import (
    EvidenceBatch,
    FieldEvidence,
    FieldStatus,
    ManifestRecord,
)
from app.probe_evidence.permissions import PermissionRegistry
from app.probe_evidence.repository import EvidenceRepository, ManifestRepository


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class TrialResult:
    """一次试跑的结果（批次本身不可变，复用状态放在结果里）。"""

    batch: EvidenceBatch
    coalesced: bool          # 是否复用了已存在/并发中的同一合批键批次
    new_batch: bool          # 本次是否实际产出了新批次
    manifest_records: tuple[ManifestRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch": self.batch.to_dict(),
            "coalesced": self.coalesced,
            "new_batch": self.new_batch,
            "manifest_records": [record.to_dict() for record in self.manifest_records],
        }


class ProbeRunner:
    def __init__(
        self,
        planner: SamplingPlanner,
        permissions: PermissionRegistry,
        evidence_repo: EvidenceRepository,
        manifest_repo: ManifestRepository,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._planner = planner
        self._permissions = permissions
        self._evidence = evidence_repo
        self._manifest = manifest_repo
        self._clock = clock or _utc_now
        self._key_locks: dict[str, threading.Lock] = {}
        self._registry_lock = threading.Lock()

    @staticmethod
    def coalesce_key(site: str, page_id: str, sample_version: str, permission_version: int) -> str:
        raw = f"{site}|{page_id}|{sample_version}|perm-v{permission_version}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    def _lock_for(self, key: str) -> threading.Lock:
        with self._registry_lock:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._key_locks[key] = lock
            return lock

    def run_trial(
        self,
        *,
        site: str,
        page_id: str,
        sample_version: str | None,
        fields: dict[str, str],
        template_ids: list[int] | tuple[int, ...] | None = None,
    ) -> TrialResult:
        # 1) 数据归属与可用字段校验：页面/样本不存在直接拒绝。
        plan = self._planner.plan(
            site=site, page_id=page_id, sample_version=sample_version, fields=fields
        )
        # 2) 锁定采样时的许可版本；没有登记许可的站点无法发起试跑。
        permission = self._permissions.current(site)
        key = self.coalesce_key(site, page_id, plan.sample_version, permission.version)
        template_ids = tuple(sorted(set(template_ids or ())))

        lock = self._lock_for(key)
        with lock:
            existing = self._evidence.find_batch(
                site,
                page_id=page_id,
                sample_version=plan.sample_version,
                permission_version=permission.version,
            )
            if existing is not None:
                records = self._write_back(existing, template_ids)
                return TrialResult(batch=existing, coalesced=True, new_batch=False,
                                   manifest_records=tuple(records))

            batch = self._sample(plan, permission, key, template_ids)
            self._evidence.add_batch(batch)
            records = self._write_back(batch, template_ids)
            return TrialResult(batch=batch, coalesced=False, new_batch=True,
                               manifest_records=tuple(records))

    # ---- 实际采样 -----------------------------------------------------
    def _sample(self, plan: SamplingPlan, permission, key: str,
                template_ids: tuple[int, ...]) -> EvidenceBatch:
        sample = plan.sample
        evidences: list[FieldEvidence] = []
        for field_name, requested_selector in plan.requested.items():
            evidences.append(
                self._sample_field(field_name, requested_selector, plan, permission)
            )
        return EvidenceBatch(
            batch_id=f"batch-{key}",
            site=plan.site,
            page_id=plan.page_id,
            sample_version=plan.sample_version,
            permission_version=permission.version,
            allowed_fields_snapshot=permission.allowed_fields,
            fields=tuple(evidences),
            template_ids=template_ids,
            created_at=self._clock(),
        )

    def _sample_field(
        self,
        field_name: str,
        requested_selector: str,
        plan: SamplingPlan,
        permission,
    ) -> FieldEvidence:
        sample = plan.sample
        sample_ref = plan.sample_ref
        canonical_selector = sample.selectors.get(field_name, "")

        # 许可优先：超出站点字段范围的原值在探针处直接拦截，不离开样本边界。
        if not permission.permits(field_name):
            return FieldEvidence(
                field_name=field_name,
                status=FieldStatus.PENDING_PERMISSION,
                selector=requested_selector or canonical_selector,
                raw_value=None,
                sample_ref=sample_ref,
                reason=(
                    f"站点 {plan.site} 许可版本 v{permission.version} 未授权字段"
                    f"「{field_name}」，原值已拦截"
                ),
            )

        # 已授权但样本本身没有该字段数据。
        if field_name not in sample.values:
            return FieldEvidence(
                field_name=field_name,
                status=FieldStatus.SAMPLE_MISSING,
                selector=requested_selector or canonical_selector,
                raw_value=None,
                sample_ref=sample_ref,
                reason=f"样本 {sample_ref} 不包含字段「{field_name}」的数据",
            )

        effective_selector = requested_selector or canonical_selector
        # 选择器在样本 DOM 上未命中（模拟真实探针的选择器探测结果）。
        if effective_selector != canonical_selector:
            return FieldEvidence(
                field_name=field_name,
                status=FieldStatus.NO_MATCH,
                selector=effective_selector,
                raw_value=None,
                sample_ref=sample_ref,
                reason=f"选择器 {effective_selector} 在样本上未命中字段「{field_name}」",
            )

        return FieldEvidence(
            field_name=field_name,
            status=FieldStatus.DELIVERED,
            selector=effective_selector,
            raw_value=sample.values[field_name],
            sample_ref=sample_ref,
            reason="探针实际采到原值",
        )

    def _write_back(
        self, batch: EvidenceBatch, template_ids: tuple[int, ...]
    ) -> list[ManifestRecord]:
        records: list[ManifestRecord] = []
        for template_id in template_ids:
            records.extend(
                self._manifest.write_back(batch, template_id, recorded_at=self._clock())
            )
        return records
