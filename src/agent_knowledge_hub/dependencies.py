from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from agent_knowledge_hub.utils import utc_now_iso, write_json


@dataclass(frozen=True)
class RuntimeDependency:
    package: str
    import_name: str
    installed: bool
    capability: str
    required_for: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeCapability:
    capability: str
    ready: bool
    required_packages: list[str]
    missing_packages: list[str]
    note: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeDependencyReport:
    generated_at: str
    dependencies: list[RuntimeDependency]
    capabilities: list[RuntimeCapability]
    markdown: str

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "dependencies": [dependency.to_dict() for dependency in self.dependencies],
            "capabilities": [capability.to_dict() for capability in self.capabilities],
        }


_DEPENDENCY_SPECS = [
    {
        "package": "pypdf",
        "import_name": "pypdf",
        "capability": "pdf_text",
        "required_for": "PDF text-layer extraction",
    },
    {
        "package": "python-docx",
        "import_name": "docx",
        "capability": "docx",
        "required_for": "DOCX paragraph and table extraction",
    },
    {
        "package": "pymupdf",
        "import_name": "fitz",
        "capability": "pdf_ocr",
        "required_for": "PDF page rendering before OCR fallback",
    },
    {
        "package": "rapidocr",
        "import_name": "rapidocr",
        "capability": "pdf_ocr",
        "required_for": "OCR fallback for scanned or low-quality PDF text",
    },
    {
        "package": "onnxruntime",
        "import_name": "onnxruntime",
        "capability": "pdf_ocr",
        "required_for": "RapidOCR model execution",
    },
]

_CAPABILITY_NOTES = {
    "plain_text": "Markdown, HTML, and TXT parsing use the Python standard library.",
    "pdf_text": "PDF text-layer extraction uses pypdf. Low-quality text may still require OCR.",
    "docx": "DOCX parsing requires python-docx.",
    "pdf_ocr": "PDF OCR fallback requires pymupdf, rapidocr, and onnxruntime together.",
}


def check_runtime_dependencies(
    *,
    find_spec: Callable[[str], object | None] = importlib.util.find_spec,
) -> RuntimeDependencyReport:
    dependencies = [
        RuntimeDependency(
            package=str(spec["package"]),
            import_name=str(spec["import_name"]),
            installed=find_spec(str(spec["import_name"])) is not None,
            capability=str(spec["capability"]),
            required_for=str(spec["required_for"]),
        )
        for spec in _DEPENDENCY_SPECS
    ]

    capabilities = [
        RuntimeCapability(
            capability="plain_text",
            ready=True,
            required_packages=[],
            missing_packages=[],
            note=_CAPABILITY_NOTES["plain_text"],
        )
    ]
    for capability in ["pdf_text", "docx", "pdf_ocr"]:
        required = [
            dependency.package
            for dependency in dependencies
            if dependency.capability == capability
        ]
        missing = [
            dependency.package
            for dependency in dependencies
            if dependency.capability == capability and not dependency.installed
        ]
        capabilities.append(
            RuntimeCapability(
                capability=capability,
                ready=not missing,
                required_packages=required,
                missing_packages=missing,
                note=_CAPABILITY_NOTES[capability],
            )
        )

    report_without_markdown = RuntimeDependencyReport(
        generated_at=utc_now_iso(),
        dependencies=dependencies,
        capabilities=capabilities,
        markdown="",
    )
    return RuntimeDependencyReport(
        generated_at=report_without_markdown.generated_at,
        dependencies=report_without_markdown.dependencies,
        capabilities=report_without_markdown.capabilities,
        markdown=_render_dependency_report_markdown(report_without_markdown),
    )


def write_runtime_dependency_report_bundle(
    *,
    output_dir: Path | str,
    report: RuntimeDependencyReport,
) -> dict[str, Path]:
    bundle_dir = Path(output_dir).resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)
    json_path = bundle_dir / "runtime-dependencies.json"
    markdown_path = bundle_dir / "runtime-dependencies.md"

    write_json(json_path, report.to_dict())
    markdown_path.write_text(report.markdown, encoding="utf-8")
    return {"json_path": json_path, "markdown_path": markdown_path}


def _render_dependency_report_markdown(report: RuntimeDependencyReport) -> str:
    lines = [
        "# Runtime Dependency Report",
        "",
        f"Generated At: `{report.generated_at}`",
        "",
        "## Capabilities",
        "",
        "| Capability | Ready | Missing Packages | Note |",
        "| --- | --- | --- | --- |",
    ]
    for capability in report.capabilities:
        missing = ", ".join(capability.missing_packages) if capability.missing_packages else "-"
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_table_cell(capability.capability),
                    "yes" if capability.ready else "no",
                    _escape_table_cell(missing),
                    _escape_table_cell(capability.note),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Dependencies",
            "",
            "| Package | Import | Installed | Capability | Required For |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for dependency in report.dependencies:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_table_cell(dependency.package),
                    _escape_table_cell(dependency.import_name),
                    "yes" if dependency.installed else "no",
                    _escape_table_cell(dependency.capability),
                    _escape_table_cell(dependency.required_for),
                ]
            )
            + " |"
        )

    return "\n".join(lines).strip() + "\n"


def _escape_table_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
