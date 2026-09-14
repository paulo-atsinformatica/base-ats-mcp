import math

from falkordb import FalkorDB

from .config import settings
from .telemetry import tracer
from .logger import logger
from .text_normalize import to_fulltext_query
from .cypher import KEYWORD_SEARCH, VECTOR_SEARCH, rrf_fuse


def _vecf32_literal(values: list) -> str:
    safe_values = []
    for value in values:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Embedding contains non-finite value")
        safe_values.append(repr(number))
    return f"vecf32([{', '.join(safe_values)}])"


class FalkorDBRepository:
    def __init__(self):
        self.db = FalkorDB(host=settings.FALKORDB_HOST, port=settings.FALKORDB_PORT)
        self.graph = self.db.select_graph(settings.FALKORDB_GRAPH_NAME)

    def hybrid_search(self, query_vector: list, query_text: str, limit: int = 5,
                      include_analyst: bool = True, rrf_k: int = 60):
        """Funde busca vetorial e lexical por Reciprocal Rank Fusion.

        As duas metades da base pedem mecanismos diferentes, e foi medido em
        eval/: em mensagem de erro colada literalmente (CIDADES3, PARAMDAV,
        rejeicao 491) o BM25 puro faz recall@5 = 0,98, patamar que busca densa
        raramente alcanca em identificador exato; ja em pergunta parafraseada
        de cliente o lexical cai para ~0,64, que e onde o denso ganha.

        RRF soma 1/(k + posicao) de cada lista. Usa so a POSICAO, nunca o score
        bruto — os dois sistemas pontuam em escalas incomparaveis (cosseno em
        [0,1] contra score do RediSearch, que aqui volta como inteiro).
        """
        with tracer.start_as_current_span("falkordb_hybrid_search"):
            # Buscar fundo em cada lista: um documento que aparece em 6o lugar
            # numa e ausente na outra ainda pode vencer depois da fusao.
            fundo = max(limit * 4, 20)
            densa = self.vector_search(query_vector, fundo, include_analyst)
            lexical = self.keyword_search(query_text, fundo, include_analyst)
            return rrf_fuse([densa, lexical], limit, rrf_k)

    def keyword_search(self, query_text: str, limit: int = 5, include_analyst: bool = True):
        """Busca lexical no indice full-text, sobre Chunk.search_text."""
        with tracer.start_as_current_span("falkordb_keyword_search"):
            termos = to_fulltext_query(query_text)
            if not termos:
                return []
            query = KEYWORD_SEARCH
            try:
                res = self.graph.query(
                    query,
                    {"termos": termos, "include_analyst": include_analyst, "limit": limit},
                )
                return res.result_set or []
            except Exception as e:
                # Indice ainda nao criado (base indexada por versao anterior):
                # a busca continua funcionando so com o vetorial.
                logger.warning("keyword_search_failed", error=str(e)[:200])
                return []

    def vector_search(self, query_vector: list, limit: int = 5, include_analyst: bool = True):
        with tracer.start_as_current_span("falkordb_vector_search"):
            query_vec = _vecf32_literal(query_vector)
            query = VECTOR_SEARCH.replace("__QUERY_VECTOR__", query_vec)
            try:
                res = self.graph.query(query, {"limit": limit, "include_analyst": include_analyst})
                return res.result_set
            except Exception as e:
                logger.warning("vector_search_failed_falling_back_to_scan", error=str(e))
                return self._vector_search_scan(query_vector, limit, include_analyst)

    def _vector_search_scan(self, query_vector: list, limit: int = 5, include_analyst: bool = True):
        """Semantic fallback: cosine similarity over stored embeddings."""
        res = self.graph.query(
            "MATCH (c:Chunk)<-[:HAS_CHUNK]-(d:Document) "
            "WHERE c.embedding IS NOT NULL "
            "AND ($include_analyst = true OR coalesce(d.audience, 'analyst') <> 'analyst') "
            "RETURN d.id, d.title, d.path, c.heading, c.content, c.embedding",
            {"include_analyst": include_analyst},
        )
        results = []
        qnorm = math.sqrt(sum(x * x for x in query_vector)) or 1.0
        for row in res.result_set:
            embedding = row[5]
            if not embedding:
                continue
            dot = sum(a * b for a, b in zip(query_vector, embedding))
            enorm = math.sqrt(sum(x * x for x in embedding)) or 1.0
            score = dot / (qnorm * enorm)
            results.append((row[0], row[1], row[2], row[3], row[4], score))
        results.sort(key=lambda r: r[5], reverse=True)
        return [list(r) for r in results[:limit]]

    def get_document(self, doc_id: str, include_analyst: bool = True):
        with tracer.start_as_current_span("falkordb_get_document"):
            query = (
                "MATCH (d:Document {id: $doc_id}) "
                "WHERE $include_analyst = true OR coalesce(d.audience, 'analyst') <> 'analyst' "
                "RETURN d.title, d.raw_content, d.path, d.type"
            )
            res = self.graph.query(query, {"doc_id": doc_id, "include_analyst": include_analyst})
            if res.result_set:
                return res.result_set[0]
            return None

    def get_neighbors(self, entity_name: str, depth: int = 1, limit: int = 20,
                      include_analyst: bool = True):
        with tracer.start_as_current_span("falkordb_graph_neighbors"):
            safe_depth = max(1, min(int(depth), 2))
            normalized_name = " ".join(entity_name.strip().lower().split())

            # Escopo publico: a entidade so pode ser explorada se algum
            # documento nao-analyst a cita. Nome de tabela ou de ferramenta
            # interna que so aparece em pagina analyst e, ele proprio,
            # informacao restrita.
            if not include_analyst and not self._entity_is_public(normalized_name):
                return []

            # Busca a mais para compensar o que o filtro de audience descarta.
            fetch = limit if include_analyst else limit * 3
            query = (
                f"MATCH (e:Entity)-[r*1..{safe_depth}]-(n) "
                "WHERE e.name = $name OR toLower(e.display_name) = $name "
                "RETURN e.display_name, type(r[0]), "
                "coalesce(n.display_name, n.name, n.title, n.slug, n.id, n.path), "
                "labels(n)[0], coalesce(n.audience, ''), coalesce(n.name, '') "
                "LIMIT $limit"
            )
            res = self.graph.query(query, {"name": normalized_name, "limit": fetch})
            rows = res.result_set or []

            if include_analyst:
                return [row[:4] for row in rows]
            return self._filter_public(rows, limit)

    def _entity_is_public(self, normalized_name: str) -> bool:
        query = (
            "MATCH (d:Document)-[:MENTIONS]->(e:Entity) "
            "WHERE (e.name = $name OR toLower(e.display_name) = $name) "
            "AND coalesce(d.audience, 'analyst') <> 'analyst' "
            "RETURN count(d) LIMIT 1"
        )
        res = self.graph.query(query, {"name": normalized_name})
        return bool(res.result_set and res.result_set[0][0])

    def _filter_public(self, rows: list, limit: int) -> list:
        """Remove do resultado tudo que so existe em documento audience=analyst.

        Sao dois vazamentos distintos: o titulo/caminho do documento restrito,
        e o nome de entidade que so aparece nesses documentos.
        """
        sem_doc_restrito = [
            row for row in rows
            if not (row[3] == "Document" and (row[4] or "analyst") == "analyst")
        ]

        nomes_entidade = {row[5] for row in sem_doc_restrito if row[3] == "Entity" and row[5]}
        publicas: set = set()
        if nomes_entidade:
            res = self.graph.query(
                "MATCH (d:Document)-[:MENTIONS]->(e:Entity) "
                "WHERE e.name IN $names "
                "AND coalesce(d.audience, 'analyst') <> 'analyst' "
                "RETURN DISTINCT e.name",
                {"names": list(nomes_entidade)},
            )
            publicas = {row[0] for row in (res.result_set or [])}

        visiveis = [
            row for row in sem_doc_restrito
            if row[3] != "Entity" or row[5] in publicas
        ]
        return [row[:4] for row in visiveis[:limit]]

    def check_health(self):
        try:
            self.db.connection.ping()
            return True
        except Exception as e:
            logger.error("falkordb_health_check_failed", error=str(e))
            return False


repo = FalkorDBRepository()
