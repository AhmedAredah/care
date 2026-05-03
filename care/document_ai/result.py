"""Result dataclasses for document-AI / VLM providers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SpatialWord:
    text: str
    bbox: Optional[list[float]] = None
    confidence: Optional[float] = None


@dataclass
class SpatialTextResult:
    words: list[SpatialWord] = field(default_factory=list)
    can_map_to_image_coordinates: bool = False
    provider: str = ""


@dataclass
class MarkdownSection:
    heading: str = ""
    body: str = ""
    bbox: Optional[list[float]] = None


@dataclass
class MarkdownResult:
    markdown: str = ""
    sections: list[MarkdownSection] = field(default_factory=list)
    provider: str = ""


@dataclass
class CandidateRegion:
    label: str
    bbox: Optional[list[float]] = None
    confidence: Optional[float] = None


@dataclass
class RegionDetectionResult:
    regions: list[CandidateRegion] = field(default_factory=list)
    provider: str = ""


@dataclass
class DocumentQAResult:
    answer: str = ""
    confidence: Optional[float] = None
    provider: str = ""


@dataclass
class DocumentAIResult:
    spatial_text: Optional[SpatialTextResult] = None
    markdown: Optional[MarkdownResult] = None
    regions: Optional[RegionDetectionResult] = None
    qa: Optional[DocumentQAResult] = None
    provider_name: str = ""
    provider_version: str = ""
    warnings: list[str] = field(default_factory=list)
    generative: bool = True
    hallucination_risk: bool = True
    can_map_to_image_coordinates: bool = False
