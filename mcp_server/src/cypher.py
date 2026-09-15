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


RRF_K_PADRAO = 60
PESO_PADRAO = 1.0


def rrf_fuse(listas: list, limit: int, rrf_k: int = RRF_K_PADRAO,
             pesos: list | None = None) -> list:
    """Reciprocal Rank Fusion entre varias listas ordenadas de resultados.

    Cada linha e (doc_id, title, path, heading, content, score). A fusao usa
    so a POSICAO na lista, nunca o score bruto: cosseno em [0,1] e score do
    RediSearch nao sao comparaveis, e normalizar um no outro seria inventar
    uma escala.

    `rrf_k` decide QUANTO a co-ocorrencia vale contra a relevancia isolada, e
    nao e detalhe: com k=60, um chunk em 11o lugar nas DUAS listas (2/70) ganha
    do 1o colocado da densa ausente na lexical (1/61). Isso e otimo quando as
    duas metades tem sinal (mensagem de erro colada) e pessimo quando a lexical
    e ruido (sintoma parafraseado, sem os termos do titulo). Medido em
    2026-09-14 sobre 600 consultas: k=60 manteve R@10 mas derrubou R@1 de 0,517
    para 0,338 contra a busca densa pura.

    `pesos` multiplica a contribuicao de cada lista, na mesma ordem de
    `listas` - serve para dar mais voz a densa sem desligar a lexical.
    """
    if pesos is None:
        pesos = [PESO_PADRAO] * len(listas)

    pontos: dict = {}
    linhas: dict = {}
    for indice, lista in enumerate(listas):
        peso = pesos[indice] if indice < len(pesos) else PESO_PADRAO
        for posicao, linha in enumerate(lista):
            # Chave por chunk: documento + secao.
            chave = (linha[0] or linha[2], linha[3])
            pontos[chave] = pontos.get(chave, 0.0) + peso / (rrf_k + posicao + 1)
            linhas.setdefault(chave, linha)

    ordenado = sorted(pontos.items(), key=lambda kv: kv[1], reverse=True)
    resultado = []
    for chave, score in ordenado[:limit]:
        linha = list(linhas[chave])
        linha[5] = score  # o score devolvido passa a ser o do RRF
        resultado.append(linha)
    return resultado
