"""分站点采样许可注册中心。

许可有明确的站点与字段范围：

- 每个站点维护一条单调递增的许可版本链；
- 一次许可变更（补许可/收回许可）生成新版本，旧版本保留可回查；
- 探针只在当前（或指定历史）版本授权的字段上放行原值，超出权限的原值拦截。
"""
from __future__ import annotations

from typing import Any, Callable

from app.probe_evidence.models import PermissionVersion


class PermissionError(Exception):
    """请求的站点/许可版本不存在等许可侧错误。"""


class PermissionRegistry:
    def __init__(self, clock: Callable[[], str] | None = None) -> None:
        # site -> 按版本号升序的许可版本链
        self._versions: dict[str, list[PermissionVersion]] = {}
        self._clock = clock or (lambda: "")

    # ---- 变更侧（只追加，不改历史） -----------------------------------
    def grant(
        self,
        site: str,
        allowed_fields: set[str] | frozenset[str],
        *,
        note: str = "",
    ) -> PermissionVersion:
        """登记一个新许可版本；allowed_fields 是该版本的完整授权字段集。"""
        chain = self._versions.setdefault(site, [])
        version = PermissionVersion(
            site=site,
            version=len(chain) + 1,
            allowed_fields=frozenset(allowed_fields),
            note=note,
            issued_at=self._clock(),
        )
        chain.append(version)
        return version

    def update_fields(
        self, site: str, added: set[str] | None = None,
        removed: set[str] | None = None, *, note: str = "",
    ) -> PermissionVersion:
        """在当前许可基础上补许可/收回许可，生成下一版本。"""
        current = self.current(site)
        fields = set(current.allowed_fields)
        fields.update(added or set())
        fields.difference_update(removed or set())
        return self.grant(site, fields, note=note)

    # ---- 查询侧 -------------------------------------------------------
    def has_site(self, site: str) -> bool:
        return bool(self._versions.get(site))

    def current(self, site: str) -> PermissionVersion:
        chain = self._versions.get(site)
        if not chain:
            raise PermissionError(f"站点 {site} 尚未登记任何采样许可")
        return chain[-1]

    def version_at(self, site: str, version: int) -> PermissionVersion:
        for item in self._versions.get(site, ()):
            if item.version == version:
                return item
        raise PermissionError(f"站点 {site} 不存在许可版本 {version}")

    def is_allowed(self, site: str, field_name: str, *, version: int | None = None) -> bool:
        permission = self.current(site) if version is None else self.version_at(site, version)
        return permission.permits(field_name)

    def history(self, site: str) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self._versions.get(site, [])]

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        return {
            site: [item.to_dict() for item in chain]
            for site, chain in sorted(self._versions.items())
        }
