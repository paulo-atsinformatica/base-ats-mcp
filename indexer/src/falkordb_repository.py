from falkordb import FalkorDB
from .config import settings
from .telemetry import tracer
from .logger import logger
import json

class FalkorDBRepository:
    def __init__(self):
        self.db = FalkorDB(host=settings.FALKORDB_HOST, port=settings.FALKORDB_PORT)
        self.graph = self.db.select_graph(settings.FALKORDB_GRAPH_NAME)
        self._ensure_indexes()

    def _ensure_indexes(self):
        # Tenta criar o índice vetorial — sintaxe varia por versão do FalkorDB.
        # Falha silenciosa: o serviço funciona sem índice (buscas por scan).
        strategies = [
            # FalkorDB >= 4.x
            "CALL db.idx.vector.createNodeIndex('Chunk', 'embedding', 3072, 'cosine')",
            # Sintaxe alternativa de versões mais recentes
            "CREATE VECTOR INDEX FOR (c:Chunk) ON (c.embedding) OPTIONS {dimension: 3072, similarityFunction: 'cosine'}",
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
                # Tenta próxima sintaxe
                logger.debug("vector_index_syntax_failed", error=err)
        logger.warning("vector_index_not_created", reason="no supported syntax found — scans will be used")

    def save_document(self, doc_data: dict, chunks: list, embeddings: list):
        with tracer.start_as_current_span("falkordb_save_document"):
            # 1. Clean up old data for this path
            self.delete_document(doc_data['path'])
            
            # 2. Create Document node
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
            
            # 3. Create Chunks and relate to Document
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                chunk_id = f"{doc_data['id']}#chunk_{i}"
                chunk_query = """
                MATCH (d:Document {id: $doc_id})
                CREATE (c:Chunk {
                    id: $chunk_id,
                    heading: $heading,
                    content: $content,
                    position: $pos,
                    embedding: $emb
                })
                CREATE (d)-[:HAS_CHUNK]->(c)
                """
                self.graph.query(chunk_query, {
                    "doc_id": doc_data['id'],
                    "chunk_id": chunk_id,
                    "heading": chunk['heading'],
                    "content": chunk['content'],
                    "pos": i,
                    "emb": emb
                })
                
            # 4. Handle Tags
            for tag_name in doc_data.get('tags', []):
                tag_query = """
                MATCH (d:Document {id: $doc_id})
                MERGE (t:Tag {name: $tag_name})
                MERGE (d)-[:HAS_TAG]->(t)
                """
                self.graph.query(tag_query, {"doc_id": doc_data['id'], "tag_name": tag_name})
                
            # 5. Handle Modules
            for module_slug in doc_data.get('modulos', []):
                mod_query = """
                MATCH (d:Document {id: $doc_id})
                MERGE (m:Module {slug: $mod_slug})
                MERGE (d)-[:BELONGS_TO_MODULE]->(m)
                """
                self.graph.query(mod_query, {"doc_id": doc_data['id'], "mod_slug": module_slug})

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

repo = FalkorDBRepository()
