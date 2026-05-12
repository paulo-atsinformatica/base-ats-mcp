import re
from typing import Any


KNOWN_TERMS = {
    "backup now": "product",
    "firebird": "database",
    "ibexpert": "tool",
    "flamerobin": "tool",
    "sefaz": "service",
    "sped": "module",
    "nfe": "module",
    "nf-e": "module",
    "nfce": "module",
    "nfc-e": "module",
    "mdf-e": "module",
    "monitor api": "module",
    "resulth": "product",
    "windows": "platform",
    "xml": "file_type",
    "certificado digital": "certificate",
}


PATTERNS = [
    (re.compile(r"\b[\w.-]+\.dll\b", re.IGNORECASE), "dll"),
    (re.compile(r"\b[\w.-]+\.fdb\b", re.IGNORECASE), "database_file"),
    (re.compile(r"\b[\w.-]+\.xml\b", re.IGNORECASE), "xml_file"),
    (re.compile(r"\bRejei[cç][aã]o\s+\d{3,4}\b", re.IGNORECASE), "sefaz_rejection"),
    (re.compile(r"\b(?:erro|error|vendor error)\s+\d{2,6}\b", re.IGNORECASE), "error_code"),
    (re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b"), "db_object"),
]


def normalize_entity_name(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    normalized = normalized.strip(".,;:()[]{}\"'")
    aliases = {
        "nfe": "nf-e",
        "nfce": "nfc-e",
    }
    return aliases.get(normalized, normalized)


def _add_entity(entities: dict[str, dict[str, str]], name: str, entity_type: str):
    normalized = normalize_entity_name(name)
    if not normalized or len(normalized) < 2:
        return
    current = entities.get(normalized)
    if current:
        if current["type"] in {"keyword", "tag"} and entity_type not in {"keyword", "tag"}:
            current["type"] = entity_type
        return
    entities[normalized] = {
        "name": normalized,
        "display_name": name.strip(),
        "type": entity_type,
    }


def _iter_values(value: Any):
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]


def extract_entities(doc_data: dict, content: str) -> list[dict[str, str]]:
    entities: dict[str, dict[str, str]] = {}

    for tag in _iter_values(doc_data.get("tags")):
        _add_entity(entities, tag, "tag")

    for module in _iter_values(doc_data.get("modulos")):
        _add_entity(entities, module, "module")
        for part in re.split(r"[/\\>|,;]+", module):
            _add_entity(entities, part, "module")

    title = doc_data.get("title")
    if title:
        _add_entity(entities, title, "document_topic")

    search_text = f"{title or ''}\n{content}"
    lowered = search_text.lower()
    for term, entity_type in KNOWN_TERMS.items():
        if term in lowered:
            _add_entity(entities, term, entity_type)

    for pattern, entity_type in PATTERNS:
        for match in pattern.finditer(search_text):
            _add_entity(entities, match.group(0), entity_type)

    return sorted(entities.values(), key=lambda item: (item["type"], item["name"]))
