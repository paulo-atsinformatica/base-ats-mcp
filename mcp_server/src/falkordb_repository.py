import math

from falkordb import FalkorDB

from .config import settings
from .telemetry import tracer
from .logger import logger


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

    def vector_search(self, query_vector: list, limit: int = 5):
        with tracer.start_as_current_span("falkordb_vector_search"):
            query_vec = _vecf32_literal(query_vector)
            query = """
            CALL db.idx.vector.queryNodes('Chunk', 'embedding', $limit, __QUERY_VECTOR__)
            YIELD node, score
            MATCH (node)<-[:HAS_CHUNK]-(d:Document)
            RETURN d.id as doc_id, d.title as title, d.path as path,
                   node.heading as heading, node.content as content, score
            """.replace("__QUERY_VECTOR__", query_vec)
            try:
                res = self.graph.query(query, {"limit": limit})
                return res.result_set
            except Exception as e:
                logger.warning("vector_search_failed_falling_back_to_scan", error=str(e))
                return self._vector_search_scan(query_vector, limit)

    def _vector_search_scan(self, query_vector: list, limit: int = 5):
        """Semantic fallback: cosine similarity over stored embeddings."""
        res = self.graph.query(
            "MATCH (c:Chunk)<-[:HAS_CHUNK]-(d:Document) "
            "WHERE c.embedding IS NOT NULL "
            "RETURN d.id, d.title, d.path, c.heading, c.content, c.embedding"
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

    def get_document(self, doc_id: str):
        with tracer.start_as_current_span("falkordb_get_document"):
            query = "MATCH (d:Document {id: $doc_id}) RETURN d.title, d.raw_content, d.path, d.type"
            res = self.graph.query(query, {"doc_id": doc_id})
            if res.result_set:
                return res.result_set[0]
            return None

    def get_neighbors(self, entity_name: str, depth: int = 1, limit: int = 20):
        with tracer.start_as_current_span("falkordb_graph_neighbors"):
            safe_depth = max(1, min(int(depth), 2))
            query = (
                f"MATCH (e:Entity {{name: $name}})-[r*1..{safe_depth}]-(n) "
                "RETURN e.name, type(r[0]), n.name, labels(n)[0] LIMIT $limit"
            )
            res = self.graph.query(query, {"name": entity_name, "limit": limit})
            return res.result_set

    def check_health(self):
        try:
            self.db.connection.ping()
            return True
        except Exception as e:
            logger.error("falkordb_health_check_failed", error=str(e))
            return False


repo = FalkorDBRepository()
