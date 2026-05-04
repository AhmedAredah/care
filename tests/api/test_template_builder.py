"""Phase 8 — template builder backend tests.

Calls FastAPI handlers directly (no httpx). Covers:

- normalized-coord conversion math
- session creation against a synthetic PDF
- page image endpoint serves only files inside work_dir/template-builder/<token>/
- token regex blocks traversal-shaped inputs
- preview returns structured QA without writing anywhere
- save validates the YAML before writing
- save refuses overwrite without force=true; allows it with force=true
- save rejects bad jurisdiction / template_id shapes
- delete cleans up the session work_dir
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException
from fastapi.responses import FileResponse

from care.api.routes_template_builder import (
    PreviewRequest,
    SaveRequest,
    SourceRequest,
    create_source,
    delete_source,
    get_source_page,
    preview,
    save_template,
)
from care.core.config import AppConfig
from care.services.template_builder import (
    TOKEN_RE,
    BuilderSessionError,
    TemplateBuilderStore,
    pixel_bbox_to_norm,
)
from tests._fixtures import make_digital_pdf, make_synthetic_image

# ----- pixel-to-normalized-coord conversion -------------------------------


def test_pixel_bbox_to_norm_round_trips_simple_case() -> None:
    out = pixel_bbox_to_norm([0, 0, 800, 1000], 1600, 2000)
    assert out == [0.0, 0.0, 0.5, 0.5]


def test_pixel_bbox_to_norm_clamps_off_page_drag() -> None:
    out = pixel_bbox_to_norm([-50, -10, 2000, 5000], 1000, 1000)
    assert out == [0.0, 0.0, 1.0, 1.0]


def test_pixel_bbox_to_norm_swaps_inverted_corners() -> None:
    out = pixel_bbox_to_norm([800, 600, 200, 100], 1000, 1000)
    assert out == [0.2, 0.1, 0.8, 0.6]


def test_pixel_bbox_to_norm_rejects_zero_width_page() -> None:
    with pytest.raises(ValueError):
        pixel_bbox_to_norm([0, 0, 100, 100], 0, 100)


def test_pixel_bbox_to_norm_rejects_short_bbox() -> None:
    with pytest.raises(ValueError):
        pixel_bbox_to_norm([0, 0, 100], 100, 100)


# ----- store path safety --------------------------------------------------


def test_store_token_regex_matches_only_16_hex() -> None:
    assert TOKEN_RE.fullmatch("0123456789abcdef")
    assert not TOKEN_RE.fullmatch("0123456789ABCDEF")
    assert not TOKEN_RE.fullmatch("../etc/passwd")
    assert not TOKEN_RE.fullmatch("0123456789abcde")
    assert not TOKEN_RE.fullmatch("g123456789abcdef")


def test_store_page_image_path_rejects_invalid_token(tmp_path: Path) -> None:
    store = TemplateBuilderStore(work_dir=tmp_path)
    for bad in ["..", "../etc/passwd", "0123456789ABCDEF", "g" * 16, ""]:
        with pytest.raises(BuilderSessionError):
            store.page_image_path(bad, 0)


def test_store_page_image_path_rejects_negative_page(tmp_path: Path) -> None:
    store = TemplateBuilderStore(work_dir=tmp_path)
    with pytest.raises(BuilderSessionError):
        store.page_image_path("0" * 16, -1)


def test_store_session_dir_is_inside_work_dir(tmp_path: Path) -> None:
    """Even with a malicious-looking token shape, safe_join keeps the
    resulting path under work_dir/template-builder/."""
    store = TemplateBuilderStore(work_dir=tmp_path)
    # A real token (regex-matching) round-trips cleanly.
    sess_dir = store._session_dir("abcdef0123456789")
    assert sess_dir.resolve().is_relative_to(tmp_path.resolve())


def test_store_create_session_renders_into_token_dir(tmp_path: Path) -> None:
    src = make_digital_pdf(tmp_path / "sample.pdf")
    store = TemplateBuilderStore(work_dir=tmp_path / "work")
    session = store.create_session(src)
    assert TOKEN_RE.fullmatch(session.token)
    assert (tmp_path / "work" / "template-builder" / session.token).is_dir()
    assert all(
        Path(p.image_path).resolve().is_relative_to(
            (tmp_path / "work" / "template-builder").resolve()
        )
        for p in session.pages
    )
    assert session.pages[0].width > 0
    # A digital PDF must produce at least some native words.
    total_words = sum(len(p.words) for p in session.pages)
    assert total_words > 0


def test_store_delete_session_removes_files(tmp_path: Path) -> None:
    src = make_digital_pdf(tmp_path / "sample.pdf")
    store = TemplateBuilderStore(work_dir=tmp_path / "work")
    session = store.create_session(src)
    sess_dir = tmp_path / "work" / "template-builder" / session.token
    assert sess_dir.exists()
    assert store.delete_session(session.token)
    assert not sess_dir.exists()
    assert store.get_session(session.token) is None


def test_store_create_session_rejects_relative_path(tmp_path: Path) -> None:
    store = TemplateBuilderStore(work_dir=tmp_path)
    with pytest.raises(BuilderSessionError):
        store.create_session("relative.pdf")


def test_store_create_session_rejects_missing_file(tmp_path: Path) -> None:
    store = TemplateBuilderStore(work_dir=tmp_path)
    with pytest.raises(BuilderSessionError):
        store.create_session(tmp_path / "no_such.pdf")


# ----- API: source / page / preview / save -------------------------------


def _store_for(tmp_path: Path) -> tuple[TemplateBuilderStore, AppConfig]:
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")
    cfg.paths.export_dir = str(tmp_path / "exports")
    cfg.paths.templates_dir = str(tmp_path / "templates")
    Path(cfg.paths.work_dir).mkdir(parents=True, exist_ok=True)
    return TemplateBuilderStore(work_dir=Path(cfg.paths.work_dir)), cfg


def test_create_source_returns_token_and_pages(tmp_path: Path) -> None:
    src = make_digital_pdf(tmp_path / "sample.pdf")
    store, cfg = _store_for(tmp_path)
    payload = create_source(SourceRequest(path=str(src)), store=store)
    assert TOKEN_RE.fullmatch(payload["token"])
    assert payload["page_count"] == len(payload["pages"])
    for page in payload["pages"]:
        assert page["image_url"].startswith(
            f"/api/template-builder/source/{payload['token']}/page/"
        )


def test_create_source_rejects_relative_path(tmp_path: Path) -> None:
    store, _cfg = _store_for(tmp_path)
    with pytest.raises(HTTPException) as ei:
        create_source(SourceRequest(path="relative.pdf"), store=store)
    assert ei.value.status_code == 400


def test_create_source_404_when_file_missing(tmp_path: Path) -> None:
    store, _cfg = _store_for(tmp_path)
    with pytest.raises(HTTPException) as ei:
        create_source(SourceRequest(path=str(tmp_path / "no_such.pdf")), store=store)
    assert ei.value.status_code == 404


def test_get_source_page_serves_only_inside_work_dir(tmp_path: Path) -> None:
    src = make_digital_pdf(tmp_path / "sample.pdf")
    store, cfg = _store_for(tmp_path)
    created = create_source(SourceRequest(path=str(src)), store=store)
    response = get_source_page(created["token"], 0, store=store)
    assert isinstance(response, FileResponse)
    served = Path(response.path).resolve()
    work_root = Path(cfg.paths.work_dir).resolve()
    assert served.is_relative_to(work_root / "template-builder" / created["token"])


def test_get_source_page_rejects_traversal_token(tmp_path: Path) -> None:
    store, _cfg = _store_for(tmp_path)
    with pytest.raises(HTTPException) as ei:
        get_source_page("../../etc", 0, store=store)
    assert ei.value.status_code == 400


def test_get_source_page_404_for_unknown_token(tmp_path: Path) -> None:
    store, _cfg = _store_for(tmp_path)
    with pytest.raises(HTTPException) as ei:
        get_source_page("0" * 16, 0, store=store)
    assert ei.value.status_code == 404


def test_get_source_page_404_for_out_of_range(tmp_path: Path) -> None:
    src = make_digital_pdf(tmp_path / "sample.pdf")
    store, _cfg = _store_for(tmp_path)
    created = create_source(SourceRequest(path=str(src)), store=store)
    with pytest.raises(HTTPException) as ei:
        get_source_page(created["token"], 99, store=store)
    assert ei.value.status_code == 404


def test_delete_source_removes_session(tmp_path: Path) -> None:
    src = make_digital_pdf(tmp_path / "sample.pdf")
    store, cfg = _store_for(tmp_path)
    created = create_source(SourceRequest(path=str(src)), store=store)
    sess_dir = (
        Path(cfg.paths.work_dir) / "template-builder" / created["token"]
    )
    assert sess_dir.exists()
    out = delete_source(created["token"], store=store)
    assert out["deleted"] is True
    assert not sess_dir.exists()


def test_delete_source_rejects_invalid_token(tmp_path: Path) -> None:
    store, _cfg = _store_for(tmp_path)
    with pytest.raises(HTTPException) as ei:
        delete_source("../etc", store=store)
    assert ei.value.status_code == 400


# ----- preview -----------------------------------------------------------


def _example_template(template_id: str = "ex_v1") -> dict:
    return {
        "template_id": template_id,
        "jurisdiction": "ex",
        "version": "1.0",
        "signature": {
            "anchor_text": ["MOCK CRASH REPORT", "Officer"],
            "form_number_regex": None,
        },
        "regions": {
            "diagram": {
                "page": 0,
                "bbox_norm": [0.05, 0.10, 0.95, 0.50],
                "requires_redaction": True,
            },
            "narrative": {
                "page": 0,
                "bbox_norm": [0.05, 0.55, 0.95, 0.95],
                "anchor_start": "MOCK",
                "anchor_end": "Officer",
            },
        },
    }


def test_preview_returns_template_match_and_extractions(tmp_path: Path) -> None:
    src = make_digital_pdf(
        tmp_path / "sample.pdf",
        lines=["MOCK CRASH REPORT", "Officer Synthetic Test", "narrative body"],
    )
    store, cfg = _store_for(tmp_path)
    created = create_source(SourceRequest(path=str(src)), store=store)
    body = PreviewRequest(token=created["token"], template=_example_template())
    out = preview(body, store=store, config=cfg)
    assert "template_match" in out
    assert "diagram" in out
    assert "narrative" in out


def test_preview_422_on_invalid_template(tmp_path: Path) -> None:
    src = make_digital_pdf(tmp_path / "sample.pdf")
    store, cfg = _store_for(tmp_path)
    created = create_source(SourceRequest(path=str(src)), store=store)
    bad = _example_template()
    bad["regions"]["diagram"]["bbox_norm"] = [2, 2, 3, 3]  # invalid
    with pytest.raises(HTTPException) as ei:
        preview(
            PreviewRequest(token=created["token"], template=bad),
            store=store,
            config=cfg,
        )
    assert ei.value.status_code == 422


def test_preview_404_for_unknown_token(tmp_path: Path) -> None:
    store, cfg = _store_for(tmp_path)
    with pytest.raises(HTTPException) as ei:
        preview(
            PreviewRequest(token="0" * 16, template=_example_template()),
            store=store,
            config=cfg,
        )
    assert ei.value.status_code == 404


def test_preview_400_for_bad_token_shape(tmp_path: Path) -> None:
    store, cfg = _store_for(tmp_path)
    with pytest.raises(HTTPException) as ei:
        preview(
            PreviewRequest(token="../etc/passwd", template=_example_template()),
            store=store,
            config=cfg,
        )
    assert ei.value.status_code == 400


# ----- save --------------------------------------------------------------


def test_save_writes_validated_template(tmp_path: Path) -> None:
    _store_for(tmp_path)  # creates dirs
    cfg = AppConfig()
    cfg.paths.templates_dir = str(tmp_path / "templates")

    out = save_template(
        SaveRequest(
            jurisdiction="ex",
            template_id="ex_v1",
            template=_example_template(),
        ),
        config=cfg,
    )
    target = Path(out["path"])
    assert target.exists()
    parsed = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert parsed["template_id"] == "ex_v1"
    # Round-trips through the schema.
    from care.templates.schemas import TemplateSchema
    TemplateSchema.model_validate(parsed)


def test_save_rejects_template_id_mismatch(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.paths.templates_dir = str(tmp_path / "templates")
    template = _example_template(template_id="other_id")
    with pytest.raises(HTTPException) as ei:
        save_template(
            SaveRequest(
                jurisdiction="ex",
                template_id="ex_v1",
                template=template,
            ),
            config=cfg,
        )
    assert ei.value.status_code == 422


def test_save_refuses_overwrite_without_force(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.paths.templates_dir = str(tmp_path / "templates")
    save_template(
        SaveRequest(
            jurisdiction="ex",
            template_id="ex_v1",
            template=_example_template(),
        ),
        config=cfg,
    )
    with pytest.raises(HTTPException) as ei:
        save_template(
            SaveRequest(
                jurisdiction="ex",
                template_id="ex_v1",
                template=_example_template(),
            ),
            config=cfg,
        )
    assert ei.value.status_code == 409


def test_save_allows_overwrite_with_force(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.paths.templates_dir = str(tmp_path / "templates")
    save_template(
        SaveRequest(
            jurisdiction="ex",
            template_id="ex_v1",
            template=_example_template(),
        ),
        config=cfg,
    )
    out = save_template(
        SaveRequest(
            jurisdiction="ex",
            template_id="ex_v1",
            template=_example_template(),
            force=True,
        ),
        config=cfg,
    )
    assert out["validated"] is True
    assert Path(out["path"]).exists()


def test_save_rejects_invalid_jurisdiction_or_id(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.paths.templates_dir = str(tmp_path / "templates")
    for bad_id in ["BAD-ID", "../foo", "ok name", ""]:
        with pytest.raises(HTTPException) as ei:
            save_template(
                SaveRequest(
                    jurisdiction="ex",
                    template_id=bad_id,
                    template=_example_template(template_id=bad_id),
                ),
                config=cfg,
            )
        assert ei.value.status_code == 400, f"expected 400 for id={bad_id!r}"
    for bad_jur in ["../etc", "Bad/dir", "X X"]:
        with pytest.raises(HTTPException) as ei:
            save_template(
                SaveRequest(
                    jurisdiction=bad_jur,
                    template_id="ex_v1",
                    template=_example_template(),
                ),
                config=cfg,
            )
        assert ei.value.status_code == 400


def test_save_invalid_template_returns_422(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.paths.templates_dir = str(tmp_path / "templates")
    bad = _example_template()
    bad["regions"]["narrative"]["bbox_norm"] = [0.0, 0.0, 1.5, 0.5]  # > 1
    with pytest.raises(HTTPException) as ei:
        save_template(
            SaveRequest(
                jurisdiction="ex",
                template_id="ex_v1",
                template=bad,
            ),
            config=cfg,
        )
    assert ei.value.status_code == 422


def test_save_does_not_touch_export_dir(tmp_path: Path) -> None:
    """Builder must NEVER write into the export directory."""
    cfg = AppConfig()
    cfg.paths.export_dir = str(tmp_path / "exports")
    cfg.paths.templates_dir = str(tmp_path / "templates")
    Path(cfg.paths.export_dir).mkdir(parents=True, exist_ok=True)
    save_template(
        SaveRequest(
            jurisdiction="ex",
            template_id="ex_v1",
            template=_example_template(),
        ),
        config=cfg,
    )
    assert list(Path(cfg.paths.export_dir).rglob("*")) == []


def test_session_for_image_only_input_yields_zero_words(tmp_path: Path) -> None:
    """An image (no text layer) still loads; words are empty per page."""
    src = make_synthetic_image(tmp_path / "scan.png")
    store, _cfg = _store_for(tmp_path)
    created = create_source(SourceRequest(path=str(src)), store=store)
    assert created["page_count"] == 1
    assert all(p["words"] == [] for p in created["pages"])
