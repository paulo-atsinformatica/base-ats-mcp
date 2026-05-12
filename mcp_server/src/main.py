import asyncio
import sys
import os
import httpx
from typing import Optional, Any
from fastapi import FastAPI, HTTPException, Security, Request, Depends
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse
from mcp.server import Server
import mcp.types as types
from pydantic import BaseModel

from .config import settings
from .logger import logger
from .telemetry import tracer
from .tools.search_knowledge import search_knowledge
from .tools.get_document import get_document
from .tools.graph_neighbors import graph_neighbors

# ─────────────────────────────────────────────
# Configuração de Segurança
# ─────────────────────────────────────────────

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_api_key(api_key: str = Security(api_key_header)):
    if not api_key or api_key != settings.ADMIN_TOKEN:
        raise HTTPException(
            status_code=403,
            detail="Acesso negado: X-API-Key inválida ou ausente."
        )
    return api_key

# ─────────────────────────────────────────────
# Inicialização do Servidor MCP
# ─────────────────────────────────────────────

mcp_server = Server("erp-kb-graphrag")

@mcp_server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_knowledge",
            description="Busca semântica (RAG) na base de conhecimento do ERP.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Termo ou pergunta de busca"},
                    "limit": {"type": "integer", "description": "Máximo de resultados", "default": 5},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_document",
            description="Recupera o conteúdo completo de um documento técnico pelo ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "ID único do documento"},
                },
                "required": ["doc_id"],
            },
        ),
        types.Tool(
            name="graph_neighbors",
            description="Explora relações no grafo de conhecimento.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_name": {"type": "string", "description": "Nome da entidade"},
                    "depth": {"type": "integer", "description": "Profundidade", "default": 1},
                },
                "required": ["entity_name"],
            },
        ),
    ]

@mcp_server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    if not arguments: arguments = {}
    try:
        if name == "search_knowledge":
            result = await search_knowledge(arguments.get("query"), arguments.get("limit", 5))
            return [types.TextContent(type="text", text=str(result))]
        elif name == "get_document":
            result = await get_document(arguments.get("doc_id"))
            return [types.TextContent(type="text", text=str(result))]
        elif name == "graph_neighbors":
            result = await graph_neighbors(arguments.get("entity_name"), arguments.get("depth", 1))
            return [types.TextContent(type="text", text=str(result))]
        else:
            raise ValueError(f"Ferramenta desconhecida: {name}")
    except Exception as e:
        logger.error("tool_execution_failed", tool=name, error=str(e))
        return [types.TextContent(type="text", text=f"Erro: {str(e)}")]

# ─────────────────────────────────────────────
# FastAPI (OpenAPI + Stateless MCP HTTP)
# ─────────────────────────────────────────────

app = FastAPI(title="ERP KB GraphRAG API", version="1.0.0")

@app.post("/mcp", tags=["mcp"], dependencies=[Depends(get_api_key)])
async def handle_mcp_stateless(request: Request):
    """
    Endpoint MCP Stateless (JSON-RPC sobre HTTP).
    Recebe uma requisição JSON-RPC, processa e retorna a resposta.
    """
    payload = await request.json()
    
    # Se for um list_tools
    if payload.get("method") == "tools/list":
        tools = await handle_list_tools()
        return {
            "jsonrpc": "2.0",
            "id": payload.get("id"),
            "result": {"tools": [t.model_dump() for t in tools]}
        }
    
    # Se for uma chamada de tool
    if payload.get("method") == "tools/call":
        params = payload.get("params", {})
        name = params.get("name")
        args = params.get("arguments")
        
        result = await handle_call_tool(name, args)
        return {
            "jsonrpc": "2.0",
            "id": payload.get("id"),
            "result": {"content": [c.model_dump() for c in result]}
        }

    return {"jsonrpc": "2.0", "id": payload.get("id"), "error": {"code": -32601, "message": "Method not found"}}

# ─────────────────────────────────────────────
# Endpoints REST (ChatGPT Actions)
# ─────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    limit: Optional[int] = 5

@app.post("/api/knowledge/search", tags=["knowledge"], dependencies=[Depends(get_api_key)])
async def api_search(req: SearchRequest):
    return {"result": await search_knowledge(req.query, req.limit)}

@app.get("/api/knowledge/document/{doc_id}", tags=["knowledge"], dependencies=[Depends(get_api_key)])
async def api_get_doc(doc_id: str):
    return {"result": await get_document(doc_id)}

@app.get("/health")
async def health_check():
    from .falkordb_repository import repo
    return {"status": "ok" if repo.check_health() else "degraded"}

@app.post("/api/admin/sync", tags=["admin"], dependencies=[Depends(get_api_key)])
async def trigger_sync():
    """Aciona re-indexação no Indexer Service (git pull + sync)."""
    INDEXER_INTERNAL_URL = "http://indexer:9000"
    logger.info("manual_sync_triggered")
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(f"{INDEXER_INTERNAL_URL}/trigger")
            response.raise_for_status()
            return response.json()
    except httpx.RequestError as e:
        logger.error("indexer_unreachable", error=str(e))
        raise HTTPException(status_code=503, detail="Indexer service unavailable")

@app.get("/")
async def root():
    return {"mcp_endpoint": "/mcp", "openapi": "/openapi.json"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.MCP_PORT)
