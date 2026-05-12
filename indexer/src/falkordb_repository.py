from falkordb import FalkorDB
import math

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
        self._ensure_indexes()

    def _ensure_indexes(self):
        strategies = [
            "CREATE VECTOR INDEX FOR (c:Chunk) ON (c.embedding) "
            "OPTIONS {dimension: 3072, similarityFunction: 'cosine'}",
            "CALL db.idx.vector.createNodeIndex('Chunk', 'embedding', 3072, 'cosine')",
        ]
        for stmt in strategies:
            try:
                self.graph.query(stmt)
                logger.info("vector_index_ensured")
                return
            except Exception as e:
                err = str(e)
                if "already exists" in err or "Index already exists" in err:
                    logger.debug("vector_index_exists")
                    return
                logger.debug("vector_index_syntax_failed", error=err)
        logger.warning("vector_index_not_created", reason="no supported syntax found; scans will be used")

    def save_document(self, doc_data: dict, chunks: list, embeddings: list):
        with tracer.start_as_current_span("falkordb_save_document"):
            self.delete_document(doc_data["path"])

            query = """
            MERGE (d:Document {id: $id})
            SET d.path = $path,
                d.title = $title,
                d.type = $type,
                d.audience = $audience,
                d.status = $status,
                d.content_hash = $content_hash,
                d.updated_at = $updated_at,
                d.raw_content = $raw_content
            """
            self.graph.query(query, doc_data)

            for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                chunk_id = f"{doc_data['id']}#chunk_{i}"
                embedding_literal = _vecf32_literal(emb)
                chunk_query = """
                MATCH (d:Document {id: $doc_id})
                CREATE (c:Chunk {
                    id: $chunk_id,
                    heading: $heading,
                    content: $content,
                    position: $pos,
                    embedding: __EMBEDDING__
                })
                CREATE (d)-[:HAS_CHUNK]->(c)
                """.replace("__EMBEDDING__", embedding_literal)
                self.graph.query(
                    chunk_query,
                    {
                        "doc_id": doc_data["id"],
                        "chunk_id": chunk_id,
                        "heading": chunk["heading"],
                        "content": chunk["content"],
                        "pos": i,
                    },
                )

            for tag_name in doc_data.get("tags", []):
                tag_query = """
                MATCH (d:Document {id: $doc_id})
                MERGE (t:Tag {name: $tag_name})
                MERGE (d)-[:HAS_TAG]->(t)
                """
                self.graph.query(tag_query, {"doc_id": doc_data["id"], "tag_name": tag_name})

            for module_slug in doc_data.get("modulos", []):
                mod_query = """
                MATCH (d:Document {id: $doc_id})
                MERGE (m:Module {slug: $mod_slug})
                MERGE (d)-[:BELONGS_TO_MODULE]->(m)
                """
                self.graph.query(mod_query, {"doc_id": doc_data["id"], "mod_slug": module_slug})

            self._save_entities(doc_data)

    def _save_entities(self, doc_data: dict):
        entities = doc_data.get("entities", [])
        for entity in entities:
            entity_query = """
            MATCH (d:Document {id: $doc_id})
            MERGE (e:Entity {name: $name})
            SET e.display_name = $display_name,
                e.type = $type
            MERGE (d)-[:MENTIONS]->(e)
            """
            self.graph.query(
                entity_query,
                {
                    "doc_id": doc_data["id"],
                    "name": entity["name"],
                    "display_name": entity["display_name"],
                    "type": entity["type"],
                },
            )

            if entity["type"] == "module":
                module_query = """
                MATCH (e:Entity {name: $entity_name})
                MERGE (m:Module {slug: $module_slug})
                MERGE (e)-[:IN_MODULE]->(m)
                """
                self.graph.query(
                    module_query,
                    {"entity_name": entity["name"], "module_slug": entity["name"]},
                )

            if entity["type"] == "tag":
                tag_query = """
                MATCH (e:Entity {name: $entity_name})
                MERGE (t:Tag {name: $tag_name})
                MERGE (e)-[:HAS_TAG_ENTITY]->(t)
                """
                self.graph.query(tag_query, {"entity_name": entity["name"], "tag_name": entity["name"]})

    def delete_document(self, path: str):
        with tracer.start_as_current_span("falkordb_delete_document"):
            query = """
            MATCH (d:Document {path: $path})
            OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk)
            DETACH DELETE c
            DETACH DELETE d
            """
            self.graph.query(query, {"path": path})

    def get_file_hash(self, path: str):
        query = "MATCH (d:Document {path: $path}) RETURN d.content_hash"
        res = self.graph.query(query, {"path": path})
        if res.result_set:
            return res.result_set[0][0]
        return None

    def list_all_document_paths(self) -> list[str]:
        query = "MATCH (d:Document) RETURN d.path"
        res = self.graph.query(query)
        return [row[0] for row in res.result_set] if res.result_set else []


repo = FalkorDBRepository()
