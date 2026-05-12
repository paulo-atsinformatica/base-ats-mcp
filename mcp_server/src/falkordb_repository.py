from falkordb import FalkorDB
from .config import settings
from .telemetry import tracer
from .logger import logger

class FalkorDBRepository:
    def __init__(self):
        self.db = FalkorDB(host=settings.FALKORDB_HOST, port=settings.FALKORDB_PORT)
        self.graph = self.db.select_graph(settings.FALKORDB_GRAPH_NAME)

    def vector_search(self, query_vector: list, limit: int = 5):
        with tracer.start_as_current_span("falkordb_vector_search"):
            # Procedimento queryNodes: (index_name, k, vector, [filter])
            # Algumas versões do FalkorDB exigem 4 argumentos
            query = """
            CALL db.idx.vector.queryNodes('chunk_vector_idx', $limit, $query_vector, null)
            YIELD node, score
            MATCH (node)<-[:HAS_CHUNK]-(d:Document)
            RETURN d.id as doc_id, d.title as title, d.path as path,
                   node.heading as heading, node.content as content, score
            """
            try:
                res = self.graph.query(query, {"query_vector": query_vector, "limit": limit})
                return res.result_set
            except Exception as e:
                logger.warning("vector_search_failed_falling_back", error=str(e))
                return self._vector_search_scan(query_vector, limit)

    def _vector_search_scan(self, query_vector: list, limit: int = 5):
        """Fallback: cosine similarity calculado no Python via scan do grafo."""
        import math
        res = self.graph.query(
            "MATCH (c:Chunk)<-[:HAS_CHUNK]-(d:Document) "
            "WHERE c.embedding IS NOT NULL "
            "RETURN d.id, d.title, d.path, c.heading, c.content, c.embedding"
        )
        results = []
        qv = query_vector
        qnorm = math.sqrt(sum(x * x for x in qv)) or 1.0
        for row in res.result_set:
            emb = row[5]
            if not emb:
                continue
            dot = sum(a * b for a, b in zip(qv, emb))
            enorm = math.sqrt(sum(x * x for x in emb)) or 1.0
            score = dot / (qnorm * enorm)
            results.append((row[0], row[1], row[2], row[3], row[4], score))
        results.sort(key=lambda r: r[5], reverse=True)
        return [list(r) for r in results[:limit]]

    def get_document(self, doc_id: str):
        with tracer.start_as_current_span("falkordb_get_document"):
            query = "MATCH (d:Document {id: $doc_id}) RETURN d.title, d.raw_content, d.path, d.type"
            res = self.graph.query(query, {"doc_id": doc_id})
            if res.result_set:
                return res.result_set[0]
            return None

    def get_neighbors(self, entity_name: str, depth: int = 1, limit: int = 20):
        with tracer.start_as_current_span("falkordb_graph_neighbors"):
            query = """
            MATCH (e:Entity {name: $name})-[r*1..$depth]-(n)
            RETURN e.name as source, type(r[0]) as relation, n.name as target, labels(n)[0] as target_type
            LIMIT $limit
            """
            # depth in path needs to be handled carefully in cypher
            # For MVP, we'll use a simpler version or string formatting if safe
            query = f"MATCH (e:Entity {{name: $name}})-[r*1..{depth}]-(n) RETURN e.name, type(r[0]), n.name, labels(n)[0] LIMIT $limit"
            res = self.graph.query(query, {"name": entity_name, "limit": limit})
            return res.result_set

    def check_health(self):
        try:
            # A classe FalkorDB não tem ping(), mas o objeto de conexão sim
            self.db.connection.ping()
            return True
        except Exception as e:
            logger.error("falkordb_health_check_failed", error=str(e))
            return False

repo = FalkorDBRepository()
