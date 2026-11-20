"""分站点探针证据领域。

围绕「模板规则目前缺少区分适用站点和样本归属」的问题，本包提供：

- 采样页目录与数据归属/可用字段校验（``catalog``）
- 分站点、分字段、带版本的采样许可（``permissions``）
- 分站点探针证据数据集与证据批次（``repository``）
- 模板证据清单，登记实际交付字段及样本出处（``repository``）
- 探针执行器：许可拦截、同站同样本并发合批（``runner``）
- 模板发布闸口：用实际采到的证据核对选择器（``gate``）

同一采样页可以被多个站点的模板引用，但每个站点只会产出归属于本站点、
引用本站点许可版本的证据批次，站点之间证据互不可见。
"""
from app.probe_evidence.catalog import PageCatalog, SamplingPlan, SamplingPlanner
from app.probe_evidence.gate import PublishGate, TemplateCheckReport
from app.probe_evidence.models import (
    EvidenceBatch,
    FieldEvidence,
    FieldStatus,
    FieldVerdict,
    ManifestRecord,
    PageSample,
    PermissionVersion,
)
from app.probe_evidence.permissions import PermissionError, PermissionRegistry
from app.probe_evidence.repository import (
    EvidenceRepository,
    ManifestRepository,
)
from app.probe_evidence.runner import ProbeRunner
from app.probe_evidence.service import ProbeEvidenceService, bootstrap_demo_data

__all__ = [
    "EvidenceBatch",
    "EvidenceRepository",
    "FieldEvidence",
    "FieldStatus",
    "FieldVerdict",
    "ManifestRecord",
    "ManifestRepository",
    "PageCatalog",
    "PageSample",
    "PermissionError",
    "PermissionRegistry",
    "PermissionVersion",
    "ProbeEvidenceService",
    "ProbeRunner",
    "PublishGate",
    "SamplingPlan",
    "SamplingPlanner",
    "TemplateCheckReport",
    "bootstrap_demo_data",
]
