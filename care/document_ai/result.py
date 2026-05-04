"""Result dataclasses for document-AI / VLM providers."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SpatialWord:
    text: str
    bbox: list[float] | None = None
    confidence: float | None = None


@dataclass
class SpatialTextResult:
    words: list[SpatialWord] = field(default_factory=list)
    can_map_to_image_coordinates: bool = False
    provider: str = ""


@dataclass
class MarkdownSection:
    heading: str = ""
    body: str = ""
    bbox: list[float] | None = None


@dataclass
class MarkdownResult:
    markdown: str = ""
    sections: list[MarkdownSection] = field(default_factory=list)
    provider: str = ""


@dataclass
class CandidateRegion:
    label: str
    bbox: list[float] | None = None
    confidence: float | None = None


@dataclass
class RegionDetectionResult:
    regions: list[CandidateRegion] = field(default_factory=list)
    provider: str = ""


@dataclass
class DocumentQAResult:
    answer: str = ""
    confidence: float | None = None
    provider: str = ""


@dataclass
class DocumentAIResult:
    spatial_text: SpatialTextResult | None = None
    markdown: MarkdownResult | None = None
    regions: RegionDetectionResult | None = None
    qa: DocumentQAResult | None = None
    provider_name: str = ""
    provider_version: str = ""
    warnings: list[str] = field(default_factory=list)
    generative: bool = True
    hallucination_risk: bool = True
    can_map_to_image_coordinates: bool = False
