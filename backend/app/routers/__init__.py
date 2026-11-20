"""业务路由汇总：通用模块资源路由 + 探针证据专用路由。"""
from __future__ import annotations

from app.routers import probe_evidence, resource

ROUTERS = [probe_evidence, resource]
