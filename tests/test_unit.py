"""
Testes unitários — markdown_parser e chunker (standalone, sem deps externas).
Executar: python -m pytest tests/test_unit.py -v
"""
import sys
import re
import types
import pytest
from pathlib import Path
from contextlib import contextmanager

# ─────────────────────────────────────────────────────────────────
# Stub completo de todas as dependências externas
# ─────────────────────────────────────────────────────────────────

class _FakeSpan:
    @contextmanager
    def __call__(self): yield

class _FakeTracer:
    def start_as_current_span(self, name, **kw):
        return _ctx()

@contextmanager
def _ctx():
    yield None

_fake_tracer = _FakeTracer()

def _stub(mod_name, **attrs):
    m = sys.modules.get(mod_name) or types.ModuleType(mod_name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[mod_name] = m
    return m

# opentelemetry stubs
_stub("opentelemetry")
_stub("opentelemetry.trace",
      get_tracer=lambda *a, **kw: _fake_tracer,
      set_tracer_provider=lambda p: None)

_stub("opentelemetry.sdk")
_sdk_trace = _stub("opentelemetry.sdk.trace")
_sdk_trace.TracerProvider = type("TracerProvider", (), {
    "__init__": lambda self, **kw: None,
    "add_span_processor": lambda self, p: None,
})
_stub("opentelemetry.sdk.trace.export",
      BatchSpanProcessor=type("BatchSpanProcessor", (), {"__init__": lambda self, e: None}))
_stub("opentelemetry.sdk.resources",
      Resource=type("Resource", (), {"create": staticmethod(lambda d: None)}))
_stub("opentelemetry.exporter")
_stub("opentelemetry.exporter.otlp")
_stub("opentelemetry.exporter.otlp.proto")
_stub("opentelemetry.exporter.otlp.proto.grpc")
_stub("opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
      OTLPSpanExporter=type("OTLPSpanExporter", (), {"__init__": lambda self, **kw: None}))

# structlog stub
_log_cls = type("_Log", (), {
    "info": lambda self, *a, **kw: None,
    "debug": lambda self, *a, **kw: None,
    "warning": lambda self, *a, **kw: None,
    "error": lambda self, *a, **kw: None,
})
_stub("structlog",
      configure=lambda **kw: None,
      get_logger=lambda: _log_cls(),
      PrintLoggerFactory=object,
      make_filtering_bound_logger=lambda lvl: None,
      processors=types.SimpleNamespace(
          add_log_level=None,
          TimeStamper=lambda **kw: None,
          JSONRenderer=lambda: None,
      ))

# frontmatter stub
class _FakePost:
    def __init__(self, meta, content):
        self.metadata = meta
        self.content = content

def _fake_loads(text):
    meta = {}
    body = text
    m = re.match(r'^---\n(.*?)\n---\n?(.*)', text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            if ':' in line:
                k, _, v = line.partition(':')
                meta[k.strip()] = v.strip().strip('"')
        body = m.group(2)
    return _FakePost(meta, body)

_stub("frontmatter", loads=_fake_loads)

# pydantic_settings stub
class _BaseSettings:
    def __init__(self, **kw): pass
    class Config: env_file = ".env"

_stub("pydantic_settings", BaseSettings=_BaseSettings)
_stub("pydantic", BaseModel=object)

# sentence_transformers stub
_stub("sentence_transformers",
      SentenceTransformer=type("ST", (), {
          "__init__": lambda self, model: None,
          "encode": lambda self, text: [0.0] * 384,
      }))

# Add indexer/src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "indexer"))

from src.markdown_parser import MarkdownParser
from src.chunker import Chunker
from src.entity_extractor import extract_entities, normalize_entity_name


# ─────────────────────────────────────────────────────────────────
# Tests — MarkdownParser
# ─────────────────────────────────────────────────────────────────

class TestMarkdownParser:
    def setup_method(self):
        self.parser = MarkdownParser()

    def test_parses_frontmatter_and_body(self):
        content = '---\ntitle: "Cadastro de Clientes"\nstatus: active\n---\n\n## Visão Geral\nTexto aqui.'
        result = self.parser.parse(content)
        assert result["metadata"]["title"] == "Cadastro de Clientes"
        assert result["metadata"]["status"] == "active"
        assert "Visão Geral" in result["content"]

    def test_parses_content_without_frontmatter(self):
        content = "# Apenas título\nSem frontmatter."
        result = self.parser.parse(content)
        assert result["metadata"] == {}
        assert "título" in result["content"] or "Apenas" in result["content"]

    def test_empty_content(self):
        result = self.parser.parse("")
        assert result["metadata"] == {}

    def test_draft_status_preserved(self):
        content = '---\ntitle: "Stub"\nstatus: draft\n---\nA preencher.'
        result = self.parser.parse(content)
        assert result["metadata"].get("status") == "draft"

    def test_id_field_preserved(self):
        content = '---\nid: ROT-fechamento-caixa\ntitle: "Test"\n---\nConteúdo.'
        result = self.parser.parse(content)
        assert result["metadata"].get("id") == "ROT-fechamento-caixa"


# ─────────────────────────────────────────────────────────────────
# Tests — Chunker
# ─────────────────────────────────────────────────────────────────

SAMPLE_TS = """## Sintoma
O sistema exibe erro ao abrir o caixa.

## Causa
Configuração incorreta do terminal.

## Solução
Reconfigurar o terminal nas opções do sistema.
"""

class TestChunker:
    def setup_method(self):
        self.chunker = Chunker()

    def test_splits_by_h2_headings(self):
        chunks = self.chunker.chunk_by_headings(SAMPLE_TS)
        assert len(chunks) == 3

    def test_headings_captured(self):
        chunks = self.chunker.chunk_by_headings(SAMPLE_TS)
        headings = [c["heading"] for c in chunks]
        assert "Sintoma" in headings
        assert "Causa" in headings
        assert "Solução" in headings

    def test_content_not_empty(self):
        for c in self.chunker.chunk_by_headings(SAMPLE_TS):
            assert c["content"].strip() != ""

    def test_empty_returns_empty(self):
        assert self.chunker.chunk_by_headings("") == []

    def test_no_headings_returns_intro(self):
        chunks = self.chunker.chunk_by_headings("Apenas texto sem heading.")
        assert len(chunks) == 1
        assert chunks[0]["heading"] == "Intro"

    def test_empty_sections_filtered_out(self):
        content = "## Vazia\n\n## Com conteúdo\nTexto real aqui."
        chunks = self.chunker.chunk_by_headings(content)
        assert len(chunks) == 1
        assert chunks[0]["heading"] == "Com conteúdo"

    def test_h1_also_splits(self):
        content = "# Visão Geral\nTexto.\n\n# Outra Seção\nMais texto."
        chunks = self.chunker.chunk_by_headings(content)
        assert len(chunks) == 2


# ─────────────────────────────────────────────────────────────────
# Tests — Audience Rule
# ─────────────────────────────────────────────────────────────────

DB_KEYWORDS = [
    r'\bSELECT\b', r'\bFirebird\b', r'banco de dados',
    r'\bSYSDBA\b', r'\.fdb\b', r'\bgbak\b',
]

def is_db_content(content):
    for kw in DB_KEYWORDS:
        if re.search(kw, content, re.IGNORECASE):
            return True
    return False


class TestAudienceRule:
    def test_select_detected(self):
        assert is_db_content("Execute SELECT * FROM CLIENTES WHERE ID = 1")

    def test_firebird_detected(self):
        assert is_db_content("Conecte ao banco Firebird via isql")

    def test_fdb_path_detected(self):
        assert is_db_content("Caminho: C:\\dados\\empresa.fdb")

    def test_banco_de_dados_detected(self):
        assert is_db_content("Acesse o banco de dados pelo IBExpert")

    def test_sysdba_detected(self):
        assert is_db_content("Conecte com usuário SYSDBA")

    def test_normal_text_not_flagged(self):
        assert not is_db_content("Vá em Financeiro > Lançamentos e clique em Novo.")

    def test_nfe_rejection_not_flagged(self):
        assert not is_db_content("Rejeição 204: Duplicidade de NF-e — verifique a chave de acesso.")

    def test_case_insensitive(self):
        assert is_db_content("use o select para buscar dados")


class TestEntityExtractor:
    def test_normalizes_common_aliases(self):
        assert normalize_entity_name("NFE") == "nf-e"
        assert normalize_entity_name("  Backup   Now  ") == "backup now"

    def test_extracts_metadata_and_patterns(self):
        doc_data = {
            "title": "Erro no Backup Now",
            "tags": ["backup", "Firebird"],
            "modulos": ["windows/backup"],
        }
        content = "Unable to load dbxfb.dll ao conectar empresa.fdb. Rejeicao 539 na NF-e."
        entities = extract_entities(doc_data, content)
        names = {entity["name"] for entity in entities}
        types = {entity["name"]: entity["type"] for entity in entities}

        assert "backup now" in names
        assert "dbxfb.dll" in names
        assert "empresa.fdb" in names
        assert "rejeicao 539" in names
        assert "windows/backup" in names
        assert types["dbxfb.dll"] == "dll"
        assert types["empresa.fdb"] == "database_file"
        assert types["rejeicao 539"] == "sefaz_rejection"
