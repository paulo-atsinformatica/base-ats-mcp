"""Consultas Cypher da busca, isoladas do cliente do FalkorDB.

Ficam aqui para poderem ser executadas por um teste direto contra um FalkorDB
real sem arrastar o resto do servico (cliente, telemetria, embeddings). A
sintaxe destas consultas so se verifica no banco: um erro de digitacao em
Cypher nao aparece em revisao de codigo nem em import.
"""

# Busca lexical sobre o texto normalizado do chunk.
KEYWORD_SEARCH = """
CALL db.idx.fulltext.queryNodes('Chunk', $termos)
YIELD node, score
MATCH (node)<-[:HAS_CHUNK]-(d:Document)
WHERE $include_analyst = true OR coalesce(d.audience, 'analyst') <> 'analyst'
RETURN d.id as doc_id, d.title as title, d.path as path,
       node.heading as heading, node.content as content, score
LIMIT $limit
"""

# Busca vetorial. __QUERY_VECTOR__ e substituido por um literal vecf32([...]),
# porque o procedimento nao aceita vetor vindo de parametro.
VECTOR_SEARCH = """
CALL db.idx.vector.queryNodes('Chunk', 'embedding', $limit, __QUERY_VECTOR__)
YIELD node, score
MATCH (node)<-[:HAS_CHUNK]-(d:Document)
WHERE $include_analyst = true OR coalesce(d.audience, 'analyst') <> 'analyst'
RETURN d.id as doc_id, d.title as title, d.path as path,
       node.heading as heading, node.content as content, score
"""


def rrf_fuse(listas: list, limit: int, rrf_k: int = 60) -> list:
    """Reciprocal Rank Fusion entre varias listas ordenadas de resultados.

    Cada linha e (doc_id, title, path, heading, content, score). A fusao usa
    so a POSICAO na lista, nunca o score bruto: cosseno em [0,1] e score do
    RediSearch nao sao comparaveis, e normalizar um no outro seria inventar
    uma escala. Um chunk que aparece razoavelmente bem nas duas listas vence
    um que aparece otimo em uma so — que e exatamente o comportamento
    desejado entre busca densa e lexical.
    """
    pontos: dict = {}
    linhas: dict = {}
    for lista in listas:
        for posicao, linha in enumerate(lista):
            # Chave por chunk: documento + secao.
            chave = (linha[0] or linha[2], linha[3])
            pontos[chave] = pontos.get(chave, 0.0) + 1.0 / (rrf_k + posicao + 1)
            linhas.setdefault(chave, linha)

    ordenado = sorted(pontos.items(), key=lambda kv: kv[1], reverse=True)
    resultado = []
    for chave, score in ordenado[:limit]:
        linha = list(linhas[chave])
        linha[5] = score  # o score devolvido passa a ser o do RRF
        resultado.append(linha)
    return resultado
