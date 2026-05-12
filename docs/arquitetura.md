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
- Armazena nos `Document`, `Chunk`, `Tag`, `Module` e `Entity`.
- Relacoes: `HAS_CHUNK`, `HAS_TAG`, `BELONGS_TO_MODULE`, `MENTIONS`, `IN_MODULE` e `HAS_TAG_ENTITY`.
- O embedding dos chunks usa `models/gemini-embedding-2`, com indice vetorial `cosine` de 3072 dimensoes.
- A busca vetorial usa a assinatura atual do FalkorDB:
  `db.idx.vector.queryNodes('Chunk', 'embedding', k, vecf32([...]))`.

### Indexer Service

| Modulo | Responsabilidade |
|---|---|
| `markdown_parser.py` | Le frontmatter e corpo do `.md` |
| `chunker.py` | Divide conteudo por headings H1/H2 |
| `embeddings.py` | Gera embeddings com Google Gemini |
| `entity_extractor.py` | Extrai entidades tecnicas de forma deterministica |
| `falkordb_repository.py` | Persiste documentos, chunks e relacionamentos no FalkorDB |
| `main.py` | Orquestra sync, `git pull`, hash de conteudo e remocao de deletados |

Logica de sincronizacao:

1. Faz `git pull` no repositorio da wiki.
2. Para cada `.md` em `WIKI_PATH`, exceto `index.md` e `log.md`:
   - Se `status: draft`, remove o documento antigo do grafo e ignora.
   - Calcula SHA-256 do conteudo.
   - Se o hash for igual ao armazenado, nao reindexa.
   - Se mudou, remove os chunks antigos e recria documento, chunks, tags e modulos.
3. Extrai entidades a partir de tags, modulos, titulo e padroes tecnicos.
4. Remove do banco documentos que nao existem mais no diretorio da wiki.

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
(:Entity {name, display_name, type})

(:Document)-[:HAS_CHUNK]->(:Chunk)
(:Document)-[:HAS_TAG]->(:Tag)
(:Document)-[:BELONGS_TO_MODULE]->(:Module)
(:Document)-[:MENTIONS]->(:Entity)
(:Entity)-[:IN_MODULE]->(:Module)
(:Entity)-[:HAS_TAG_ENTITY]->(:Tag)
```

## Entidades e `graph_neighbors`

O indexador cria entidades deterministicas sem LLM. As fontes sao:

- `tags` e `modulos` do frontmatter.
- Titulo do documento.
- Termos conhecidos, como `Backup Now`, `Firebird`, `SPED`, `NFe`, `NFC-e`, `Monitor API`.
- Padroes tecnicos, como `.dll`, `.fdb`, `.xml`, `Rejeicao 539`, `Vendor Error 99` e objetos em caixa alta.

A tool `graph_neighbors` consulta esses nos `Entity` e retorna documentos, tags, modulos e entidades relacionadas. Entidades que aparecem no mesmo documento podem ser descobertas com profundidade 2 pelo caminho `Entity <- MENTIONS - Document - MENTIONS -> Entity`.

## Fluxo automatico

1. O analista edita um `.md` e faz commit/push.
2. O GitHub Actions executa `.github/workflows/sync.yml`.
3. O workflow chama `POST /api/admin/sync` com `X-API-Key`.
4. O MCP Server chama internamente o Indexer em `http://indexer:9000/trigger`.
5. O Indexer atualiza apenas arquivos alterados.
6. O ChatGPT passa a consultar o conteudo atualizado nas proximas chamadas.
