"""Testa o seletor de arquivos do sync incremental contra um repo git real.

Nao precisa de FalkorDB nem de chave do Gemini: exercita so git_sync, que e
onde mora o risco de o indexador deixar de ver uma alteracao.

  python tests/test_incremental_sync.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "indexer"))

falhas = 0


def check(rotulo, condicao, detalhe=""):
    global falhas
    status = "PASS" if condicao else "FAIL"
    if not condicao:
        falhas += 1
    print("  [%s] %s%s" % (status, rotulo, (" - " + detalhe) if detalhe else ""))


def git(args, cwd):
    subprocess.run(["git"] + args, cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def escrever(path: Path, texto="---\nid: X\n---\n\n## A\ncorpo\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(texto, encoding="utf-8")


def stub_logger():
    """Substitui src.logger para o teste rodar sem structlog instalado.

    git_sync so usa o logger para avisar de falha de comando; nao vale exigir
    a dependencia inteira para testar selecao de arquivo.
    """
    import types

    modulo = types.ModuleType("src.logger")
    modulo.logger = types.SimpleNamespace(
        info=lambda *a, **k: None,
        debug=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    sys.modules.setdefault("src", types.ModuleType("src")).__path__ = [
        str(Path(__file__).resolve().parents[1] / "indexer" / "src")
    ]
    sys.modules["src.logger"] = modulo


def main():
    # Importado aqui para o sys.path acima valer.
    stub_logger()
    from src.git_sync import changed_files as _changed_files, git_head as _git_head

    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp) / "repo"
        wiki_dir = repo_dir / "wiki"
        wiki_dir.mkdir(parents=True)
        git(["init", "-q"], repo_dir)
        git(["config", "user.email", "t@t"], repo_dir)
        git(["config", "user.name", "t"], repo_dir)

        escrever(wiki_dir / "rotinas" / "a.md")
        escrever(wiki_dir / "rotinas" / "b.md")
        escrever(wiki_dir / "index.md")
        escrever(repo_dir / "README.md", "fora da wiki\n")
        git(["add", "-A"], repo_dir)
        git(["commit", "-qm", "base"], repo_dir)
        base = _git_head(repo_dir)
        check("HEAD lido do repo", bool(base), str(base)[:8])

        # Sem mudanca nenhuma
        processar, removidos = _changed_files(wiki_dir, base, base)
        check("commit igual nao gera trabalho", processar == [] and removidos == [])

        # Um arquivo alterado, um novo, um apagado, um renomeado,
        # mais ruido que o indexador deve ignorar.
        escrever(wiki_dir / "rotinas" / "a.md", "---\nid: X\n---\n\n## A\nnovo corpo\n")
        escrever(wiki_dir / "erros" / "novo.md")
        (wiki_dir / "rotinas" / "b.md").unlink()
        escrever(repo_dir / "README.md", "mudou mas esta fora da wiki\n")
        escrever(wiki_dir / "index.md", "indice atualizado\n")
        git(["add", "-A"], repo_dir)
        git(["commit", "-qm", "mudancas"], repo_dir)
        head = _git_head(repo_dir)

        processar, removidos = _changed_files(wiki_dir, base, head)
        nomes = sorted(p.relative_to(wiki_dir).as_posix() for p in processar)
        check("pega alterado e novo", nomes == ["erros/novo.md", "rotinas/a.md"], str(nomes))
        check("pega o apagado", removidos == ["rotinas/b.md"], str(removidos))
        check("ignora arquivo fora da wiki", "README.md" not in str(nomes))
        check("ignora index.md", "index.md" not in str(nomes))

        # Rename: o caminho antigo tem de sair do indice e o novo entrar.
        anterior = head
        git(["mv", "wiki/rotinas/a.md", "wiki/rotinas/a-renomeado.md"], repo_dir)
        git(["commit", "-qm", "rename"], repo_dir)
        head = _git_head(repo_dir)
        processar, removidos = _changed_files(wiki_dir, anterior, head)
        nomes = [p.relative_to(wiki_dir).as_posix() for p in processar]
        check("rename indexa o novo caminho", nomes == ["rotinas/a-renomeado.md"], str(nomes))
        check("rename remove o caminho antigo", removidos == ["rotinas/a.md"], str(removidos))

        # Commit inexistente (cenario de force-push): tem de devolver None
        # para o chamador cair na varredura completa, nunca indexar errado.
        check("commit desconhecido cai para varredura completa",
              _changed_files(wiki_dir, "0" * 40, head) is None)

    print("\n%s" % ("todos os testes passaram" if falhas == 0 else "%d falha(s)" % falhas))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
