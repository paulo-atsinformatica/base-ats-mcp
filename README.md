# ERP KB FalkorDB GraphRAG

Base de conhecimento em grafo para a ATS Informatica, usando FalkorDB e embeddings do Google Gemini.

## Componentes

- **Indexer:** processa Markdown, gera embeddings com `models/gemini-embedding-2` e popula o FalkorDB.
- **MCP Server/API:** expoe MCP stateless e endpoints REST para ChatGPT Actions.
- **FalkorDB:** armazena documentos, chunks, tags, modulos e indice vetorial.

## Endpoints principais

| Endpoint | Uso |
|---|---|
| `POST /api/knowledge/search` | Busca semantica |
| `GET /api/knowledge/document/{doc_id}` | Documento completo |
| `POST /api/admin/sync` | Reindexacao administrativa |
| `GET /health` | Health check |

Todos os endpoints protegidos usam `X-API-Key` com o valor de `ADMIN_TOKEN`.
O endpoint legado `POST /sync` tambem aceita `X-Admin-Token` para compatibilidade.

Tambem e possivel configurar `PUBLIC_TOKEN` para agentes sem acesso a documentos `audience: analyst`. O `ADMIN_TOKEN` tem escopo completo; o `PUBLIC_TOKEN` enxerga apenas documentos nao restritos.

## Deploy

As imagens Docker sao geradas no GHCR pelo GitHub Actions. Para producao:

1. Configure as variaveis no servidor, incluindo `GOOGLE_API_KEY`, `ADMIN_TOKEN` e `EMBEDDING_MODEL=models/gemini-embedding-2`.
2. Suba a stack:

```bash
docker compose up -d
```

3. Acione a primeira indexacao:

```bash
curl -X POST https://seu-servidor/api/admin/sync \
  -H "X-API-Key: seu_admin_token"
```

Veja detalhes em `docs/deploy-coolify.md` e `docs/instrucoes_custom_gpt.md`.
