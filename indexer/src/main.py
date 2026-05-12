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
from .falkordb_repository import repo

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def get_file_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


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

def process_file(file_path: Path):
    wiki_dir = Path(settings.WIKI_PATH)
    rel_path = str(file_path.relative_to(wiki_dir))
    with tracer.start_as_current_span("process_file", attributes={"file.path": rel_path}):
        try:
            content = file_path.read_text(encoding="utf-8")
            current_hash = get_file_hash(content)

            old_hash = repo.get_file_hash(rel_path)
            if old_hash == current_hash:
                logger.debug("file_unchanged", path=rel_path)
                return

            parsed = markdown_parser.parse(content)
            metadata = parsed["metadata"]

            # Regra: não indexar stubs (status: draft)
            if metadata.get("status") == "draft":
                logger.info("skipping_stub", path=rel_path)
                repo.delete_document(rel_path)
                return

            logger.info("indexing_file", path=rel_path)

            chunks = chunker.chunk_by_headings(parsed["content"])
            if not chunks:
                logger.warning("no_chunks_found", path=rel_path)
                return

            embeddings = embedding_generator.generate_batch([c["content"] for c in chunks])

            doc_data = {
                "id": metadata.get("id"),
                "path": rel_path,
                "title": metadata.get("title", file_path.stem),
                "type": metadata.get("type"),
                "audience": metadata.get("audience"),
                "status": metadata.get("status", "active"),
                "content_hash": current_hash,
                "updated_at": str(metadata.get("data_atualizacao", "")),
                "raw_content": content,
                "tags": metadata.get("tags", []) or [],
                "modulos": metadata.get("modulos", []) or [],
            }

            if not doc_data["id"]:
                logger.warning("missing_id_skipping", path=rel_path)
                return

            repo.save_document(doc_data, chunks, embeddings)
            logger.info("file_indexed", path=rel_path, chunks=len(chunks))

        except Exception as e:
            logger.error("file_processing_failed", path=rel_path, error=str(e))


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

def run_sync():
    logger.info("sync_started", wiki_path=settings.WIKI_PATH)
    wiki_dir = Path(settings.WIKI_PATH)

    if not wiki_dir.exists():
        logger.error("wiki_path_not_found", path=settings.WIKI_PATH)
        return {"status": "error", "reason": "wiki path not found"}

    processed = 0
    errors = 0

    files = list(wiki_dir.rglob("*.md"))
    for md_file in files:
        if md_file.name in ("index.md", "log.md"):
            continue
        try:
            process_file(md_file)
            processed += 1
            # Rate limiting conservador para evitar 429 em chaves compartilhadas
            time.sleep(2.0)
        except Exception as e:
            logger.error("unexpected_error", file=str(md_file), error=str(e))
            errors += 1
            
    cleanup_deleted_files()

    summary = {"status": "ok", "processed": processed, "errors": errors}
    logger.info("sync_finished", **summary)
    return summary


# ─────────────────────────────────────────────
# HTTP Server (internal trigger endpoint)
# ─────────────────────────────────────────────

app = FastAPI(title="ERP KB Indexer — Internal")


@app.post("/trigger")
async def trigger_sync():
    """Endpoint interno chamado pelo MCP Server para acionar re-indexação."""
    with tracer.start_as_current_span("trigger_sync"):
        git_pull()
        result = run_sync()
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
        result = run_sync()
        sys.exit(0 if result.get("status") == "ok" else 1)
