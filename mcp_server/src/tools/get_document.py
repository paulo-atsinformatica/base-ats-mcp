from ..falkordb_repository import repo
from ..telemetry import tracer

async def get_document(doc_id: str):
    with tracer.start_as_current_span("tool_get_document"):
        res = repo.get_document(doc_id)
        if res:
            title, content, path, doc_type = res
            return f"Title: {title}\nType: {doc_type}\nPath: {path}\n\n{content}"
        return f"Document with ID {doc_id} not found."
