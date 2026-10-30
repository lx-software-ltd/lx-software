"""Read and rewrite Word resumes without changing locked paragraphs.

``python-docx`` keeps namespace declarations that ``xml.etree`` would drop.
``defusedxml`` rejects entity declarations before that parser runs. A direct
check showed ``python-docx`` does not expand a custom entity; the pre-check
is still the gate.
"""

from __future__ import annotations

import io
import zipfile
from copy import deepcopy
from typing import Any

import defusedxml.ElementTree as defused_et
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.oxml.xmlchemy import BaseOxmlElement
from resume_store import ResumeError

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
UNCOMPRESSED_MAX = 30 * 1024 * 1024
DOCUMENT_XML_MAX = 10 * 1024 * 1024


def validate(data: bytes) -> None:
    if not data.startswith(b"PK"):
        raise ResumeError("Upload a .docx Word document.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ResumeError("Upload a .docx Word document.") from exc
    names = archive.namelist()
    if "word/document.xml" not in names:
        raise ResumeError("This file is not a Word document.")
    if any(name.endswith("vbaProject.bin") for name in names):
        raise ResumeError("Macro-enabled documents are not accepted.")
    infos = archive.infolist()
    if sum(info.file_size for info in infos) > UNCOMPRESSED_MAX:
        raise ResumeError("The document is too large to read.")
    document_info = archive.getinfo("word/document.xml")
    if document_info.file_size > DOCUMENT_XML_MAX:
        raise ResumeError("The document is too large to read.")
    xml = archive.read("word/document.xml")
    if b"<w:ins" in xml or b"<w:del" in xml or b"<w:delText" in xml:
        raise ResumeError("Accept all changes in Word, then upload again.")
    try:
        defused_et.fromstring(xml)
    except Exception as exc:
        raise ResumeError("The document XML is not safe to read.") from exc


def _ancestors(node: BaseOxmlElement, tag: str) -> bool:
    parent = node.getparent()
    wanted = qn(tag)
    while parent is not None:
        if parent.tag == wanted:
            return True
        parent = parent.getparent()
    return False


def paragraph_text(paragraph: BaseOxmlElement) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == qn("w:t"):
            parts.append(node.text or "")
        elif node.tag == qn("w:tab"):
            parts.append("\t")
        elif node.tag == qn("w:br"):
            parts.append("\n")
    return "".join(parts)


def _style_name(paragraph: BaseOxmlElement) -> str:
    props = paragraph.find(qn("w:pPr"))
    if props is None:
        return ""
    style = props.find(qn("w:pStyle"))
    if style is None:
        return ""
    return str(style.get(qn("w:val")) or "")


def _numbered(paragraph: BaseOxmlElement) -> bool:
    props = paragraph.find(qn("w:pPr"))
    return props is not None and props.find(qn("w:numPr")) is not None


def _run_count(paragraph: BaseOxmlElement) -> int:
    return sum(1 for node in paragraph.iter() if node.tag == qn("w:r"))


def iter_body_paragraphs(document: Document) -> list[BaseOxmlElement]:
    return [node for node in document.element.body.iter(qn("w:p"))]


def paragraph_map(data: bytes) -> list[dict[str, Any]]:
    validate(data)
    document = Document(io.BytesIO(data))
    rows: list[dict[str, Any]] = []
    for index, paragraph in enumerate(iter_body_paragraphs(document)):
        text = paragraph_text(paragraph)
        rows.append(
            {
                "id": f"p{index}",
                "text": text,
                "style": _style_name(paragraph),
                "numbered": _numbered(paragraph),
                "inTable": _ancestors(paragraph, "w:tbl"),
                "inTextBox": _ancestors(paragraph, "w:txbxContent"),
                "runs": _run_count(paragraph),
                "chars": len(text),
            }
        )
    return rows


def _first_run_properties(paragraph: BaseOxmlElement) -> BaseOxmlElement | None:
    for node in paragraph.iter(qn("w:r")):
        props = node.find(qn("w:rPr"))
        if props is not None:
            return deepcopy(props)
    return None


def _has_hyperlink(paragraph: BaseOxmlElement) -> bool:
    return any(node.tag == qn("w:hyperlink") for node in paragraph.iter())


def _set_text(paragraph: BaseOxmlElement, text: str) -> None:
    props = _first_run_properties(paragraph)
    for node in list(paragraph):
        if node.tag in {qn("w:r"), qn("w:hyperlink"), qn("w:ins"), qn("w:del")}:
            paragraph.remove(node)
    pieces = text.split("\n") if text else [""]
    for line_index, line in enumerate(pieces):
        if line_index:
            run = OxmlElement("w:r")
            if props is not None:
                run.append(deepcopy(props))
            run.append(OxmlElement("w:br"))
            paragraph.append(run)
        chunks = line.split("\t") if line else [""]
        for chunk_index, chunk in enumerate(chunks):
            if chunk_index:
                tab_run = OxmlElement("w:r")
                if props is not None:
                    tab_run.append(deepcopy(props))
                tab_run.append(OxmlElement("w:tab"))
                paragraph.append(tab_run)
            run = OxmlElement("w:r")
            if props is not None:
                run.append(deepcopy(props))
            node = OxmlElement("w:t")
            node.set(XML_SPACE, "preserve")
            node.text = chunk
            run.append(node)
            paragraph.append(run)


def apply(
    data: bytes,
    layout: dict[str, Any],
    output: dict[str, Any],
) -> tuple[bytes, list[str]]:
    """Write model text into a copy of the template. Locked paragraphs stay byte-identical."""
    validate(data)
    document = Document(io.BytesIO(data))
    elements = iter_body_paragraphs(document)
    by_id = {f"p{index}": element for index, element in enumerate(elements)}
    notes: list[str] = []
    replacements = {str(item["id"]): str(item.get("text") or "") for item in output.get("replacements") or []}
    for item in output.get("skills") or []:
        replacements[str(item["id"])] = str(item.get("text") or "")
    groups = {str(group.get("headerId")): group for group in layout.get("roles") or []}
    for spec in output.get("roles") or []:
        group = groups.get(str(spec.get("headerId")))
        if not group:
            continue
        ids = [str(item) for item in group.get("bulletIds") or []]
        texts = [str(item) for item in spec.get("bullets") or []]
        for bullet_id, text in zip(ids, texts, strict=False):
            replacements[bullet_id] = text
        if len(texts) > len(ids) and ids:
            anchor = by_id[ids[-1]]
            for extra in texts[len(ids) :]:
                clone = deepcopy(anchor)
                _set_text(clone, extra)
                anchor.addnext(clone)
                anchor = clone
        elif len(texts) < len(ids):
            for bullet_id in ids[len(texts) :]:
                element = by_id[bullet_id]
                parent = element.getparent()
                if parent is not None:
                    parent.remove(element)
    for paragraph_id, text in replacements.items():
        element = by_id.get(paragraph_id)
        if element is None or element.getparent() is None:
            continue
        if _has_hyperlink(element) or _run_count(element) > 1:
            notes.append(f"Inline formatting in {paragraph_id} was flattened.")
        _set_text(element, text)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue(), notes


def to_markdown(paragraphs: list[dict[str, Any]], layout: dict[str, Any]) -> str:
    roles = {str(item.get("id")): str(item.get("role") or "other") for item in layout.get("paragraphs") or []}
    lines: list[str] = []
    for paragraph in paragraphs:
        text = str(paragraph.get("text") or "").strip()
        if not text:
            continue
        role = roles.get(str(paragraph.get("id")), "other")
        if role == "name":
            lines.append(f"# {text}")
        elif role == "section_heading":
            lines.append(f"\n## {text}")
        elif role == "bullet":
            lines.append(f"- {text}")
        elif role in {"role_header", "headline"}:
            lines.append(f"\n**{text}**")
        elif role == "role_meta":
            lines.append(f"_{text}_")
        else:
            lines.append(text)
    return "\n".join(lines).strip()


def open_document(data: bytes) -> Document:
    validate(data)
    return Document(io.BytesIO(data))
