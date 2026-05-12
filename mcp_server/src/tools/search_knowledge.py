from ..falkordb_repository import repo
from ..embeddings import embedding_generator
from ..telemetry import tracer

async def search_knowledge(query: str, limit: int = 5, include_analyst: bool = True):
    with tracer.start_as_current_span("tool_search_knowledge"):
        # 1. Generate query embedding
        query_vector = embedding_generator.generate(query)
        
        # 2. Search in FalkorDB
        results = repo.vector_search(query_vector, limit, include_analyst=include_analyst)
        
        formatted = []
        for r in results:
            formatted.append(f"Doc ID: {r[0]}\nTitle: {r[1]}\nPath: {r[2]}\nHeading: {r[3]}\nContent: {r[4]}\nScore: {r[5]}\n---")
            
        return "\n".join(formatted) if formatted else "No results found."
