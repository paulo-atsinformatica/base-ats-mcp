# Arquitetura - ERP KB FalkorDB

## Visao geral

```text
GitHub wiki/*.md -> GitHub Actions -> POST /api/admin/sync
                                      |
                                      v
                                MCP Server
                                      |
                                      v
                                Indexer Service
                                      |
                                      v
                                FalkorDB Graph
                                      |
                                      v
                           ChatGPT Actions / agentes IA
```

## Componentes

### FalkorDB

- Banco de grafos com suporte a indice vetorial.
- Armazena nos `Document`, `Chunk`, `Tag` e `Module`.
- Relacoes: `HAS_CHUNK`, `HAS_TAG` e `BELONGS_TO_MODULE`.
- O embedding dos chunks usa `models/gemini-embedding-2`, com indice vetorial `cosine` de 3072 dimensoes.
- A busca vetorial usa a assinatura atual do FalkorDB:
  `db.idx.vector.queryNodes('Chunk', 'embedding', k, vecf32([...]))`.

### Indexer Service

| Modulo | Responsabilidade |
|---|---|
| `markdown_parser.py` | Le frontmatter e corpo do `.md` |
| `chunker.py` | Divide conteudo por headings H1/H2 |
| `embeddings.py` | Gera embeddings com Google Gemini |
| `falkordb_repository.py` | Persiste documentos, chunks e relacionamentos no FalkorDB |
| `main.py` | Orquestra sync, `git pull`, hash de conteudo e remocao de deletados |

Logica de sincronizacao:

1. Faz `git pull` no repositorio da wiki.
2. Para cada `.md` em `WIKI_PATH`, exceto `index.md` e `log.md`:
   - Se `status: draft`, remove o documento antigo do grafo e ignora.
   - Calcula SHA-256 do conteudo.
   - Se o hash for igual ao armazenado, nao reindexa.
   - Se mudou, remove os chunks antigos e recria documento, chunks, tags e modulos.
3. Remove do banco documentos que nao existem mais no diretorio da wiki.

### MCP Server / API REST

O servidor expoe MCP stateless e endpoints REST. Para ChatGPT Actions, use os endpoints REST.

| Endpoint | Metodo | Header | Uso |
|---|---:|---|---|
| `/api/knowledge/search` | POST | `X-API-Key` | Busca semantica na base |
| `/api/knowledge/document/{doc_id}` | GET | `X-API-Key` | Recupera documento completo |
| `/api/admin/sync` | POST | `X-API-Key` | Aciona reindexacao |
| `/sync` | POST | `X-API-Key` ou `X-Admin-Token` | Alias legado para compatibilidade |
| `/health` | GET | nenhum | Health check |
| `/mcp` | POST | `X-API-Key` | MCP JSON-RPC stateless |

## Modelo de dados

```cypher
(:Document {
  id,
  path,
  title,
  type,
  audience,
  status,
  content_hash,
  updated_at,
  raw_content
})

(:Chunk {
  id,
  heading,
  content,
  position,
  embedding
})

(:Tag {name})
(:Module {slug})

(:Document)-[:HAS_CHUNK]->(:Chunk)
(:Document)-[:HAS_TAG]->(:Tag)
(:Document)-[:BELONGS_TO_MODULE]->(:Module)
```

## Observacao sobre `graph_neighbors`

A tool `graph_neighbors` esta exposta no MCP, mas o indexador atual ainda nao cria nos `Entity` nem relacoes `RELATED_TO`. Portanto, ela tende a retornar vazio ate que a extracao de entidades seja implementada.

## Fluxo automatico

1. O analista edita um `.md` e faz commit/push.
2. O GitHub Actions executa `.github/workflows/sync.yml`.
3. O workflow chama `POST /api/admin/sync` com `X-API-Key`.
4. O MCP Server chama internamente o Indexer em `http://indexer:9000/trigger`.
5. O Indexer atualiza apenas arquivos alterados.
6. O ChatGPT passa a consultar o conteudo atualizado nas proximas chamadas.
