"""Roda o golden set contra um backend de recuperacao e reporta as metricas.

Backends locais (lexicais, sem API key) servem de baseline e de ablacao:

  bm25-chunk      unidade = chunk H2, texto = SO o conteudo do chunk.
                  Paridade com a producao de hoje (indexer/src/chunker.py +
                  main.py embeddando o content puro do chunk).
  bm25-chunk-ctx  igual, mas cada chunk recebe o preambulo de contexto
                  (titulo | tipo | modulos | tags | secao) -> mede o ganho da
                  correcao proposta no chunking.
  bm25-doc        unidade = documento inteiro (1 doc = 1 vetor).
  bm25-doc-ctx    documento inteiro + preambulo de contexto.

Backend remoto:

  api             POST {url}/api/knowledge/search no MCP Server implantado.
                  Mede o sistema real (denso, FalkorDB). Consome cota do
                  Gemini: use --limit-queries.

Os numeros lexicais NAO sao uma simulacao do retriever denso; sao um piso de
referencia e, sobretudo, um teste A/B do formato da unidade indexada, que vale
para os dois tipos de busca.

Uso:
  python run_eval.py --backend bm25-chunk
  python run_eval.py --backend all
  python run_eval.py --backend api --api-url https://... --scope public
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from pathlib import Path

import common

KS = (1, 3, 5, 10)
TOP_K = 10
LOCAL_BACKENDS = ("bm25-chunk", "bm25-chunk-ctx", "bm25-doc", "bm25-doc-ctx")


def build_index(docs, backend):
    index = common.BM25()
    units = []
    for doc in docs:
        if backend == "bm25-chunk":
            for chunk in common.chunk_by_headings(doc.body):
                units.append((doc.id, chunk["content"]))
        elif backend == "bm25-chunk-ctx":
            for chunk in common.chunk_by_headings(doc.body):
                header = common.context_header(doc, chunk["heading"])
                units.append((doc.id, header + "\n" + chunk["content"]))
        elif backend == "bm25-doc":
            units.append((doc.id, doc.body))
        elif backend == "bm25-doc-ctx":
            units.append((doc.id, common.context_header(doc) + "\n" + doc.body))
        else:
            raise ValueError("backend desconhecido: " + backend)
    index.add_all(units)
    return index


def api_search(url, token, query, limit, ajustes=None):
    import httpx

    corpo = {"query": query, "limit": limit}
    # Ajuste da fusao. O servidor so aceita de token full - com token publico
    # os campos sao ignorados e a busca cai no padrao, entao uma varredura de
    # configuracao tem de ser feita com o ADMIN_TOKEN.
    corpo.update(ajustes or {})

    response = httpx.post(
        url.rstrip("/") + "/api/knowledge/search",
        json=corpo,
        headers={"X-API-Key": token},
        timeout=60.0,
    )
    response.raise_for_status()
    text = response.json().get("result", "")
    ids = []
    for line in str(text).splitlines():
        if line.startswith("Doc ID:"):
            doc_id = line.split(":", 1)[1].strip()
            if doc_id and doc_id not in ids:  # dedup: varios chunks do mesmo doc
                ids.append(doc_id)
    return ids


def evaluate(rows, retrieve, indexed_ids, analyst_ids=None):
    per_track = defaultdict(
        lambda: dict({"n": 0, "rr": 0.0}, **{"hit@%d" % k: 0 for k in KS})
    )
    skipped = 0
    leaks = []
    for row in rows:
        if row["target_id"] not in indexed_ids:
            skipped += 1  # alvo fora do escopo/indice: nao e falha do retriever
            continue
        ranked = retrieve(row["query"])
        if analyst_ids:
            vazados = [d for d in ranked if d in analyst_ids]
            if vazados:
                leaks.append({"qid": row.get("qid"), "docs": vazados})
        bucket = per_track[row["track"]]
        bucket["n"] += 1
        if row["target_id"] in ranked:
            rank = ranked.index(row["target_id"]) + 1
            bucket["rr"] += 1.0 / rank
            for k in KS:
                if rank <= k:
                    bucket["hit@%d" % k] += 1
    return {"per_track": dict(per_track), "skipped": skipped, "leaks": leaks}


def summarize(result):
    out = {"tracks": {}, "overall": {}}
    total = dict({"n": 0, "rr": 0.0}, **{"hit@%d" % k: 0 for k in KS})
    for track, bucket in sorted(result["per_track"].items()):
        n = bucket["n"] or 1
        row = {"n": bucket["n"], "mrr@10": round(bucket["rr"] / n, 4)}
        for k in KS:
            row["recall@%d" % k] = round(bucket["hit@%d" % k] / n, 4)
        out["tracks"][track] = row
        total["n"] += bucket["n"]
        total["rr"] += bucket["rr"]
        for k in KS:
            total["hit@%d" % k] += bucket["hit@%d" % k]
    n = total["n"] or 1
    overall = {"n": total["n"], "mrr@10": round(total["rr"] / n, 4)}
    for k in KS:
        overall["recall@%d" % k] = round(total["hit@%d" % k] / n, 4)
    out["overall"] = overall
    return out


def print_table(name, summary):
    print("")
    print("### " + name)
    print("| trilha | n | R@1 | R@3 | R@5 | R@10 | MRR@10 |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for track, m in summary["tracks"].items():
        print("| %s | %d | %.3f | %.3f | %.3f | %.3f | %.3f |" % (
            track, m["n"], m["recall@1"], m["recall@3"],
            m["recall@5"], m["recall@10"], m["mrr@10"]))
    m = summary["overall"]
    print("| **TOTAL** | %d | %.3f | %.3f | %.3f | %.3f | %.3f |" % (
        m["n"], m["recall@1"], m["recall@3"],
        m["recall@5"], m["recall@10"], m["mrr@10"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="E:/Projetos/obsidian/wiki")
    parser.add_argument("--goldenset", default=str(Path(__file__).parent / "goldenset.jsonl"))
    parser.add_argument("--backend", default="bm25-chunk",
                        help="bm25-chunk | bm25-chunk-ctx | bm25-doc | bm25-doc-ctx | api | all")
    parser.add_argument("--scope", choices=("full", "public"), default="full",
                        help="public = so documentos audience != analyst")
    parser.add_argument("--api-url", default=os.getenv("MCP_SERVER_URL", ""))
    parser.add_argument("--api-token", default=os.getenv("ADMIN_TOKEN", ""))
    parser.add_argument("--limit-queries", type=int, default=0, help="0 = todas")
    parser.add_argument("--track", default="", help="avaliar so uma trilha")
    # Varredura da fusao (backend api). Sem estes, o servidor usa o padrao.
    parser.add_argument("--rrf-k", type=int, default=None,
                        help="k do RRF: menor = mais peso ao topo de cada lista")
    parser.add_argument("--peso-denso", type=float, default=None)
    parser.add_argument("--peso-lexical", type=float, default=None)
    args = parser.parse_args()

    ajustes = {}
    if args.rrf_k is not None:
        ajustes["rrf_k"] = args.rrf_k
    if args.peso_denso is not None:
        ajustes["peso_denso"] = args.peso_denso
    if args.peso_lexical is not None:
        ajustes["peso_lexical"] = args.peso_lexical

    todos = common.load_docs(Path(args.corpus))
    # O indexer pula draft; o eval tem de refletir isso.
    docs = [d for d in todos if not d.is_draft]
    analyst_ids = {d.id for d in docs if d.audience == "analyst"}
    if args.scope == "public":
        docs = [d for d in docs if d.audience != "analyst"]
    indexed_ids = {d.id for d in docs}

    rows = [json.loads(line) for line in open(args.goldenset, encoding="utf-8")]
    if args.track:
        rows = [r for r in rows if r["track"] == args.track]
    if args.limit_queries:
        # Amostra ESTRATIFICADA: cortar as N primeiras linhas pegaria uma
        # trilha so (o arquivo vem ordenado por qid) e o numero nao diria nada.
        por_trilha = defaultdict(list)
        for row in rows:
            por_trilha[row["track"]].append(row)
        cota = max(1, args.limit_queries // max(1, len(por_trilha)))
        amostra = []
        for track in sorted(por_trilha):
            amostra.extend(por_trilha[track][:cota])
        rows = amostra[: args.limit_queries]

    backends = list(LOCAL_BACKENDS) if args.backend == "all" else [args.backend]
    report = {
        "corpus": args.corpus,
        "scope": args.scope,
        "docs_indexaveis": len(docs),
        "consultas": len(rows),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        # Sem registrar a configuracao, dois relatorios viram numeros soltos
        # que ninguem consegue comparar depois.
        "ajustes_fusao": ajustes or None,
        "backends": {},
    }

    for backend in backends:
        started = time.time()
        # Vazamento so faz sentido medir no backend remoto em escopo publico:
        # nos locais o filtro e aplicado na propria selecao de candidatos.
        checar_vazamento = analyst_ids if (backend == "api" and args.scope == "public") else None
        if backend == "api":
            if not args.api_url or not args.api_token:
                raise SystemExit("backend api exige --api-url e --api-token")

            def retrieve(q, _u=args.api_url, _t=args.api_token, _a=ajustes):
                return api_search(_u, _t, q, TOP_K, _a)
        else:
            index = build_index(docs, backend)

            def retrieve(q, _i=index, _a=indexed_ids):
                return [d for d, _ in _i.search(q, _a, TOP_K)]

            print("[%s] unidades indexadas: %d" % (backend, len(index.unit_doc)))
        result = evaluate(rows, retrieve, indexed_ids, checar_vazamento)
        summary = summarize(result)
        summary["skipped_alvo_fora_do_indice"] = result["skipped"]
        summary["vazamentos_analyst"] = len(result["leaks"])
        summary["segundos"] = round(time.time() - started, 1)
        report["backends"][backend] = summary
        print_table(backend, summary)
        print("    (alvos fora do indice, ignorados: %d | %.1fs)"
              % (result["skipped"], summary["segundos"]))
        if checar_vazamento is not None:
            print("    vazamento de audience=analyst em escopo publico: %d consultas"
                  % len(result["leaks"]))

    out_dir = Path(__file__).parent / "reports"
    out_dir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = out_dir / ("%s-%s-%s.json" % (stamp, args.backend, args.scope))
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("")
    print("relatorio: " + str(out))


if __name__ == "__main__":
    main()
