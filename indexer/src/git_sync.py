"""Selecao de arquivos alterados via git, para o sync incremental.

Modulo deliberadamente sem dependencia de FalkorDB nem do cliente de
embeddings: e a parte com mais risco de erro silencioso (deixar de ver uma
alteracao) e precisa ser testavel sem infraestrutura nenhuma.
"""
import subprocess
from pathlib import Path

from .logger import logger

# Arquivos de navegacao da wiki, nunca indexados como conteudo.
SKIP_FILES = ("index.md", "log.md")


def git(args: list, cwd: Path):
    """Roda um comando git e devolve stdout, ou None se falhar."""
    try:
        result = subprocess.run(
            ["git"] + args, cwd=str(cwd), capture_output=True, text=True, timeout=120
        )
    except Exception as e:
        logger.warning("git_command_failed", args=" ".join(args), error=str(e))
        return None
    if result.returncode != 0:
        logger.warning("git_command_failed", args=" ".join(args),
                       stderr=result.stderr.strip()[:300])
        return None
    return result.stdout


def git_head(repo_dir: Path):
    if not (repo_dir / ".git").exists():
        return None
    out = git(["rev-parse", "HEAD"], repo_dir)
    return out.strip() if out else None


def changed_files(wiki_dir: Path, last_commit: str, head: str):
    """Arquivos .md da wiki tocados entre dois commits.

    Devolve (a_processar, removidos_rel) ou None quando o git nao consegue
    responder — por exemplo se o commit anterior sumiu apos um force-push.
    Nesse caso o chamador cai na varredura completa, que e sempre correta.
    """
    repo_dir = wiki_dir.parent
    if last_commit == head:
        return [], []
    out = git(["diff", "--name-status", last_commit, head], repo_dir)
    if out is None:
        return None

    prefixo = wiki_dir.name + "/"  # caminhos do git sao relativos a raiz do repo
    a_processar, removidos = [], []
    for linha in out.splitlines():
        partes = linha.split("\t")
        if len(partes) < 2:
            continue
        estado = partes[0]
        caminhos = partes[1:]
        # Rename vem como "R100 antigo novo": o antigo sai, o novo entra.
        alvos = [(estado[0], caminhos[-1])]
        if estado.startswith("R") and len(caminhos) == 2:
            alvos = [("D", caminhos[0]), ("A", caminhos[1])]
        for acao, caminho in alvos:
            if not caminho.startswith(prefixo) or not caminho.endswith(".md"):
                continue
            rel = caminho[len(prefixo):]
            if Path(rel).name in SKIP_FILES:
                continue
            if acao == "D":
                removidos.append(rel)
            else:
                a_processar.append(wiki_dir / rel)
    return a_processar, removidos
