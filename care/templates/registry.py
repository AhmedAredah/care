"""Template registry."""
from __future__ import annotations

from collections.abc import Iterable

from .schemas import TemplateSchema


class TemplateRegistry:
    def __init__(self, templates: Iterable[TemplateSchema] | None = None) -> None:
        self._by_id: dict[str, TemplateSchema] = {}
        for template in templates or []:
            self.register(template)

    def register(self, template: TemplateSchema) -> None:
        if template.template_id in self._by_id:
            raise ValueError(f"Duplicate template_id: {template.template_id}")
        self._by_id[template.template_id] = template

    def get(self, template_id: str) -> TemplateSchema:
        if template_id not in self._by_id:
            raise KeyError(f"Template '{template_id}' not registered")
        return self._by_id[template_id]

    def has(self, template_id: str) -> bool:
        return template_id in self._by_id

    def all(self) -> list[TemplateSchema]:
        return list(self._by_id.values())

    def names(self) -> list[str]:
        return sorted(self._by_id)

    def __len__(self) -> int:
        return len(self._by_id)

    def filter_by(
        self,
        *,
        jurisdiction: str | None = None,
        template_ids: Iterable[str] | None = None,
    ) -> TemplateRegistry:
        """Return a new registry restricted to a per-job allowlist.

        Both arguments are optional and additive (AND): a template must
        satisfy every supplied criterion to be included. If neither
        argument is supplied (or both reduce to empty after stripping),
        the returned registry contains every template — i.e. an absent
        or empty allowlist is treated as "no filter, use all" so the
        common case of "submit a job without naming a state" still
        works.
        """
        juris = (jurisdiction or "").strip() or None
        ids: set[str] | None = None
        if template_ids is not None:
            ids = {tid.strip() for tid in template_ids if tid and tid.strip()}
            if not ids:
                ids = None
        if juris is None and ids is None:
            return TemplateRegistry(self.all())
        filtered: list[TemplateSchema] = []
        for t in self._by_id.values():
            if juris is not None and (t.jurisdiction or "") != juris:
                continue
            if ids is not None and t.template_id not in ids:
                continue
            filtered.append(t)
        return TemplateRegistry(filtered)
