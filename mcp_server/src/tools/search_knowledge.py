from ..falkordb_repository import repo
from ..embeddings import embedding_generator
from ..telemetry import tracer

async def search_knowledge(query: str, limit: int = 5, include_analyst: bool = True,
                           rrf_k: int = 60, peso_denso: float = 1.0,
                           peso_lexical: float = 1.0):
    with tracer.start_as_current_span("tool_search_knowledge"):
        # 1. Generate query embedding
        query_vector = embedding_generator.generate(query)

        # 2. Busca hibrida: vetorial + lexical, fundidas por RRF.
        #    O texto cru vai junto porque a metade lexical precisa dele.
        #    rrf_k e os pesos existem para o harness de avaliacao varrer
        #    configuracoes sem um ciclo de deploy por valor; o atendimento
        #    normal nao os informa e cai no padrao.
        results = repo.hybrid_search(
            query_vector, query, limit, include_analyst=include_analyst,
            rrf_k=rrf_k, peso_denso=peso_denso, peso_lexical=peso_lexical,
        )

        formatted = []
        for r in results:
            formatted.append(
                f"Doc ID: {r[0]}\nTitle: {r[1]}\nPath: {r[2]}\n"
                f"Heading: {r[3]}\nContent: {r[4]}\nScore: {r[5]}\n---"
            )

        return "\n".join(formatted) if formatted else "No results found."
