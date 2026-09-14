"""Utilitarios compartilhados do harness de avaliacao de recuperacao.

Le o corpus de markdown da wiki (o mesmo que o indexer consome), replica o
chunking da producao e implementa um BM25 local sem dependencias externas,
usado como baseline lexical e para ablacoes de chunking/contexto.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

SKIP_FILENAMES = {"index.md", "log.md", "lacunas.md"}

# Stopwords pt-BR enxutas: so o que e ruido puro em consulta de suporte.
STOPWORDS = {
    "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos", "e",
    "em", "essa", "esse", "esta", "este", "eu", "foi", "for", "isso", "ja",
    "la", "mais", "mas", "me", "mesmo", "na", "nas", "no", "nos", "nao", "num",
    "numa", "o", "os", "ou", "para", "pela", "pelo", "por", "que", "se", "sem",
    "ser", "seu", "sua", "sao", "tem", "um", "uma", "voce", "ha", "pelos",
}


@dataclass
class Doc:
    id: str
    path: str
    title: str
    type: str
    audience: str
    status: str
    modulos: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    body: str = ""

    @property
    def is_draft(self) -> bool:
        return self.status == "draft"


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def load_docs(root: Path) -> list[Doc]:
    """Carrega todo .md com frontmatter valido sob root."""
    docs: list[Doc] = []
    for path in sorted(root.rglob("*.md")):
        if path.name in SKIP_FILENAMES or ".obsidian" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        try:
            meta = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(meta, dict) or not meta.get("id"):
            continue
        docs.append(
            Doc(
                id=str(meta["id"]),
                path=str(path.relative_to(root)).replace("\\", "/"),
                title=str(meta.get("title", path.stem)),
                # llm-wiki usa tipo_ats (type vira rotulo OKF); wiki/ usa type.
                type=str(meta.get("tipo_ats") or meta.get("type") or ""),
                audience=str(meta.get("audience", "analyst")),
                status=str(meta.get("status", "active")),
                modulos=_as_list(meta.get("modulos")),
                tags=_as_list(meta.get("tags")),
                body=parts[2].strip(),
            )
        )
    return docs


def chunk_by_headings(content: str) -> list[dict]:
    """Copia fiel de indexer/src/chunker.py - paridade com a producao."""
    chunks: list[dict] = []
    current_heading = "Intro"
    current_content: list[str] = []
    for line in content.split("\n"):
        if line.startswith("## ") or line.startswith("# "):
            if current_content:
                chunks.append(
                    {"heading": current_heading, "content": "\n".join(current_content).strip()}
                )
            current_heading = line.strip("#").strip()
            current_content = []
        else:
            current_content.append(line)
    if current_content:
        chunks.append({"heading": current_heading, "content": "\n".join(current_content).strip()})
    return [c for c in chunks if c["content"]]


def context_header(doc: Doc, heading: str | None = None) -> str:
    """Preambulo de contexto proposto para o texto embeddado de cada chunk."""
    bits = [doc.title]
    if doc.type:
        bits.append("tipo: " + doc.type)
    if doc.modulos:
        bits.append("modulos: " + ", ".join(doc.modulos))
    if doc.tags:
        bits.append("tags: " + ", ".join(doc.tags))
    if heading and heading != "Intro":
        bits.append("secao: " + heading)
    return " | ".join(bits)


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    text = strip_accents(text.lower())
    return [t for t in _TOKEN_RE.findall(text) if len(t) > 1 and t not in STOPWORDS]


def clean_markdown(text: str) -> str:
    """Remove sintaxe (negrito, wikilink, link, callout) preservando o texto."""
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_`>#]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def sections(body: str) -> dict[str, str]:
    """Mapeia heading H2 -> texto da secao (chave sem acento, minuscula)."""
    out: dict[str, str] = {}
    current = "intro"
    buf: list[str] = []
    for line in body.split("\n"):
        if line.startswith("## "):
            if buf:
                out.setdefault(current, "\n".join(buf).strip())
            current = strip_accents(line[3:].strip().lower())
            buf = []
        else:
            buf.append(line)
    if buf:
        out.setdefault(current, "\n".join(buf).strip())
    return {k: v for k, v in out.items() if v}


class BM25:
    """BM25 Okapi em memoria. Unidades sao (doc_id, texto)."""

    def __init__(self, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.unit_doc: list[str] = []
        self.lengths: list[int] = []
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.avgdl = 0.0

    def add_all(self, units: Iterable[tuple[str, str]]) -> None:
        for doc_id, text in units:
            idx = len(self.unit_doc)
            toks = tokenize(text)
            self.unit_doc.append(doc_id)
            self.lengths.append(len(toks))
            for term, freq in Counter(toks).items():
                self.postings[term].append((idx, freq))
        self.avgdl = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0

    def search(self, query: str, allowed: set[str] | None, top_k: int) -> list[tuple[str, float]]:
        """Retorna [(doc_id, score)] deduplicado por documento (max entre unidades)."""
        n = len(self.unit_doc)
        if not n:
            return []
        scores: dict[int, float] = defaultdict(float)
        for term in set(tokenize(query)):
            posting = self.postings.get(term)
            if not posting:
                continue
            idf = math.log(1 + (n - len(posting) + 0.5) / (len(posting) + 0.5))
            for idx, freq in posting:
                dl = self.lengths[idx] or 1
                denom = freq + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                scores[idx] += idf * (freq * (self.k1 + 1)) / denom
        best: dict[str, float] = {}
        for idx, score in scores.items():
            doc_id = self.unit_doc[idx]
            if allowed is not None and doc_id not in allowed:
                continue
            if score > best.get(doc_id, 0.0):
                best[doc_id] = score
        return sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
