# Arquitetura — ERP KB FalkorDB

## Visão Geral

```
GitHub (wiki/) ─── push ──► GitHub Actions ──► POST /sync
                                                     │
                                              [MCP Server]
                                                     │
                                              [Indexer Service]
                                                     │
                                              [FalkorDB Graph]
                                                     │
                                              [MCP Server] ◄── Agente IA
```

## Componentes

### 1. FalkorDB
- Banco de grafos + vetores.
- Armazena nós: `Document`, `Chunk`, `Tag`, `Module`, `Entity`.
- Relações: `HAS_CHUNK`, `HAS_TAG`, `BELONGS_TO_MODULE`, `RELATED_TO`.
- Índice vetorial na propriedade `embedding` dos nós `Chunk` (cosine, 384 dims).

### 2. Indexer Service
| Módulo | Responsabilidade |
|---|---|
| `markdown_parser.py` | Lê frontmatter e corpo do `.md` |
| `chunker.py` | Divide conteúdo por headings H1/H2 |
| `embeddings.py` | Gera vetores com `all-MiniLM-L6-v2` |
| `falkordb_repository.py` | Persiste e atualiza grafos no banco |
| `main.py` | Orquestra o sync, verifica hashes, ignora drafts |

**Lógica de Sincronização:**
1. Para cada `.md` no volume `wiki/`:
   - Se `status: draft` → apaga entrada antiga (se existir) e ignora.
   - Calcula SHA-256 do conteúdo.
   - Se hash igual ao armazenado → sem mudança, ignora.
   - Se diferente → re-indexa completamente (apaga chunks antigos, recria).

### 3. MCP Server
Exposição de tools via protocolo MCP sobre FastAPI/SSE.

| Tool | Parâmetros | Descrição |
|---|---|---|
| `search_knowledge` | `query`, `limit` | Busca semântica por similaridade vetorial |
| `get_document` | `doc_id` | Retorna conteúdo original completo |
| `graph_neighbors` | `entity_name`, `depth` | Explora relações do grafo (máx depth=2) |

**Segurança:**
- Header `X-Admin-Token` obrigatório no endpoint `/sync`.
- FalkorDB não é exposto externamente (rede Docker interna).

## Modelo de Dados (Cypher)

```cypher
// Nós
(:Document {id, path, title, type, audience, status, content_hash, updated_at, raw_content})
(:Chunk {id, heading, content, position, embedding})
(:Tag {name})
(:Module {slug})
(:Entity {name, type})

// Relações
(:Document)-[:HAS_CHUNK]->(:Chunk)
(:Document)-[:HAS_TAG]->(:Tag)
(:Document)-[:BELONGS_TO_MODULE]->(:Module)
(:Document)-[:RELATED_TO]->(:Entity)
```

## Fluxo de Atualização Automática

1. Analista edita um `.md` e faz commit/push no GitHub.
2. GitHub Actions executa o workflow `sync.yml`.
3. O workflow faz `POST /sync` com o `ADMIN_TOKEN`.
4. O MCP Server aciona o Indexer.
5. O Indexer detecta o arquivo alterado via hash e re-indexa.
6. O agente de IA automaticamente passa a ver o conteúdo atualizado.

## Recursos de RAM (VPS 8 GB)

| Componente | RAM estimada |
|---|---|
| FalkorDB | ~800 MB – 1.2 GB |
| Indexer (com modelo MiniLM carregado) | ~300 MB |
| MCP Server (FastAPI) | ~150 MB |
| SO + buffers | ~1.5 GB |
| **Total estimado** | **~3.5 GB** |

> Sobram ~4.5 GB livres. O VPS de 8 GB é mais que suficiente para este MVP.
