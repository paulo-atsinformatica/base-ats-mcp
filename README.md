# ERP KB FalkorDB GraphRAG

Base de conhecimento em grafo para a ATS Informatica, usando FalkorDB e embeddings do Google Gemini.

## Componentes

- **Indexer:** processa Markdown, gera embeddings com `models/gemini-embedding-2` e popula o FalkorDB.
- **MCP Server/API:** expoe MCP stateless e endpoints REST para ChatGPT Actions.
- **FalkorDB:** armazena documentos, chunks, tags, modulos, indice vetorial e indice full-text.

## Endpoints principais

| Endpoint | Uso |
|---|---|
| `POST /api/knowledge/search` | Busca hibrida (vetorial + lexical, fundidas por RRF) |
| `GET /api/knowledge/document/{doc_id}` | Documento completo |
| `POST /api/admin/sync` | Reindexacao administrativa |
| `GET /health` | Health check |

## Manter o conhecimento atualizado

A fonte da verdade e a wiki no GitHub. Corrigir ou acrescentar conhecimento e
sempre: editar o `.md` -> commit/push -> acionar o sync.

```bash
# incremental (padrao): processa so o que mudou desde o ultimo commit indexado
curl -X POST https://seu-servidor/api/admin/sync -H "X-API-Key: $ADMIN_TOKEN"

# uma pagina so, para corrigir sem esperar ciclo inteiro
curl -X POST "https://seu-servidor/api/admin/sync?path=rotinas/fechamento-de-caixa.md" \
  -H "X-API-Key: $ADMIN_TOKEN"

# varredura completa (apos mudar o formato de indexacao)
curl -X POST "https://seu-servidor/api/admin/sync?force=true" -H "X-API-Key: $ADMIN_TOKEN"
```

O indexador guarda no grafo o ultimo commit indexado (no `:Meta`) e usa
`git diff --name-status` para decidir o que reprocessar; cai sozinho para
varredura completa quando esse ponteiro nao serve (primeira execucao,
force-push, ou mudanca de `INDEX_SCHEMA_VERSION`).

`INDEX_SCHEMA_VERSION`, em `indexer/src/main.py`, entra no hash de cada
documento: **mudar essa string obriga a base inteira a ser reindexada**. E o
que se faz ao alterar chunking, preambulo de contexto ou modelo de embedding.

## Qualidade da busca

`eval/` tem o harness que mede recall@k de cada configuracao de indexacao
contra um golden set de 1.200 consultas derivadas da propria base. Toda
mudanca em chunking, embedding ou busca deve ser medida ali antes e depois —
ver `eval/README.md`.

## Testes

```bash
python tests/test_incremental_sync.py   # selecao de arquivos por git diff
docker run -d --name erp-kb-fts-test -p 16379:6379 falkordb/falkordb:latest
python tests/test_hybrid_search.py      # Cypher real + filtro de audience + RRF
docker rm -f erp-kb-fts-test
```

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
