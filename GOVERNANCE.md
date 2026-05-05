# care Development Contract

This document is the governing architecture, security, privacy, offline-mode, plugin, and export contract for this repository.

All code, tests, documentation, packaging scripts, frontend assets, model integrations, and provider plugins must comply with this document.

If any user request conflicts with this contract, do not implement the conflicting request. Explain the conflict and propose a compliant alternative.

This contract is enforced by:
- CLAUDE.md
- .claude/rules/*
- .claude/settings.json
- .claude/hooks/*
- scripts/governance_check.py
- tests/governance/*
- CI

You are an expert Python software architect, senior backend engineer, privacy engineer, and full-stack developer.

Your task is to build a production-quality open-source repository named:

care

The repository must implement a fully offline, inspectable, auditable, plugin-based tool that helps Departments of Transportation process police crash report PDFs/images, detect the exact report template/version, extract the crash/incident diagram and narrative, detect and remove personally identifiable information, and export only privacy-safe public research artifacts.

This tool is intended for DOTs and similar public agencies. They may process highly sensitive crash reports in air-gapped environments. Therefore, the default application must make zero internet connections, include no telemetry, include no analytics, and must not download models, dependencies, fonts, JavaScript, CSS, or any other assets at runtime.

The architecture must be plugin-based. This is non-negotiable.

The core pipeline must not depend directly on a single OCR model, a single PII model, a single PDF library, a single VLM/document model, or a single redaction strategy. The core pipeline must depend only on interfaces, registries, local configuration, and normalized intermediate representations.

The most important plugin categories are:

1. Traditional OCR engines.
2. VLM/LLM-based OCR and document parsing models.
3. PII detection models.
4. PII redaction/anonymization strategies.
5. Template detectors.
6. PDF/image backends.
7. Exporters.
8. QA/review policies.

The tool must support traditional OCR engines such as PaddleOCR and Tesseract, and it must also support multimodal/VLM document models such as Kosmos-2.5 or future local document-reading LLMs as plugins.

Do not hard-code PaddleOCR, Tesseract, Presidio, Piiranha, Kosmos-2.5, or any other model into the core pipeline. They must be plugins.

============================================================
PROJECT MISSION
============================================================

Build a local-first, offline-first, open-source crash report extraction and de-identification tool.

Given a folder containing crash reports in PDF, scanned PDF, image-only PDF, PNG, JPG, JPEG, or TIFF format, the app must:

1. Read each report.
2. Inspect each file.
3. Determine whether the report has a usable native PDF text layer.
4. Render pages to images when needed.
5. Run local OCR and/or local VLM document parsing through plugins.
6. Normalize all document text/layout results into a canonical DocumentIR.
7. Detect the exact crash report template/version when possible.
8. Extract the crash/incident diagram.
9. Extract the crash narrative.
10. Detect PII in extracted text and diagram regions.
11. Redact or anonymize PII.
12. Export a public-safe folder containing only redacted diagrams, redacted narratives, and metadata manifests.
13. Never export the original report by default.
14. Never export unredacted narrative by default.
15. Fail closed when confidence is too low.
16. Route uncertain cases to human review.

The tool should help DOTs make crash report diagrams and narratives publicly available for researchers while reducing privacy risk.

============================================================
CORE PRODUCT PRINCIPLES
============================================================

The application must follow these principles:

- Offline-first.
- Local-only processing.
- Open-source.
- Auditable.
- Reproducible builds.
- Plugin-based architecture.
- No hidden network calls.
- No telemetry.
- No analytics.
- No auto-update checks.
- No runtime dependency downloads.
- No runtime model downloads.
- No external frontend assets.
- No CDN.
- No Google Fonts.
- No cloud APIs in the default build.
- No raw PII in logs.
- No original PDF in public exports.
- No unredacted narrative in public exports.
- Fail closed.
- Human-reviewable.
- Privacy-first.
- DOT-verifiable.
- Installer must be usable in air-gapped environments.

A DOT should be able to:

1. Inspect the source code.
2. Build the app from source.
3. Install it without internet.
4. Disable network access.
5. Process reports locally.
6. Verify that the installer matches the reviewed source.
7. Verify that no backdoor, telemetry, or external exfiltration exists.
8. Replace OCR, PII, or VLM providers with their own internal plugins.

============================================================
TECHNOLOGY STACK
============================================================

Use:

- Backend: Python.
- API framework: FastAPI.
- CLI: Typer or argparse.
- Frontend: plain HTML, CSS, and JavaScript.
- Data models: Pydantic or dataclasses.
- Image processing: Pillow and/or OpenCV.
- PDF rendering: pypdfium2 or another permissive-license local PDF renderer.
- PDF text extraction: pypdf, pdfminer.six, pdfplumber, or equivalent permissive/default-safe libraries.
- Default OCR plugin: PaddleOCR, loaded only from local model paths.
- Fallback OCR plugin: Tesseract, loaded only from local tessdata paths.
- Default PII plugin chain: regex/custom recognizers plus Presidio.
- Optional PII plugin: Piiranha, disabled by default and clearly marked as license-review-required.
- Optional VLM/document-AI plugin: Kosmos-2.5, disabled by default and loaded only from local model paths.
- Testing: pytest.
- Build/package scripts: shell scripts and/or Python scripts.

Do not use React, Vue, Angular, or frontend build systems unless absolutely necessary. Prefer simple static HTML/CSS/JS.

Do not use CDNs, remote fonts, remote stylesheets, remote images, or external JavaScript.

Avoid AGPL libraries in the default runtime. If an AGPL library is useful, isolate it as an optional plugin and clearly document the licensing implications.

============================================================
LICENSE AND MODEL GOVERNANCE
============================================================

The repo itself is released under Apache-2.0 (see ``LICENSE`` and ``NOTICE``). The Apache-2.0 patent grant and NOTICE-propagation rules apply to all distributions, including the Windows installer artifacts.

Every third-party dependency and model must be tracked in a license manifest.

Every plugin must expose:

- provider name
- provider version
- provider type
- model name
- model version
- model path
- model checksums
- license
- whether it requires network access
- whether it is enabled by default
- whether it is safe for public-sector/offline use
- whether it is generative
- whether it may hallucinate
- whether it can provide bounding boxes
- whether its output can be used for image redaction

Important rule about Piiranha:

- Do not make Piiranha mandatory.
- Do not make Piiranha the default PII engine.
- Implement only an optional provider skeleton for Piiranha.
- Disable it by default.
- Require explicit config enablement.
- Add a license warning in config and docs.
- Do not download Piiranha at runtime.
- Load only from local files if enabled.
- Mark it as “requires legal/license review before DOT deployment.”

Important rule about Kosmos-2.5 and other VLMs:

- Do not make Kosmos-2.5 mandatory.
- Do not make Kosmos-2.5 the default OCR engine.
- Implement it as an optional VLM/document-AI plugin.
- Disable it by default.
- Load only from local files if enabled.
- Treat generative output as lower trust than exact OCR unless reviewed.
- Never use VLM-only text for image redaction unless it has reliable bounding boxes.
- Never allow VLM output to silently override PII detection or redaction.

============================================================
REPOSITORY STRUCTURE
============================================================

The canonical repository layout is:

repo-root/
  README.md
  LICENSE
  pyproject.toml
  uv.lock
  .gitignore
  config.yaml

  care/
    __init__.py
    main.py

    api/
      __init__.py
      routes_health.py
      routes_jobs.py
      routes_reports.py
      routes_exports.py
      routes_plugins.py
      routes_review.py
      routes_offline.py

    cli/
      __init__.py
      main.py
      desktop.py
      shortcut.py

    core/
      __init__.py
      config.py
      logging.py
      errors.py
      security.py
      offline_guard.py
      governance_guard.py
      plugin_helpers.py
      paths.py
      constants.py

    ingestion/
      __init__.py
      scanner.py
      file_manifest.py
      hashing.py
      supported_files.py

    pdf/
      __init__.py
      base.py
      pypdfium2_backend.py
      text_layer.py
      renderer.py
      inspection.py

    ocr/
      __init__.py
      base.py
      registry.py
      result.py
      providers/
        __init__.py
        mock_ocr_provider.py
        paddleocr_provider.py
        tesseract_provider.py
        onnxtr_provider.py
        noop_provider.py

    document_ai/
      __init__.py
      base.py
      registry.py
      result.py
      providers/
        __init__.py
        mock_vlm_provider.py
        kosmos25_provider.py
        layoutlm_provider.py

    document_ir/
      __init__.py
      models.py
      builder.py
      reading_order.py
      serialization.py
      reconcile.py
      provenance.py

    templates/
      __init__.py
      registry.py
      detector.py
      scoring.py
      schemas.py
      loader.py

    extraction/
      __init__.py
      diagram_extractor.py
      narrative_extractor.py
      region_extractor.py
      anchors.py

    pii/
      __init__.py
      base.py
      registry.py
      entities.py
      policies.py
      merge.py
      _hf_token_classification.py
      providers/
        __init__.py
        regex_provider.py
        presidio_provider.py
        optional_piiranha_provider.py
        roberta_ner_provider.py
        mock_pii_provider.py
      recognizers/
        __init__.py
        vin.py
        license_plate.py
        driver_license.py
        phone.py
        email.py
        address.py
        date_of_birth.py
        report_number.py
        case_number.py
        insurance_policy.py
        person_name.py
        signature.py
        medical_info.py

    llm/
      __init__.py
      base.py
      registry.py
      safety.py
      providers/
        __init__.py
        openai_provider.py
        anthropic_provider.py
        gemini_provider.py
        hf_local_provider.py
        ollama_provider.py

    redaction/
      __init__.py
      text_redactor.py
      image_redactor.py
      bbox_mapper.py
      policies.py
      audit.py

    export/
      __init__.py
      exporter.py
      manifest.py
      writers.py

    review/
      __init__.py
      qa_flags.py
      confidence.py
      review_models.py

    workers/
      __init__.py
      pipeline.py
      job_store.py
      status.py

    audit/
      __init__.py
      events.py
      sbom_notes.py

    services/
      __init__.py

  frontend/
    index.html
    css/
      app.css
    js/
      app.js
      api.js
      review.js
      plugins.js
      utils.js

  templates/
    README.md
    example_state/
      example_template_v1.yaml

  models/
    README.md
    ocr/
      README.md
      paddleocr/
        README.md
      tesseract/
        README.md
    pii/
      README.md
      presidio/
        README.md
      piiranha/
        README.md
      roberta-large-ner-english/
        README.md
    document_ai/
      README.md
      kosmos-2.5/
        README.md
      layoutlm/
        README.md

  tests/
    unit/
    integration/
    api/
    offline/
    governance/
    _fixtures.py
    conftest.py

  docs/
    architecture.md
    plugin-system.md
    offline-mode.md
    security.md
    no-network-guarantee.md
    template-authoring.md
    pii-policy.md
    redaction.md
    document-ai-plugins.md
    evaluation.md
    deployment.md
    deployment-windows.md
    packaging.md
    license-and-model-governance.md

  scripts/
    build_wheelhouse.sh
    verify_no_network.py
    generate_sbom.sh
    package_offline_installer.sh
    compute_model_checksums.py
    scan_frontend_external_assets.py
    governance_check.py
    codeql_dismiss_path_injection.sh
    generate_icon.py

The Python package is named ``care`` and lives at the repo root (no ``backend/app/`` wrapper). Plugin categories may grow over time — additions appear under the matching ``care/<category>/providers/`` directory, with each provider declaring its own model dir under ``models/<category>/<provider>/`` per :ref:`License and Model Governance`.

Do not include real crash reports or real PII in the repository. Use synthetic fixtures only.

============================================================
CANONICAL DOCUMENTIR
============================================================

Implement a provider-neutral intermediate representation called DocumentIR.

All OCR providers, PDF text-layer extractors, and VLM/document-AI providers must output or be converted into this common format.

No downstream pipeline stage may depend directly on PaddleOCR, Tesseract, Kosmos, Presidio, Piiranha, or any other specific provider.

DocumentIR must include:

- document_id
- source_file_name
- source_sha256
- file_type
- created_at
- pages
- provenance
- extraction warnings

Each page must include:

- page_index
- width
- height
- rotation
- text_source
- rendered_image_path if available
- blocks
- lines
- words
- regions
- warnings

Each word/token must include:

- id
- text
- bbox
- confidence
- source
- source_provider_type
- source_provider_version
- alternative_sources
- provenance
- can_map_to_image_coordinates

Example:

{
  "document_id": "sha256-of-source-file",
  "source_file_name": "example.pdf",
  "source_sha256": "...",
  "file_type": "pdf",
  "pages": [
    {
      "page_index": 0,
      "width": 2550,
      "height": 3300,
      "rotation": 0,
      "text_source": "ocr",
      "blocks": [],
      "lines": [],
      "words": [
        {
          "id": "p0_w00001",
          "text": "JOHN",
          "bbox": [100, 200, 180, 230],
          "confidence": 0.97,
          "source": "paddleocr",
          "source_provider_type": "traditional_ocr",
          "source_provider_version": "local",
          "alternative_sources": [
            {
              "provider": "kosmos25",
              "text": "JOHN",
              "confidence": null,
              "bbox": [102, 198, 181, 232]
            }
          ],
          "can_map_to_image_coordinates": true
        }
      ],
      "regions": []
    }
  ]
}

Use Pydantic models or dataclasses for DocumentIR.

Implement serialization and deserialization to JSON.

============================================================
PLUGIN ARCHITECTURE
============================================================

Implement formal plugin interfaces using abstract base classes or protocols.

All plugins must have:

- name
- version
- provider_type
- requires_network
- enabled_by_default
- load(config)
- healthcheck()
- get_model_manifest()
- close()

The plugin registry must:

- Load only local declared plugins.
- Never download plugins.
- Never fetch code from the internet.
- Reject unknown plugin names unless explicitly configured.
- Support dependency checks.
- Support provider health checks.
- Support model manifest export.
- Support disabled-by-default optional providers.

============================================================
OCR PLUGIN INTERFACE
============================================================

Create:

care/ocr/base.py

Implement:

class OCRProvider:
    name: str
    version: str
    provider_type: str = "traditional_ocr"
    requires_network: bool
    supports_pdf: bool
    supports_image: bool
    supports_word_bboxes: bool
    supports_line_bboxes: bool
    supports_confidence: bool

    def load(self, config) -> None:
        ...

    def process_page_image(self, image, page_context) -> OCRResult:
        ...

    def healthcheck(self) -> ProviderHealth:
        ...

    def get_model_manifest(self) -> dict:
        ...

OCRResult must include:

- words
- lines
- blocks
- confidence
- provider name
- provider version
- warnings
- can_map_to_image_coordinates

Implement these OCR providers:

1. mock_ocr_provider.py
   - Used for tests.
   - Deterministic output.
   - No external dependencies.

2. paddleocr_provider.py
   - Disabled unless configured or enabled as default.
   - Must load from local model paths.
   - Must not download models.
   - Must not use remote paths.
   - Must support det_model_dir, rec_model_dir, cls_model_dir.
   - Must fail closed if model paths are missing in offline mode.
   - Must produce word-level or line-level bounding boxes where possible.

3. tesseract_provider.py
   - Uses local Tesseract installation or local packaged binary.
   - Uses local tessdata path.
   - Must not download language data.
   - Must expose OCR confidence and boxes when available.

4. noop_provider.py
   - Returns empty OCR.
   - Useful for digital PDFs with native text only.

============================================================
DOCUMENT-AI / VLM PLUGIN INTERFACE
============================================================

The system must support VLM/LLM-based OCR and document parsing models as plugins.

Examples include:

- Kosmos-2.5
- Kosmos-2.5-Chat
- GOT-OCR-style models
- Nougat-style image-to-markdown models
- Donut-style document understanding models
- PaddleOCR-VL-style models
- Layout-aware VLMs
- Future local multimodal document models

Do not assume OCR means only traditional OCR.

Create:

care/document_ai/base.py

Implement:

class DocumentAIProvider:
    name: str
    version: str
    provider_type: str = "vlm_document_parser"
    requires_network: bool
    supports_image_to_text: bool
    supports_image_to_markdown: bool
    supports_spatial_text: bool
    supports_region_detection: bool
    supports_question_answering: bool
    supports_confidence: bool
    generative_model: bool
    hallucination_risk: bool

    def load(self, config) -> None:
        ...

    def process_page_image(self, image, page_context, task: str) -> DocumentAIResult:
        ...

    def image_to_spatial_text(self, image, page_context) -> SpatialTextResult:
        ...

    def image_to_markdown(self, image, page_context) -> MarkdownResult:
        ...

    def detect_regions(self, image, page_context) -> RegionDetectionResult:
        ...

    def ask_document_question(self, image, question: str, page_context) -> DocumentQAResult:
        ...

    def healthcheck(self) -> ProviderHealth:
        ...

    def get_model_manifest(self) -> dict:
        ...

DocumentAIResult must be convertible into DocumentIR.

Important VLM/document-AI rules:

- If a VLM returns text without bounding boxes, mark it as low spatial confidence.
- If a VLM returns markdown but no exact word coordinates, use it only for narrative extraction assistance, section detection, or reading-order hints.
- If VLM text cannot be mapped to image coordinates, it must not drive image redaction.
- If a VLM returns bounding boxes, normalize them into the DocumentIR coordinate system.
- If VLM output conflicts with traditional OCR or native PDF text, preserve both outputs and flag the conflict for QA.
- If a VLM output is generative and lacks reliable confidence scores, treat it as lower confidence.
- VLMs must never silently override PII detection or redaction decisions.
- VLMs may propose candidate narrative or diagram regions, but final export must still obey confidence and review policies.
- VLM-generated summaries or paraphrases must not be used as final narratives. Prefer verbatim extraction.

Implement these document-AI providers:

1. mock_vlm_provider.py
   - Used for tests.
   - Deterministic output.
   - Can simulate markdown, spatial OCR, conflicts, hallucinated text, and missing bounding boxes.

2. kosmos25_provider.py
   - Optional.
   - Disabled by default.
   - Local-only.
   - Must load from a local model path only.
   - Must not use a Hugging Face repo name at runtime in offline mode.
   - Must use local_files_only=True.
   - Must respect HF_HUB_OFFLINE=1.
   - Must respect TRANSFORMERS_OFFLINE=1.
   - Must respect HF_DATASETS_OFFLINE=1.
   - Must fail closed if files are missing.
   - Must expose two tasks:
     - spatial OCR task
     - markdown/document parsing task
   - Must convert spatial OCR output to DocumentIR words/lines/blocks when possible.
   - Must convert markdown output to structured sections when possible.
   - Must mark hallucination risk in the provider manifest.
   - Must mark whether output has usable bounding boxes.
   - Must mark whether output is safe for redaction mapping.
   - Must include model license, model path, revision/hash, and local file checksums in the model manifest.

Set these environment variables in offline mode:

HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_DATASETS_OFFLINE=1
HF_HUB_DISABLE_TELEMETRY=1
HF_HUB_DISABLE_IMPLICIT_TOKEN=1

When loading any Hugging Face/Transformers model:

- Use a local filesystem path, not a remote model ID.
- Pass local_files_only=True.
- Fail closed if any file is missing.
- Never fall back to internet download.
- Record model path and checksums in the manifest.

============================================================
PII PLUGIN INTERFACE
============================================================

Create:

care/pii/base.py

Implement:

class PIIDetectionProvider:
    name: str
    version: str
    provider_type: str = "pii_detector"
    requires_network: bool
    supported_entities: list[str]
    supports_offsets: bool
    supports_bboxes: bool
    supports_confidence: bool

    def load(self, config) -> None:
        ...

    def detect_text(self, text, context) -> list[PIIEntity]:
        ...

    def detect_document_ir(self, document_ir, regions=None) -> list[PIIEntity]:
        ...

    def healthcheck(self) -> ProviderHealth:
        ...

    def get_model_manifest(self) -> dict:
        ...

PIIEntity must include:

- entity_type
- text
- normalized_text if appropriate
- start_offset
- end_offset
- page_index
- bbox if available
- confidence
- provider
- detection_reason
- can_map_to_image_coordinates
- requires_review

Default PII provider chain:

1. regex_provider
2. presidio_provider

Optional disabled-by-default provider:

3. optional_piiranha_provider

The PII pipeline must support provider chaining and merging. It must deduplicate overlapping entities and preserve all provider evidence.

Detect at least these PII types:

- PERSON_NAME
- ADDRESS
- PHONE_NUMBER
- EMAIL
- DATE_OF_BIRTH
- DRIVER_LICENSE
- LICENSE_PLATE
- VIN
- INSURANCE_POLICY
- CASE_NUMBER
- REPORT_NUMBER
- SIGNATURE
- MEDICAL_INFO
- WITNESS_INFO
- VEHICLE_OWNER_INFO
- SSN if present
- VEHICLE_REGISTRATION if present
- FULL_FACE_IMAGE if future image recognizer supports it

Implement custom recognizers for crash-report-specific PII:

- VIN
- license plate
- driver license
- phone
- email
- address
- date of birth
- report/case number
- insurance policy
- signature labels
- medical information keywords
- witness/owner fields

PII rules:

- Prioritize recall over precision.
- False positives are acceptable.
- False negatives are dangerous.
- If any detector finds PII, redact it unless policy explicitly excludes it.
- If PII is detected but cannot be mapped to an image coordinate, require review before exporting diagram.
- Do not log raw PII.
- Do not store raw PII in audit logs.
- Public exports must contain only redacted/anonymized content.

============================================================
PII REDACTION INTERFACE
============================================================

Create:

care/redaction/

Implement:

class RedactionProvider:
    name: str
    version: str
    provider_type: str = "redactor"
    requires_network: bool

    def redact_text(self, text, entities, policy) -> RedactedTextResult:
        ...

    def redact_image(self, image, entities_with_bboxes, policy) -> RedactedImageResult:
        ...

Text redaction:

- Replace PII with typed placeholders:
  - [PERSON_NAME]
  - [ADDRESS]
  - [PHONE_NUMBER]
  - [EMAIL]
  - [DATE_OF_BIRTH]
  - [DRIVER_LICENSE]
  - [LICENSE_PLATE]
  - [VIN]
  - [INSURANCE_POLICY]
  - [CASE_NUMBER]
  - [REPORT_NUMBER]
  - [SIGNATURE]
  - [MEDICAL_INFO]
  - [WITNESS_INFO]
  - [VEHICLE_OWNER_INFO]
- Preserve enough narrative utility for research.
- Do not store unredacted narrative in public export.

Image redaction:

- Use pixel-level masking on the exported diagram image.
- Do not rely on visual PDF overlays.
- Redact only using reliable bounding boxes.
- Expand redaction boxes slightly to cover OCR coordinate uncertainty.
- If PII exists but cannot be mapped to boxes, require human review.
- Do not export diagram if PII risk is unresolved.

============================================================
PDF / IMAGE BACKEND INTERFACE
============================================================

Create:

care/pdf/base.py

Implement:

class PDFImageBackend:
    name: str
    version: str
    provider_type: str = "pdf_image_backend"
    requires_network: bool

    def inspect_file(self, file_path) -> FileInspection:
        ...

    def extract_text_layer(self, file_path) -> DocumentIR:
        ...

    def render_pages(self, file_path, output_dir, dpi) -> list[RenderedPage]:
        ...

FileInspection must include:

- file type
- page count
- page dimensions
- whether PDF has text layer
- whether PDF appears image-only
- whether OCR is required
- rotation
- warnings

Use pypdfium2 or equivalent as the default renderer.

Avoid producing redacted PDFs in the MVP. Public export should consist of redacted image crops, redacted narrative text/JSON, manifests, and QA reports.

============================================================
TEMPLATE REGISTRY AND TEMPLATE DETECTION
============================================================

Templates must be stored as YAML files.

Create:

templates/example_state/example_template_v1.yaml

Example:

template_id: example_state_crash_v1
jurisdiction: EXAMPLE
agency: Example DOT
version: "1.0"
description: Synthetic example crash report template
signature:
  anchor_text:
    - "Example Crash Report"
    - "Narrative"
    - "Diagram"
  form_number_regex: "EX-CR-[0-9]+"
layout:
  page_count_min: 1
  page_count_max: 3
regions:
  diagram:
    page: 0
    bbox_norm: [0.05, 0.15, 0.95, 0.55]
    requires_redaction: true
  narrative:
    page: 0
    anchor_start: "Narrative"
    anchor_end: "Officer"
    bbox_norm: [0.05, 0.55, 0.95, 0.85]

Template detector must combine:

- native PDF text anchors
- traditional OCR anchors
- VLM spatial text anchors
- VLM markdown section headers
- form number regex
- page count
- layout similarity
- known region plausibility
- visual/layout fingerprint if implemented
- OCR confidence
- final confidence score

Template detector must return:

- template_id
- version
- confidence
- evidence
- warnings
- requires_review

If confidence is below threshold, return UNKNOWN.

Unknown templates must not be auto-exported.

If the template is detected only by VLM output and traditional OCR/native text do not support the match, require review.

============================================================
DIAGRAM EXTRACTION
============================================================

Create:

care/extraction/diagram_extractor.py

The diagram extractor must support:

- template-defined normalized bounding boxes
- anchor-based regions
- VLM-suggested candidate diagram regions as secondary evidence
- confidence scoring
- QA warnings

Diagram extraction rules:

- Extract diagram as an image crop from the rendered page.
- Avoid including surrounding PII-heavy form fields.
- Apply image redaction to any PII inside the crop.
- If the diagram region is uncertain, require review.
- If PII may be present but cannot be mapped to coordinates, require review.
- Do not export unredacted diagram.

============================================================
NARRATIVE EXTRACTION
============================================================

Create:

care/extraction/narrative_extractor.py

The narrative extractor must support:

- template-defined bounding boxes
- anchor_start / anchor_end
- native PDF text
- OCR token extraction
- VLM markdown section extraction
- hybrid extraction
- reading-order correction
- confidence scoring
- QA warnings

Narrative extraction rules:

- Prefer verbatim extraction over summaries.
- Do not allow a VLM to summarize or rewrite the narrative for public output.
- If VLM markdown improves section detection, use it as a candidate signal.
- The final narrative must include provenance.
- If narrative boundaries are uncertain, require review.
- Redact PII from the final narrative.
- Do not export unredacted narrative.

============================================================
OCR / VLM RECONCILIATION
============================================================

Create:

care/document_ir/reconcile.py

The reconciler must merge:

1. Native PDF text-layer tokens.
2. Traditional OCR tokens.
3. VLM spatial OCR text.
4. VLM markdown sections.
5. Template region hints.

The reconciler must:

- Prefer exact native PDF text when reliable.
- Prefer traditional OCR for word-level redaction boxes when confidence is good.
- Use VLM markdown to improve reading order and section detection.
- Use VLM output to help identify narrative boundaries.
- Use VLM output to help identify diagram regions only as candidate evidence.
- Never use VLM-only text for final public export unless review/confidence policy allows it.
- Flag conflicts between OCR and VLM output.
- Preserve provenance for every token, section, and region.
- Mark whether each extracted text item can be mapped back to image coordinates.

QA warnings must be emitted for:

- VLM_USED_FOR_EXTRACTION
- VLM_USED_FOR_TEMPLATE_DETECTION
- VLM_OUTPUT_CONFLICTS_WITH_OCR
- VLM_OUTPUT_HAS_NO_BBOXES
- VLM_PII_NOT_MAPPABLE_TO_IMAGE
- VLM_GENERATIVE_OUTPUT_REQUIRES_REVIEW
- VLM_MODEL_NOT_BENCHMARKED_FOR_THIS_TEMPLATE

============================================================
PROCESSING PIPELINE
============================================================

Create:

care/workers/pipeline.py

Pipeline stages:

1. Ingestion
   - Walk input directory.
   - Accept PDF, PNG, JPG, JPEG, TIFF.
   - Compute SHA-256 for each source file.
   - Create a source manifest.
   - Never modify source files.

2. File inspection
   - Determine file type.
   - Determine whether PDF has usable text layer.
   - Determine whether OCR is required.
   - Determine page count, dimensions, rotation, and image-only pages.

3. Rendering
   - Render pages locally.
   - Store temporary rendered images in a controlled work directory.
   - Clean temporary files unless debug mode is enabled.

4. Native text extraction
   - Extract native PDF text when available.
   - Convert native text to partial DocumentIR when coordinates are available.

5. Traditional OCR
   - Run configured OCR provider locally.
   - Produce word/line/block text, bounding boxes, and confidence scores.
   - Convert output to DocumentIR.

6. Optional VLM/document-AI parsing
   - Run configured document-AI providers if enabled.
   - Produce spatial text, markdown, region hints, and/or document QA outputs.
   - Convert output to DocumentIR-compatible structures.
   - Flag generative/hallucination risks.

7. Reconciliation
   - Merge native text, OCR, and VLM outputs into canonical DocumentIR.
   - Preserve provenance.
   - Emit conflict and confidence warnings.

8. Template detection
   - Detect exact template/version if possible.
   - Return UNKNOWN if confidence is too low.
   - Unknown templates must not be auto-exported.

9. Diagram extraction
   - Extract diagram crop.
   - Score region confidence.
   - Redact PII in diagram image.
   - Require review if uncertain.

10. Narrative extraction
    - Extract narrative text.
    - Preserve provenance.
    - Score confidence.
    - Require review if uncertain.

11. PII detection
    - Run provider chain.
    - Detect PII in:
      - native text
      - OCR text
      - VLM spatial text
      - VLM markdown text
      - extracted narrative
      - diagram OCR tokens
    - Merge PII entities.

12. Redaction
    - Redact narrative text using placeholders.
    - Redact diagram image using bounding boxes.
    - Require review for unmapped PII.

13. QA/fail-closed gate
    - Determine whether export is allowed.
    - Emit qa.json.
    - Block public export if required.

14. Export
    - Export only redacted diagrams, redacted narratives, manifest, and QA report.

============================================================
FAIL-CLOSED RULES
============================================================

The application must fail closed.

Do not auto-export when:

- Template is unknown.
- Template confidence is below threshold.
- OCR confidence is too low.
- VLM conflicts with OCR and conflict affects narrative or PII.
- Narrative boundaries are uncertain.
- Diagram crop boundaries are uncertain.
- Diagram crop may include surrounding PII-heavy form fields.
- PII is detected but cannot be mapped to image coordinates.
- Any provider reports unresolved errors.
- Any output might contain unredacted PII.
- Offline mode detects attempted network access.
- A required local model file is missing.
- A plugin requires network access and offline mode is enabled.

When failing closed:

- Produce internal QA report.
- Do not produce public export.
- Mark report as requiring human review.
- Explain why.

============================================================
EXPORT FORMAT
============================================================

For each successfully processed report, create:

exports/
  report_<short_sha256>/
    diagram.redacted.png
    narrative.redacted.txt
    narrative.redacted.json
    manifest.json
    qa.json

Do not include:

- original PDF
- original image
- unredacted text
- unredacted OCR JSON
- unredacted VLM output
- raw PII
- hidden text layer
- debug artifacts unless explicitly enabled outside public export

manifest.json must include:

{
  "source_sha256": "...",
  "source_file_name": "example.pdf",
  "template_id": "example_template_v1",
  "template_confidence": 0.98,
  "ocr_provider": "paddleocr",
  "ocr_provider_version": "...",
  "document_ai_providers": [],
  "pii_provider_chain": ["regex", "presidio"],
  "redaction_policy": "dot_default_v1",
  "export_contains_original_pdf": false,
  "export_contains_unredacted_text": false,
  "requires_human_review": false,
  "created_at": "ISO-8601 timestamp"
}

If a VLM/document-AI provider is used, include:

"document_ai_providers": [
  {
    "name": "kosmos25",
    "enabled": true,
    "used_for": ["markdown_assist", "spatial_ocr_assist"],
    "model_dir": "./models/document_ai/kosmos-2.5",
    "model_sha256_manifest": "...",
    "requires_network": false,
    "local_files_only": true,
    "license": "MIT or value from local manifest",
    "generative_model": true,
    "hallucination_warning": true,
    "safe_for_image_redaction": false
  }
]

qa.json must include:

- template confidence
- OCR confidence
- VLM warnings
- PII detection warnings
- redaction warnings
- review requirements
- export decision
- reasons for blocking export if blocked

============================================================
CONFIGURATION
============================================================

Create a default config file.

Example:

offline:
  enabled: true
  block_network: true
  fail_on_network_attempt: true

server:
  host: 127.0.0.1
  port: 7860
  expose_to_network: false

paths:
  work_dir: ./work
  export_dir: ./exports
  templates_dir: ./templates
  models_dir: ./models

ocr:
  provider_chain:
    - paddleocr
  providers:
    paddleocr:
      enabled: true
      det_model_dir: ./models/ocr/paddleocr/det
      rec_model_dir: ./models/ocr/paddleocr/rec
      cls_model_dir: ./models/ocr/paddleocr/cls
      allow_network: false
      local_files_only: true
    tesseract:
      enabled: true
      tessdata_dir: ./models/ocr/tesseract/tessdata
      allow_network: false
    mock_ocr:
      enabled: false

document_ai:
  enabled: false
  provider_chain:
    - mock_vlm
  providers:
    mock_vlm:
      enabled: false
      allow_network: false
    kosmos25:
      enabled: false
      model_dir: ./models/document_ai/kosmos-2.5
      processor_dir: ./models/document_ai/kosmos-2.5
      device: auto
      dtype: bfloat16
      allow_network: false
      local_files_only: true
      tasks:
        spatial_ocr: true
        markdown: true
      requires_review_when_used_for_export: true
      hallucination_warning: true

pii:
  provider_chain:
    - regex
    - presidio
  providers:
    regex:
      enabled: true
    presidio:
      enabled: true
      model_dir: ./models/pii/presidio
      allow_network: false
      local_files_only: true
    piiranha:
      enabled: false
      model_dir: ./models/pii/piiranha
      allow_network: false
      local_files_only: true
      license_warning: "Optional plugin only. Verify license before use."

template_detection:
  confidence_threshold: 0.85
  unknown_template_requires_review: true

review:
  require_review_for_vlm_generated_output: true
  require_review_for_low_ocr_confidence: true
  require_review_for_unmapped_pii: true

export:
  include_original_pdf: false
  include_unredacted_text: false
  include_debug_artifacts: false

logging:
  redact_pii: true
  log_raw_pii: false

============================================================
OFFLINE GUARD
============================================================

Create:

care/core/offline_guard.py

Implement a strict offline guard.

In offline mode:

- Block socket creation.
- Block HTTP requests.
- Block urllib requests.
- Block requests library calls.
- Block httpx calls.
- Block Hugging Face downloads.
- Block model auto-downloads.
- Fail if any provider attempts network access.
- Fail if frontend contains external assets.
- Fail if config enables a network-requiring plugin.

The app must include tests that monkeypatch network libraries and fail on any attempted external connection.

Example test behavior:

- run pipeline on synthetic scanned PDF with network blocked
- load OCR provider with local model paths
- load PII provider with local paths
- load VLM provider with local paths
- verify no call to huggingface.co
- verify no call to github.com
- verify no call to pypi.org
- verify no call to cloud APIs
- verify no external frontend URL

============================================================
CLI COMMANDS
============================================================

Implement a CLI:

care process ./input_reports --output ./exports --offline
care inspect ./input_reports/report.pdf
care list-plugins
care verify-offline
care validate-template ./templates/example_state/example_template_v1.yaml
care serve --host 127.0.0.1 --port 7860 --offline
care compute-model-checksums ./models
care generate-sbom
care scan-frontend-assets

CLI requirements:

- All commands work offline.
- process must fail closed.
- verify-offline must test network blocking.
- list-plugins must show enabled/disabled status, network requirements, and license notes.
- inspect must not export anything.
- serve must bind to 127.0.0.1 by default.

============================================================
API REQUIREMENTS
============================================================

Implement local FastAPI endpoints:

GET /health
GET /plugins
GET /jobs
POST /jobs
GET /jobs/{job_id}
GET /reports/{report_id}
GET /reports/{report_id}/qa
GET /reports/{report_id}/manifest
GET /reports/{report_id}/diagram
GET /reports/{report_id}/narrative
POST /reports/{report_id}/review/approve
POST /reports/{report_id}/review/reject
GET /exports
GET /offline/status

API rules:

- Bind to 127.0.0.1 by default.
- No public network exposure unless explicitly configured.
- Validate all paths.
- Prevent path traversal.
- Never return unredacted PII in normal API responses.
- Never expose original PDFs through public endpoints by default.

============================================================
FRONTEND REQUIREMENTS
============================================================

Build a simple local web UI using plain HTML/CSS/JS.

Views:

1. Dashboard.
2. New job page.
3. Job list.
4. Report detail page.
5. Template detection result.
6. Diagram preview.
7. Narrative preview.
8. PII highlights.
9. Redacted output preview.
10. QA warnings.
11. Approve/reject/reprocess controls.
12. Plugin status page.
13. Offline verification page.
14. Export browser.

Frontend constraints:

- All assets local.
- No CDN.
- No external JS.
- No external CSS.
- No external fonts.
- No analytics.
- No telemetry.
- No remote images.
- No map tiles.
- No external calls.
- Use fetch only against local backend endpoints.
- Provide a clear warning when a report requires review.
- Show VLM warnings when document-AI plugins were used.
- Show provider provenance for narrative and diagram extraction.

Use canvas or SVG overlays to show:

- diagram crop boundary
- OCR boxes
- PII redaction boxes
- uncertain regions
- QA warnings

============================================================
SECURITY REQUIREMENTS
============================================================

Implement:

- Path validation.
- Path traversal prevention.
- Controlled work/output directories.
- Secure temporary files.
- No raw PII logging.
- PII-redacting logger.
- Audit events without raw PII.
- Local-only server binding.
- Plugin allowlist.
- No arbitrary code execution.
- No arbitrary plugin loading from user paths unless explicitly allowed.
- No hidden network calls.
- No telemetry.
- No analytics.
- No auto-update.
- No runtime model download.
- No runtime dependency download.
- No execution of user-provided scripts.
- No exposing original PDFs by default.

Logs must never contain:

- names
- phone numbers
- addresses
- emails
- dates of birth
- driver license numbers
- license plates
- VINs
- insurance policy numbers
- raw narratives
- raw OCR dumps

============================================================
TESTING REQUIREMENTS
============================================================

Use pytest.

Create unit tests for:

- directory ingestion
- supported file filtering
- SHA-256 hashing
- manifest generation
- PDF inspection
- text-layer extraction
- rendering interface
- OCR provider interface
- mock OCR provider
- PaddleOCR provider local-path validation
- Tesseract provider local tessdata validation
- DocumentAI provider interface
- mock VLM provider
- Kosmos-2.5 provider disabled by default
- Kosmos-2.5 local_files_only behavior
- PII provider interface
- regex PII recognizers
- Presidio provider skeleton
- Piiranha provider disabled by default
- template YAML loading
- template validation
- template scoring
- diagram bbox extraction
- narrative anchor extraction
- DocumentIR serialization
- OCR/VLM reconciliation
- text redaction
- image redaction
- bounding box mapping
- export manifest generation
- QA warning generation
- fail-closed logic

Create integration tests for:

- process synthetic digital PDF
- process synthetic scanned PDF
- process synthetic image-only report
- process unknown-template report
- process low-confidence OCR report
- process report with fake PII in narrative
- process report with fake PII in diagram
- process report where VLM improves narrative section detection
- process report where VLM conflicts with OCR
- process report where VLM detects unmapped PII
- export contains only allowed files
- export does not include original PDF
- export does not include unredacted narrative

Create offline tests for:

- network blocked during processing
- network blocked during plugin load
- Hugging Face offline environment variables set
- local_files_only enforced
- no frontend external URLs
- no cloud OCR default plugins enabled
- no telemetry endpoint
- no model download
- no dependency download
- verify-offline command passes

Specific test names to include:

test_document_ai_provider_interface
test_mock_vlm_provider_outputs_document_ai_result
test_kosmos25_provider_disabled_by_default
test_kosmos25_provider_uses_local_model_path_only
test_kosmos25_provider_uses_local_files_only
test_vlm_output_converts_to_document_ir
test_vlm_markdown_can_help_narrative_detection
test_vlm_without_bboxes_cannot_drive_image_redaction
test_vlm_ocr_conflict_requires_review
test_vlm_detected_unmapped_pii_requires_review
test_offline_mode_blocks_huggingface_downloads
test_no_network_when_loading_document_ai_provider
test_document_ai_manifest_includes_model_checksums
test_export_manifest_records_document_ai_usage
test_piiranha_plugin_disabled_by_default
test_frontend_contains_no_external_urls
test_export_does_not_include_source_pdf
test_logs_do_not_include_raw_pii

============================================================
SYNTHETIC FIXTURES
============================================================

Create synthetic fixtures only.

Do not use real DOT reports.

Fixtures should include:

1. Synthetic digital PDF with text layer.
2. Synthetic scanned PDF.
3. Synthetic image-only report.
4. Synthetic unknown-template report.
5. Synthetic report with narrative and diagram.
6. Synthetic report with fake names.
7. Synthetic report with fake VINs.
8. Synthetic report with fake phone numbers.
9. Synthetic report with fake addresses.
10. Synthetic report with fake license plates.
11. Synthetic report where traditional OCR has poor reading order.
12. Synthetic report where VLM markdown improves section detection.
13. Synthetic report where VLM detects text OCR misses.
14. Synthetic report where VLM output conflicts with OCR.
15. Synthetic report where VLM produces hallucinated text.
16. Synthetic report where VLM detects possible PII but provides no bounding box.

All fake PII should be clearly synthetic.

============================================================
EVALUATION FRAMEWORK
============================================================

Add evaluation tools that can compute:

- OCR character error rate if ground truth exists.
- OCR word error rate if ground truth exists.
- Template detection accuracy.
- Unknown-template rejection rate.
- Diagram crop IoU if ground truth boxes exist.
- Narrative extraction text overlap.
- PII precision if labeled examples exist.
- PII recall if labeled examples exist.
- PII false negatives by entity type.
- PII false positives by entity type.
- Redaction completeness.
- Export safety checks.
- Reports/hour.
- Cost/report if relevant.
- Human-review rate.

PII recall is more important than precision.

False positives may remove useful detail.

False negatives may expose private information.

============================================================
PACKAGING AND RELEASE
============================================================

Support offline packaging.

Include scripts for:

- building a wheelhouse
- packaging local model files
- computing model checksums
- generating SBOM
- generating SHA-256 release checksums
- scanning frontend assets for external URLs
- verifying no-network operation
- packaging offline installer/archive

Release artifact should include:

- application code
- static frontend
- dependency wheelhouse or bundled executable
- local OCR model directory placeholders or packaged models
- local PII model directory placeholders or packaged models
- local VLM model directory placeholders or packaged models
- template registry
- license notices
- third-party notices
- model manifest
- SBOM
- SHA-256 checksums
- offline verification script

Do not require internet at install time for the production/offline package.

Create:

docs/packaging.md
docs/deployment.md
docs/offline-mode.md
docs/no-network-guarantee.md

============================================================
SBOM AND SUPPLY CHAIN
============================================================

Add documentation and scripts for:

- SBOM generation
- dependency license report
- model manifest generation
- model checksums
- release checksums
- reproducible build notes
- provenance notes

The app should support DOT review by making it clear:

- what code is included
- what dependencies are included
- what models are included
- where every model file came from
- what license each component has
- whether any component requires network access
- whether any component is disabled by default
- whether any component is optional

============================================================
DOCUMENTATION REQUIREMENTS
============================================================

Write docs for:

1. README.md
2. docs/architecture.md
3. docs/plugin-system.md
4. docs/offline-mode.md
5. docs/no-network-guarantee.md
6. docs/security.md
7. docs/template-authoring.md
8. docs/pii-policy.md
9. docs/redaction.md
10. docs/document-ai-plugins.md
11. docs/evaluation.md
12. docs/deployment.md
13. docs/packaging.md
14. docs/license-and-model-governance.md

README.md must explain:

- project purpose
- privacy goal
- offline-first design
- no-telemetry design
- plugin architecture
- how to run synthetic example
- how to run offline verification
- how to add OCR plugins
- how to add PII plugins
- how to add VLM/document-AI plugins
- how to add templates
- limitations
- security notes

docs/document-ai-plugins.md must explain:

- difference between traditional OCR and VLM document parsing
- how Kosmos-2.5 fits as an optional plugin
- how to package local model files
- how to enforce local_files_only
- hallucination risk
- when VLM output can assist extraction
- when VLM output requires review
- why VLM-only text without bounding boxes cannot drive image redaction
- how to add future multimodal OCR/document models

docs/pii-policy.md must explain:

- PII entity types
- redaction placeholders
- provider chain
- recall-over-precision policy
- custom DOT policy extension
- unmapped PII handling
- human review requirements

docs/no-network-guarantee.md must explain:

- what offline mode blocks
- how offline tests work
- how to verify no network calls
- how to run with network disabled
- how to inspect frontend assets
- how to disable optional network plugins

============================================================
IMPLEMENTATION ORDER
============================================================

Implement in this order:

Phase 1:
- repo skeleton
- config
- logging
- offline guard
- plugin base classes
- plugin registries
- DocumentIR models
- mock OCR provider
- mock VLM provider
- mock PII provider
- tests for plugin interfaces and offline guard

Phase 2:
- ingestion
- hashing
- file manifest
- PDF inspection
- rendering backend skeleton
- native text extraction skeleton
- pipeline orchestration
- synthetic fixtures

Phase 3:
- template YAML schema
- template loader
- template scoring
- diagram extractor
- narrative extractor
- QA/fail-closed gate

Phase 4:
- regex PII recognizers
- Presidio provider skeleton
- text redaction
- image redaction
- export manifest
- export writer

Phase 5:
- PaddleOCR provider skeleton
- Tesseract provider skeleton
- optional Piiranha provider skeleton disabled by default
- optional Kosmos-2.5 provider skeleton disabled by default
- OCR/VLM reconciliation

Phase 6:
- FastAPI routes
- plain HTML/CSS/JS frontend
- review UI
- plugin status page
- offline verification page

Phase 7:
- packaging scripts
- SBOM scripts
- license/model manifest
- docs
- full test suite

At every phase, maintain passing tests.

============================================================
DO NOT DO THESE THINGS
============================================================

Do not:

- Use cloud OCR as default.
- Use internet at runtime.
- Use telemetry.
- Use analytics.
- Use external frontend assets.
- Download models at runtime.
- Download dependencies at runtime.
- Export original PDFs by default.
- Export unredacted narratives by default.
- Store unredacted OCR/VLM output in public exports.
- Log raw PII.
- Hard-code one OCR model into the core pipeline.
- Hard-code one PII model into the core pipeline.
- Hard-code one VLM model into the core pipeline.
- Treat Piiranha as mandatory.
- Treat Kosmos-2.5 as mandatory.
- Silently process unknown templates.
- Silently export low-confidence results.
- Let VLM-only text drive image redaction without bounding boxes.
- Let generative output become final narrative without review.
- Load arbitrary plugins from untrusted locations.
- Bind the server to public network interfaces by default.
- Include real crash reports.
- Include real PII.

============================================================
ACCEPTANCE CRITERIA
============================================================

The repository is successful when:

1. A DOT can inspect the source code.
2. A DOT can install the app without internet.
3. A DOT can run the app with network disabled.
4. A DOT can process synthetic scanned crash reports.
5. The app extracts a redacted diagram and redacted narrative.
6. The app produces manifest.json and qa.json.
7. The app refuses to export unknown-template reports.
8. The app refuses to export low-confidence reports.
9. The app refuses to export reports with unmapped PII risk.
10. OCR engines are replaceable through plugins.
11. PII detection engines are replaceable through plugins.
12. VLM/document-AI models are replaceable through plugins.
13. PDF/image backends are replaceable through plugins.
14. No internet connection is required.
15. No internet connection is attempted in offline mode.
16. The exported folder contains no original report.
17. The exported folder contains no unredacted text.
18. The frontend has no external assets.
19. Optional Piiranha plugin is disabled by default.
20. Optional Kosmos-2.5 plugin is disabled by default.
21. The app has tests for no-network operation.
22. The app has docs for adding OCR, PII, and VLM plugins.
23. The app has docs for template authoring.
24. The app has docs for DOT offline deployment.
25. The app has SBOM/model/license manifest support.

============================================================
FINAL INSTRUCTION
============================================================

Generate the complete codebase, not just a design document.

Start with a working skeleton that passes tests, then implement the pipeline step by step.

Use mock providers first so the app can run without large model files.

All real model providers must be optional, local-only, plugin-based, and safe to disable.

The default demo must run fully offline using synthetic fixtures and mock/local providers.

The core architecture must make it easy for a DOT to add its own OCR model, PII model, VLM document reader, PDF backend, or template detector without rewriting the pipeline.