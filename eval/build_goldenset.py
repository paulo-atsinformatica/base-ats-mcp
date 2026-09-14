"""Gera o golden set de recuperacao a partir do proprio corpus da wiki.

Cada linha do JSONL e uma consulta com UM documento alvo conhecido. As
consultas sao derivadas de campos que o usuario real digitaria, agrupadas em
trilhas (tracks) com caracteristicas de vazamento lexical diferentes:

  erro_literal      mensagem de erro exata (analista cola no chat).
                    Vazamento intrinseco e LEGITIMO: a consulta real e mesmo
                    igual ao texto do documento. Numero absoluto confiavel.
  fewshot_pergunta  pergunta real de ticket, extraida de few-shot/.
                    A pergunta esta literal no doc alvo -> metrica otimista;
                    usar de forma COMPARATIVA entre configuracoes.
  sintoma           descricao do problema em troubleshooting/, sem markdown.
                    Idem: otimista, bom para regressao.
  sintoma_hard      igual a sintoma, mas removendo os termos do titulo do alvo.
                    Aproxima uma parafrase: mede robustez sem atalho lexical.
  rotina_objetivo   objetivo da rotina/procedimento/faq, texto natural.
  rotina_objetivo_hard  idem, sem os termos do titulo. Junto com sintoma_hard,
                    e a trilha mais proxima de uma pergunta de cliente
                    ("como faco para ...") e a mais dificil.

Uso:
  python build_goldenset.py --corpus E:/Projetos/obsidian/wiki --per-track 250
"""
from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

import common

MIN_TOKENS = 4
MIN_TOKENS_HARD = 6
# Um termo e "discriminativo" se aparece em no maximo esta fracao do corpus.
RARE_DF_RATIO = 0.02
MAX_QUERY_CHARS = 240

BOLD_RE = re.compile(r"\*\*(.{10,180}?)\*\*")
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _first_sentences(text: str, limit: int = MAX_QUERY_CHARS) -> str:
    text = common.clean_markdown(text)
    out: list[str] = []
    for sentence in SENT_SPLIT_RE.split(text):
        if not sentence:
            continue
        out.append(sentence)
        if sum(len(s) for s in out) >= limit:
            break
    return " ".join(out)[:limit].strip()


def _drop_title_terms(query: str, title: str) -> str:
    """Remove do texto as palavras que aparecem no titulo do alvo."""
    banned = set(common.tokenize(title))
    kept = [w for w in query.split() if common.tokenize(w) and common.tokenize(w)[0] not in banned]
    return " ".join(kept).strip()


def _ok(query: str) -> bool:
    return len(common.tokenize(query)) >= MIN_TOKENS


def _document_frequency(docs: list[common.Doc]) -> dict[str, int]:
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(set(common.tokenize(doc.title + " " + doc.body)))
    return df


def _ok_hard(query: str, df: dict[str, int], n_docs: int) -> bool:
    """Descarta consulta "hard" que virou so palavra generica de suporte.

    Sem isso o corte dos termos do titulo produz consultas como "tentar
    realizar sistema apresenta mensagem", que nenhum retriever poderia acertar
    e que so adicionam ruido a metrica.
    """
    tokens = common.tokenize(query)
    if len(tokens) < MIN_TOKENS_HARD:
        return False
    limit = max(1, int(n_docs * RARE_DF_RATIO))
    return any(df.get(t, 0) <= limit for t in tokens)


def _section(sec: dict[str, str], *names: str) -> str:
    for name in names:
        if sec.get(name):
            return sec[name]
    return ""


def build(docs: list[common.Doc]) -> list[dict]:
    rows: list[dict] = []
    df = _document_frequency(docs)
    n_docs = len(docs)
    for doc in docs:
        if doc.is_draft:
            continue  # o indexer nao indexa draft: nao da para recuperar
        sec = common.sections(doc.body)

        if doc.type == "erro":
            source = _section(sec, "mensagem de erro", "situacao", "problema", "intro")
            candidates = [common.clean_markdown(m) for m in BOLD_RE.findall(source)]
            body_msg = max(candidates, key=len) if candidates else ""
            title_msg = re.sub(r"^erro[:\s-]+", "", doc.title, flags=re.I).strip()
            query = body_msg if len(body_msg) >= 12 else title_msg
            if _ok(query):
                rows.append(_row("erro_literal", query, doc))

        elif doc.type == "few-shot":
            query = common.clean_markdown(_section(sec, "pergunta"))[:MAX_QUERY_CHARS]
            if _ok(query):
                rows.append(_row("fewshot_pergunta", query, doc))

        elif doc.type == "troubleshooting":
            raw = _section(sec, "problema", "situacao", "sintoma", "intro")
            query = _first_sentences(raw)
            if _ok(query):
                rows.append(_row("sintoma", query, doc))
                hard = _drop_title_terms(query, doc.title)
                if _ok_hard(hard, df, n_docs):
                    rows.append(_row("sintoma_hard", hard, doc))

        elif doc.type in ("rotina", "procedimento", "faq"):
            raw = _section(sec, "visao geral", "descricao", "objetivo", "quando usar", "intro")
            query = _first_sentences(raw)
            if _ok(query):
                rows.append(_row("rotina_objetivo", query, doc))
                hard = _drop_title_terms(query, doc.title)
                if _ok_hard(hard, df, n_docs):
                    rows.append(_row("rotina_objetivo_hard", hard, doc))

    return rows


def _row(track: str, query: str, doc: common.Doc) -> dict:
    return {
        "track": track,
        "query": " ".join(query.split()),
        "target_id": doc.id,
        "target_path": doc.path,
        "target_title": doc.title,
        "tipo": doc.type,
        "audience": doc.audience,
        "modulos": doc.modulos,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="E:/Projetos/obsidian/wiki")
    parser.add_argument("--out", default=str(Path(__file__).parent / "goldenset.jsonl"))
    parser.add_argument("--per-track", type=int, default=250, help="0 = sem amostragem")
    parser.add_argument("--seed", type=int, default=20260914)
    args = parser.parse_args()

    docs = common.load_docs(Path(args.corpus))
    rows = build(docs)

    if args.per_track:
        rng = random.Random(args.seed)
        by_track: dict[str, list[dict]] = {}
        for row in rows:
            by_track.setdefault(row["track"], []).append(row)
        sampled: list[dict] = []
        for track, items in sorted(by_track.items()):
            items.sort(key=lambda r: r["target_id"])  # determinismo
            sampled.extend(items if len(items) <= args.per_track
                           else rng.sample(items, args.per_track))
        rows = sampled

    for i, row in enumerate(rows):
        row["qid"] = f"{row['track']}-{i:05d}"

    out = Path(args.out)
    with out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"corpus: {args.corpus}  docs={len(docs)}")
    print(f"golden set: {out}  consultas={len(rows)}")
    for track, count in sorted(Counter(r["track"] for r in rows).items()):
        print(f"  {track:18s} {count:5d}")
    print("  audience:", dict(Counter(r["audience"] for r in rows)))


if __name__ == "__main__":
    main()
