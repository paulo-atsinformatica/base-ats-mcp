from ..falkordb_repository import repo
from ..telemetry import tracer

async def graph_neighbors(entity_name: str, depth: int = 1):
    with tracer.start_as_current_span("tool_graph_neighbors"):
        # Enforce safety limits
        if depth > 2:
            depth = 2
            
        results = repo.get_neighbors(entity_name, depth)
        
        if not results:
            return f"No relations found for entity: {entity_name}"
            
        formatted = [f"Relationships for '{entity_name}':"]
        for r in results:
            formatted.append(f"({r[0]}) -[{r[1]}]-> ({r[2]} : {r[3]})")
            
        return "\n".join(formatted)
