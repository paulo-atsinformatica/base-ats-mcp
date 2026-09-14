import os
import hashlib
import subprocess
from pathlib import Path
from fastapi import FastAPI
import uvicorn
import time
from .config import settings
from .logger import logger
from .telemetry import tracer
from .markdown_parser import markdown_parser
from .chunker import chunker
from .embeddings import embedding_generator
from .entity_extractor import extract_entities
from .falkordb_repository import repo
from .git_sync import SKIP_FILES, changed_files, git_head

# Mudar esta string invalida o hash de todo documento e forca reindexacao
# completa. "context-v2": o vetor passou a ser gerado sobre o chunk com
# preambulo de contexto (ver chunker.context_header).
INDEX_SCHEMA_VERSION = "context-v2"

META_LAST_COMMIT = "last_indexed_commit"
META_SCHEMA = "index_schema_version"
# Pausa entre lotes de embedding, para nao estourar cota em chave compartilhada.
# So se aplica a arquivo que realmente foi embeddado.
EMBED_SLEEP_SECONDS = 2.0

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def get_file_hash(content: str) -> str:
    payload = f"{INDEX_SCHEMA_VERSION}\n{content}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def git_pull():
    """Faz git pull no diretório da wiki para obter arquivos atualizados do GitHub."""
    wiki_dir = Path(settings.WIKI_PATH)
    # repo_dir é sempre um diretório dedicado (/app/repo),
    # NUNCA o WORKDIR /app (que já tem pyproject.toml, src/, etc.)
    repo_dir = wiki_dir.parent  # /app/repo  (WIKI_PATH=/app/repo/wiki)

    if not (repo_dir / ".git").exists():
        # Clonar pela primeira vez se o repo não existe
        if settings.GITHUB_REPO_URL:
            repo_dir.mkdir(parents=True, exist_ok=True)
            logger.info("git_clone_start", url=settings.GITHUB_REPO_URL, dest=str(repo_dir))
            env = os.environ.copy()
            if settings.GITHUB_TOKEN:
                url = settings.GITHUB_REPO_URL.replace(
                    "https://", f"https://{settings.GITHUB_TOKEN}@"
                )
            else:
                url = settings.GITHUB_REPO_URL
            subprocess.run(["git", "clone", url, str(repo_dir)], check=True, env=env)
            logger.info("git_clone_done")
        else:
            logger.warning("no_github_url_skipping_pull")
        return

    logger.info("git_pull_start", dir=str(repo_dir))
    result = subprocess.run(
        ["git", "pull", "--rebase"],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        logger.info("git_pull_done", output=result.stdout.strip())
    else:
        logger.error("git_pull_failed", stderr=result.stderr.strip())


# ─────────────────────────────────────────────
# Indexing Logic
# ─────────────────────────────────────────────

def process_file(file_path: Path) -> str:
    """Indexa um arquivo. Devolve o que aconteceu, para o laco saber se houve
    chamada de embedding (unico caso em que faz sentido pausar por cota)."""
    wiki_dir = Path(settings.WIKI_PATH)
    rel_path = str(file_path.relative_to(wiki_dir))
    with tracer.start_as_current_span("process_file", attributes={"file.path": rel_path}):
        try:
            content = file_path.read_text(encoding="utf-8")
            current_hash = get_file_hash(content)

            old_hash = repo.get_file_hash(rel_path)
            if old_hash == current_hash:
                logger.debug("file_unchanged", path=rel_path)
                return "unchanged"

            parsed = markdown_parser.parse(content)
            metadata = parsed["metadata"]

            # Regra: não indexar stubs (status: draft)
            if metadata.get("status") == "draft":
                logger.info("skipping_stub", path=rel_path)
                repo.delete_document(rel_path)
                return "skipped"

            logger.info("indexing_file", path=rel_path)

            chunks = chunker.chunk_by_headings(parsed["content"])
            if not chunks:
                logger.warning("no_chunks_found", path=rel_path)
                return "skipped"

            doc_data = {
                "id": metadata.get("id"),
                "path": rel_path,
                "title": metadata.get("title", file_path.stem),
                "type": metadata.get("type"),
                "audience": metadata.get("audience"),
                "status": metadata.get("status", "active"),
                "content_hash": current_hash,
                # wiki/ usa data_atualizacao; a exportacao OKF (llm-wiki/) usa
                # timestamp. Aceitar os dois para o campo nao vir vazio.
                "updated_at": str(
                    metadata.get("data_atualizacao") or metadata.get("timestamp") or ""
                ),
                "raw_content": content,
                "tags": metadata.get("tags", []) or [],
                "modulos": metadata.get("modulos", []) or [],
            }

            # Checar antes de embeddar: documento sem id nao vai ser gravado,
            # entao gerar o vetor dele so gasta cota.
            if not doc_data["id"]:
                logger.warning("missing_id_skipping", path=rel_path)
                return "skipped"

            doc_data["entities"] = extract_entities(doc_data, parsed["content"])

            # O vetor e a busca lexical usam o chunk CONTEXTUALIZADO (titulo,
            # tipo, modulos, tags, secao); o `content` guardado no grafo segue
            # cru, porque e ele que vai para o contexto do LLM.
            for chunk in chunks:
                chunk["embedding_text"] = chunker.embedding_text(metadata, chunk)
            embeddings = embedding_generator.generate_batch(
                [c["embedding_text"] for c in chunks]
            )

            repo.save_document(doc_data, chunks, embeddings)
            logger.info("file_indexed", path=rel_path, chunks=len(chunks), entities=len(doc_data["entities"]))
            return "indexed"

        except Exception as e:
            logger.error("file_processing_failed", path=rel_path, error=str(e))
            return "error"


def reindex_one(rel_path: str):
    """Reindexa um documento pelo caminho relativo a WIKI_PATH.

    Usado para corrigir conteudo de uma pagina especifica sem varrer a base.
    """
    wiki_dir = Path(settings.WIKI_PATH)
    alvo = (wiki_dir / rel_path).resolve()
    # Nao deixar sair da wiki via ../
    if not str(alvo).startswith(str(wiki_dir.resolve())):
        return {"status": "error", "reason": "path outside wiki"}
    if not alvo.exists():
        repo.delete_document(rel_path)
        return {"status": "ok", "action": "deleted", "path": rel_path}
    status = process_file(alvo)
    return {"status": "ok", "action": status, "path": rel_path}


def cleanup_deleted_files():
    """Remove do banco documentos que não existem mais no diretório da wiki."""
    with tracer.start_as_current_span("cleanup_deleted_files"):
        logger.info("starting_cleanup")
        db_paths = repo.list_all_document_paths()
        deleted_count = 0
        
        wiki_dir = Path(settings.WIKI_PATH)
        for path_str in db_paths:
            full_path = wiki_dir / path_str
            if not full_path.exists():
                logger.info("deleting_removed_file", path=path_str)
                repo.delete_document(path_str)
                deleted_count += 1
        
        logger.info("cleanup_done", removed=deleted_count)

def run_sync(force: bool = False):
    """Indexa a wiki.

    Por padrao processa so o que o git aponta como alterado desde a ultima
    indexacao. Varredura completa acontece na primeira vez, quando a versao do
    schema muda, quando o git nao sabe responder, ou com force=True.
    """
    logger.info("sync_started", wiki_path=settings.WIKI_PATH, force=force)
    wiki_dir = Path(settings.WIKI_PATH)

    if not wiki_dir.exists():
        logger.error("wiki_path_not_found", path=settings.WIKI_PATH)
        return {"status": "error", "reason": "wiki path not found"}

    head = git_head(wiki_dir.parent)
    last_commit = repo.get_meta(META_LAST_COMMIT)
    schema_gravado = repo.get_meta(META_SCHEMA)
    schema_mudou = schema_gravado != INDEX_SCHEMA_VERSION

    incremental = None
    if not force and not schema_mudou and head and last_commit:
        incremental = changed_files(wiki_dir, last_commit, head)

    if incremental is None:
        motivo = ("force" if force else
                  "schema_changed" if schema_mudou else
                  "no_baseline" if not last_commit else "git_unavailable")
        logger.info("full_sweep", reason=motivo)
        files = [p for p in wiki_dir.rglob("*.md") if p.name not in SKIP_FILES]
        removidos = []
    else:
        files, removidos = incremental
        logger.info("incremental_sweep", changed=len(files), deleted=len(removidos),
                    since=last_commit[:8], head=head[:8])

    contagem = {"indexed": 0, "unchanged": 0, "skipped": 0, "error": 0}
    for md_file in files:
        try:
            status = process_file(md_file)
        except Exception as e:
            logger.error("unexpected_error", file=str(md_file), error=str(e))
            status = "error"
        contagem[status] = contagem.get(status, 0) + 1
        # Pausa so quando houve chamada de embedding. Antes o sleep era
        # incondicional: uma varredura sem nenhuma mudanca custava ~3h.
        if status == "indexed":
            time.sleep(EMBED_SLEEP_SECONDS)

    for rel_path in removidos:
        logger.info("deleting_removed_file", path=rel_path)
        repo.delete_document(rel_path)

    if incremental is None:
        cleanup_deleted_files()

    if head and contagem["error"] == 0:
        repo.set_meta(META_LAST_COMMIT, head)
        repo.set_meta(META_SCHEMA, INDEX_SCHEMA_VERSION)

    summary = {
        "status": "ok",
        "mode": "full" if incremental is None else "incremental",
        "processed": sum(contagem.values()),
        "indexed": contagem["indexed"],
        "unchanged": contagem["unchanged"],
        "skipped": contagem["skipped"],
        "deleted": len(removidos),
        "errors": contagem["error"],
    }
    logger.info("sync_finished", **summary)
    return summary


# ─────────────────────────────────────────────
# HTTP Server (internal trigger endpoint)
# ─────────────────────────────────────────────

app = FastAPI(title="ERP KB Indexer — Internal")


@app.post("/trigger")
async def trigger_sync(force: bool = False, path: str = ""):
    """Endpoint interno chamado pelo MCP Server para acionar re-indexação.

    force=true ignora o ponteiro de commit e varre tudo.
    path=rotinas/x.md reindexa um documento só — para corrigir uma página sem
    esperar um ciclo inteiro.
    """
    with tracer.start_as_current_span("trigger_sync"):
        git_pull()
        if path:
            return reindex_one(path)
        result = run_sync(force=force)
        return result


@app.get("/health")
async def health():
    return {"status": "ok"}


# ─────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────

import asyncio

@app.on_event("startup")
async def startup_event():
    if os.getenv("INDEXER_SYNC_ON_STARTUP", "true").lower() == "true":
        logger.info("startup_sync_triggered")
        # Executa em uma thread separada para não bloquear o loop de eventos
        asyncio.create_task(asyncio.to_thread(lambda: (git_pull(), run_sync())))

# ─────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if "--server" in sys.argv:
        # Modo servidor: aguarda chamadas do MCP Server
        logger.info("indexer_mode", mode="server")
        uvicorn.run(app, host="0.0.0.0", port=9000, log_level="warning")
    else:
        # Modo one-shot: útil para execução manual / testes
        logger.info("indexer_mode", mode="one-shot")
        git_pull()
        result = run_sync(force="--force" in sys.argv)
        sys.exit(0 if result.get("status") == "ok" else 1)
