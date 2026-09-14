"""Testa a busca hibrida: Cypher real contra um FalkorDB real + fusao RRF.

O Cypher e importado de mcp_server/src/cypher.py, o mesmo texto que roda em
producao — nao uma copia. Erro de sintaxe Cypher nao aparece em revisao nem em
import, so executando.

Sobe um FalkorDB descartavel:
  docker run -d --name erp-kb-fts-test -p 16379:6379 falkordb/falkordb:latest
  python tests/test_hybrid_search.py
  docker rm -f erp-kb-fts-test

Porta configuravel por FALKORDB_TEST_PORT.
"""
import os
import sys
from pathlib import Path

import redis

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "mcp_server"))

from src.cypher import KEYWORD_SEARCH, rrf_fuse  # noqa: E402
from src.text_normalize import normalize, to_fulltext_query  # noqa: E402

PORTA = int(os.getenv("FALKORDB_TEST_PORT", "16379"))
GRAFO = "teste_hibrido"

falhas = 0


def check(rotulo, condicao, detalhe=""):
    global falhas
    if not condicao:
        falhas += 1
    print("  [%s] %s%s" % ("PASS" if condicao else "FAIL", rotulo,
                           (" - " + detalhe) if detalhe else ""))


class Grafo:
    def __init__(self, conn):
        self.conn = conn

    def query(self, cypher, params=None):
        args = ["GRAPH.QUERY", GRAFO]
        if params:
            # O cliente oficial monta o prefixo CYPHER; aqui e feito a mao.
            prefixo = " ".join(
                "%s=%s" % (k, _literal(v)) for k, v in params.items()
            )
            args.append("CYPHER " + prefixo + " " + cypher)
        else:
            args.append(cypher)
        return self.conn.execute_command(*args)


def _literal(valor):
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, (int, float)):
        return str(valor)
    return "'" + str(valor).replace("'", "\\'") + "'"


def semear(g):
    g.query("MATCH (n) DETACH DELETE n")
    docs = [
        # (id, titulo, audience, heading, conteudo)
        ("ERR-cidades3", "Erro: A component named CIDADES3 already exists", "analyst",
         "Solucao", "Acesse o banco e localize em Indices o indice CIDADES3."),
        ("TS-varios-pedidos", "Access violation na selecao de pedidos", "analyst",
         "Causa", "A rotina verifica registro da filial na tabela PARAMDAV."),
        ("ROT-troca", "Abatimento do Financeiro na Troca", "all",
         "Visao Geral", "O valor da devolucao feita na troca e descontado do contas a receber."),
        ("FAQ-nfce", "NFC-e rejeicao 491 tpEvento invalido", "all",
         "Solucao", "Verifique o tipo de evento enviado para a Sefaz na NFC-e."),
    ]
    for doc_id, titulo, audience, heading, conteudo in docs:
        g.query(
            "CREATE (d:Document {id:%s, title:%s, path:%s, audience:%s})"
            "-[:HAS_CHUNK]->(:Chunk {heading:%s, content:%s, search_text:%s})"
            % (_literal(doc_id), _literal(titulo), _literal(doc_id + ".md"),
               _literal(audience), _literal(heading), _literal(conteudo),
               _literal(normalize(titulo + " " + heading + " " + conteudo)))
        )
    try:
        g.query("CALL db.idx.fulltext.createNodeIndex('Chunk', 'search_text')")
    except redis.ResponseError as e:
        if "already" not in str(e):
            raise


def buscar(g, texto, include_analyst=True, limit=10):
    termos = to_fulltext_query(texto)
    if not termos:
        return []
    res = g.query(KEYWORD_SEARCH, {
        "termos": termos, "include_analyst": include_analyst, "limit": limit,
    })
    return res[1] or []


def main():
    conn = redis.Redis(host="localhost", port=PORTA, decode_responses=True)
    try:
        conn.ping()
    except Exception as e:
        print("FalkorDB nao esta acessivel na porta %d: %s" % (PORTA, e))
        print("suba com: docker run -d --name erp-kb-fts-test -p %d:6379 "
              "falkordb/falkordb:latest" % PORTA)
        return 2

    g = Grafo(conn)
    semear(g)

    print("normalizacao e consulta:")
    check("acento sai do texto indexado", "rejeicao" in normalize("NFC-e rejeição 491"))
    # Termo de 1 caractere e descartado: o "e" de "NFC-e" nao discrimina nada
    # e o hifen, cru, seria negacao na sintaxe do RediSearch.
    check("hifen vira separador e letra solta cai",
          to_fulltext_query("NFC-e") == "nfc", to_fulltext_query("NFC-e"))
    check("aspas e arroba nao sobrevivem",
          to_fulltext_query('erro "ao" a@b') == "erro|ao",
          to_fulltext_query('erro "ao" a@b'))
    check("termo repetido entra uma vez so",
          to_fulltext_query("nota nota fiscal") == "nota|fiscal")
    check("consulta vazia nao vira busca", to_fulltext_query("!!! ?") == "")

    print("\nbusca lexical (Cypher real):")
    ids = [linha[0] for linha in buscar(g, "CIDADES3")]
    check("acha por identificador exato", ids == ["ERR-cidades3"], str(ids))

    ids = [linha[0] for linha in buscar(g, "erro na tabela PARAMDAV")]
    check("acha nome de tabela no meio da frase", "TS-varios-pedidos" in ids, str(ids))

    ids = [linha[0] for linha in buscar(g, "rejeição 491 da NFC-e")]
    check("consulta acentuada acha doc sem acento", "FAQ-nfce" in ids, str(ids))

    ids = [linha[0] for linha in buscar(g, "abatimento xyzinexistente")]
    check("termos em OR, nao AND", "ROT-troca" in ids, str(ids))

    print("\nfiltro de audience:")
    ids = [linha[0] for linha in buscar(g, "CIDADES3 PARAMDAV troca", include_analyst=False)]
    check("escopo publico nao devolve documento analyst",
          all(i in ("ROT-troca", "FAQ-nfce") for i in ids), str(ids))
    check("escopo publico ainda devolve o que e publico", "ROT-troca" in ids, str(ids))
    ids = [linha[0] for linha in buscar(g, "CIDADES3 PARAMDAV troca", include_analyst=True)]
    check("escopo interno devolve os restritos", "ERR-cidades3" in ids, str(ids))

    print("\nfusao RRF:")
    densa = [["A", "t", "p", "h1", "c", 0.9], ["B", "t", "p", "h1", "c", 0.8]]
    lexical = [["B", "t", "p", "h1", "c", 7], ["C", "t", "p", "h1", "c", 3]]
    fundido = [linha[0] for linha in rrf_fuse([densa, lexical], 3)]
    check("quem aparece nas duas listas vence", fundido[0] == "B", str(fundido))
    check("fusao mantem os demais", sorted(fundido) == ["A", "B", "C"], str(fundido))
    check("score devolvido e o do RRF",
          all(0 < linha[5] < 1 for linha in rrf_fuse([densa, lexical], 3)))
    check("lista vazia nao quebra", rrf_fuse([[], []], 5) == [])

    print("\n%s" % ("todos os testes passaram" if falhas == 0 else "%d falha(s)" % falhas))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
