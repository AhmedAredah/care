"""OpenAI provider integration tests.

The real ``openai`` SDK is not exercised in CI — we monkeypatch
``OpenAIProvider._build_client`` to inject a fake client that records
the request and returns a canned response. The tests prove:

- The request shape we send matches the OpenAI chat-completions API
  (model, messages, response_format, max_tokens, temperature).
- Vision requests inline the image as a base64 data URL (never a
  remote URL the API would have to fetch).
- Response parsing handles text + structured (JSON-schema) outputs.
- Empty/malformed responses surface as ``LLM_OUTPUT_UNMAPPED``.
- Usage statistics flow through to the manifest.
- ``requires_review`` is True on every result.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from care.core.errors import ConfigError, OfflineGuardError
from care.llm.providers.openai_provider import OpenAIProvider

# ---- fake OpenAI client ------------------------------------------------


@dataclass
class _FakeMessage:
    content: str | None


@dataclass
class _FakeChoice:
    message: _FakeMessage
    finish_reason: str = "stop"


@dataclass
class _FakeUsage:
    prompt_tokens: int = 12
    completion_tokens: int = 7
    total_tokens: int = 19

    def model_dump(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class _FakeResponse:
    choices: list[_FakeChoice]
    model: str = "gpt-4o-mini-2024-07-18"
    usage: _FakeUsage | None = field(default_factory=_FakeUsage)


class _FakeCompletions:
    def __init__(self, parent: _FakeOpenAI) -> None:
        self._parent = parent

    def create(self, **kwargs: Any) -> _FakeResponse:
        self._parent.last_request = kwargs
        if self._parent.next_response is not None:
            return self._parent.next_response
        # Default: echo the prompt as the response so tests can assert routing.
        text = "echo: " + str(kwargs["messages"][-1]["content"])[:64]
        return _FakeResponse(choices=[_FakeChoice(_FakeMessage(text))])


class _FakeChat:
    def __init__(self, parent: _FakeOpenAI) -> None:
        self.completions = _FakeCompletions(parent)


class _FakeOpenAI:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.last_request: dict[str, Any] | None = None
        self.next_response: _FakeResponse | None = None
        self.chat = _FakeChat(self)


@pytest.fixture
def fake_provider(monkeypatch):
    """Return a loaded OpenAIProvider with a fake client wired in."""
    fake = _FakeOpenAI(api_key="sk-test")

    monkeypatch.setattr(
        OpenAIProvider, "_build_client", staticmethod(lambda config: fake)
    )
    provider = OpenAIProvider()
    provider.load(
        {
            "api_key": "sk-PLAIN-TEST-NEVER-LOG",
            "acknowledged_external_data_egress": True,
            "model": "gpt-4o-mini",
            "_app_config": {"offline_enabled": False},
        }
    )
    # Hand the fake back to the test so it can inspect last_request /
    # set next_response.
    return provider, fake


# ---- generate_text -----------------------------------------------------


def test_generate_text_sends_user_message(fake_provider) -> None:
    provider, fake = fake_provider
    fake.next_response = _FakeResponse(
        choices=[_FakeChoice(_FakeMessage("OK"))]
    )
    result = provider.generate_text("Say OK.")
    assert result.text == "OK"
    assert result.provider == "openai"
    assert result.model == "gpt-4o-mini-2024-07-18"
    assert result.finish_reason == "stop"
    assert result.usage["total_tokens"] == 19
    assert result.requires_review is True

    request = fake.last_request
    assert request["model"] == "gpt-4o-mini"
    assert request["messages"] == [{"role": "user", "content": "Say OK."}]
    assert "response_format" not in request


def test_generate_text_with_system_prompt(fake_provider) -> None:
    provider, fake = fake_provider
    fake.next_response = _FakeResponse(
        choices=[_FakeChoice(_FakeMessage("ok"))]
    )
    provider.generate_text("Hi", system="You are concise.")
    msgs = fake.last_request["messages"]
    assert msgs[0] == {"role": "system", "content": "You are concise."}
    assert msgs[-1] == {"role": "user", "content": "Hi"}


def test_generate_text_with_json_schema_emits_structured(fake_provider) -> None:
    provider, fake = fake_provider
    fake.next_response = _FakeResponse(
        choices=[_FakeChoice(_FakeMessage('{"label": "diagram", "score": 0.9}'))]
    )
    schema = {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "score": {"type": "number"},
        },
        "required": ["label", "score"],
        "additionalProperties": False,
    }
    result = provider.generate_text("classify", json_schema=schema)
    assert result.structured == {"label": "diagram", "score": 0.9}
    assert result.text == '{"label": "diagram", "score": 0.9}'

    request = fake.last_request
    rf = request["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["schema"] == schema
    assert rf["json_schema"]["strict"] is True


def test_generate_text_malformed_json_marks_unmapped(fake_provider) -> None:
    provider, fake = fake_provider
    fake.next_response = _FakeResponse(
        choices=[_FakeChoice(_FakeMessage("not json at all"))]
    )
    result = provider.generate_text(
        "schema", json_schema={"type": "object", "properties": {}}
    )
    assert result.structured is None
    assert "LLM_OUTPUT_UNMAPPED" in result.warnings


def test_generate_text_empty_choices_marks_unmapped(fake_provider) -> None:
    provider, fake = fake_provider
    fake.next_response = _FakeResponse(choices=[])
    result = provider.generate_text("anything")
    assert result.text is None
    assert result.finish_reason == "empty"
    assert "LLM_OUTPUT_UNMAPPED" in result.warnings


# ---- analyze_image -----------------------------------------------------


def _png_path(tmp_path: Path) -> Path:
    p = tmp_path / "diagram.png"
    Image.new("RGB", (8, 8), "white").save(p, format="PNG")
    return p


def test_analyze_image_inlines_data_url(tmp_path: Path, fake_provider) -> None:
    provider, fake = fake_provider
    img = _png_path(tmp_path)
    fake.next_response = _FakeResponse(
        choices=[_FakeChoice(_FakeMessage("looks like a diagram"))]
    )

    result = provider.analyze_image(str(img), "What's in this image?")
    assert "diagram" in (result.text or "")

    user_content = fake.last_request["messages"][-1]["content"]
    assert isinstance(user_content, list)
    assert user_content[0] == {"type": "text", "text": "What's in this image?"}
    image_part = user_content[1]
    assert image_part["type"] == "image_url"
    url = image_part["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    # Decode and verify it round-trips a real PNG header.
    encoded = url.split(",", 1)[1]
    raw = base64.b64decode(encoded)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_analyze_image_missing_file_raises(tmp_path: Path, fake_provider) -> None:
    provider, _ = fake_provider
    with pytest.raises(FileNotFoundError):
        provider.analyze_image(str(tmp_path / "ghost.png"), "describe")


# ---- safety / offline / config -----------------------------------------


def test_load_blocked_in_offline_mode(monkeypatch) -> None:
    """Even with a valid api key, offline mode short-circuits load."""
    monkeypatch.setattr(
        OpenAIProvider, "_build_client", staticmethod(lambda c: _FakeOpenAI())
    )
    provider = OpenAIProvider()
    with pytest.raises(OfflineGuardError):
        provider.load(
            {
                "api_key": "sk-x",
                "acknowledged_external_data_egress": True,
                "_app_config": {"offline_enabled": True},
            }
        )


def test_load_requires_egress_acknowledgement(monkeypatch) -> None:
    monkeypatch.setattr(
        OpenAIProvider, "_build_client", staticmethod(lambda c: _FakeOpenAI())
    )
    provider = OpenAIProvider()
    with pytest.raises(ConfigError, match="acknowledged_external_data_egress"):
        provider.load(
            {
                "api_key": "sk-x",
                "_app_config": {"offline_enabled": False},
            }
        )


def test_manifest_redacts_api_key(fake_provider) -> None:
    provider, _ = fake_provider
    manifest = provider.get_model_manifest()
    blob = json.dumps(manifest)
    assert "sk-PLAIN-TEST-NEVER-LOG" not in blob
    assert manifest["config"]["api_key"] == "***REDACTED***"
    assert manifest["sends_data_external"] is True
    assert manifest["safe_for_export_decision"] is False
    assert manifest["safe_for_image_redaction"] is False


def test_generate_text_unloaded_raises() -> None:
    provider = OpenAIProvider()
    with pytest.raises(RuntimeError, match="not loaded"):
        provider.generate_text("hi")


# ---- CLI llm-test command -----------------------------------------------


def test_cli_llm_test_with_mock_provider(capsys, monkeypatch, tmp_path) -> None:
    """The CLI command exercises the same provider plumbing operators
    use to verify a real key. The mock_llm provider has no network
    surface, so this proves the CLI wiring without any vendor SDK."""
    from care.cli.main import run

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "llm:\n  enabled: true\n  providers:\n    mock_llm:\n      enabled: true\n      fixture:\n        text: 'pong'\n",
        encoding="utf-8",
    )
    rc = run(
        [
            "llm-test",
            "mock_llm",
            "--prompt",
            "ping",
            "--config",
            str(cfg_path),
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["text"] == "pong"
    assert out["provider"] == "mock_llm"
    assert out["requires_review"] is True


def test_cli_llm_test_redacts_config_in_show_config(
    capsys, monkeypatch, tmp_path
) -> None:
    """When the operator passes --show-config the CLI must NOT echo
    the raw api_key in stdout."""
    from care.cli.main import run

    monkeypatch.setattr(
        OpenAIProvider, "_build_client", staticmethod(lambda c: _FakeOpenAI())
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "offline:\n  enabled: false\nllm:\n  enabled: true\n",
        encoding="utf-8",
    )
    rc = run(
        [
            "llm-test",
            "openai",
            "--prompt",
            "ping",
            "--api-key",
            "sk-MUST-NOT-LEAK",
            "--acknowledge-egress",
            "--show-config",
            "--config",
            str(cfg_path),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "sk-MUST-NOT-LEAK" not in out
    assert "***REDACTED***" in out
