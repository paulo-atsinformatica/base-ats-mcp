# Deploy no Coolify - ERP KB FalkorDB

## Pre-requisitos

- VPS com Coolify instalado.
- Dominio ou URL publica apontando para o servico MCP.
- Variaveis de ambiente configuradas no Coolify.
- Chave Google AI Studio em `GOOGLE_API_KEY`.

## Variaveis de ambiente

Configure no Coolify:

```env
GITHUB_REPO_URL=https://github.com/seu-usuario/seu-repo.git
GITHUB_TOKEN=seu_github_personal_access_token

MCP_PORT=8000
ADMIN_TOKEN=uma_senha_segura_e_longa
PUBLIC_TOKEN=uma_senha_publica_sem_acesso_analyst

GOOGLE_API_KEY=sua_chave_google_ai_studio
EMBEDDING_MODEL=models/gemini-embedding-2

FALKORDB_HOST=falkordb
FALKORDB_PORT=6379

OTEL_EXPORTER_OTLP_ENDPOINT=
```

## Deploy

1. Crie um recurso Docker Compose no Coolify apontando para este repositorio.
2. Confirme que o volume nomeado `falkordb_data` esta persistente em `/data`.
3. Faca deploy.
4. Verifique o health check:

```bash
curl https://erp-kb.seudominio.com.br/health
```

Resposta esperada:

```json
{"status":"ok","database":true}
```

## Primeira indexacao manual

Use o endpoint atual:

```bash
curl -X POST https://erp-kb.seudominio.com.br/api/admin/sync \
  -H "X-API-Key: sua_senha_admin" \
  -H "Content-Type: application/json"
```

O alias legado tambem e aceito para compatibilidade:

```bash
curl -X POST https://erp-kb.seudominio.com.br/sync \
  -H "X-Admin-Token: sua_senha_admin" \
  -H "Content-Type: application/json"
```

## GitHub Actions

Configure os secrets:

| Secret | Valor |
|---|---|
| `MCP_SERVER_URL` | URL publica do MCP Server, sem barra final |
| `ADMIN_TOKEN` | Mesmo valor de `ADMIN_TOKEN` do Coolify |

O workflow `.github/workflows/sync.yml` chama:

```text
POST {MCP_SERVER_URL}/api/admin/sync
Header: X-API-Key: {ADMIN_TOKEN}
```

## ChatGPT Actions

Para o GPT customizado, use apenas os endpoints de conhecimento:

- `POST /api/knowledge/search`
- `GET /api/knowledge/document/{doc_id}`

Nao exponha `/api/admin/sync` no schema do GPT, porque ele serve para administracao e reindexacao.

## Troubleshooting

| Problema | Causa provavel | Solucao |
|---|---|---|
| `Invalid arguments for procedure db.idx.vector.queryNodes` | Chamada antiga da procedure vetorial | Atualize a imagem com este codigo; a busca agora usa `queryNodes('Chunk', 'embedding', k, vecf32(vector))` |
| Busca cai em fallback | Indice vetorial ausente, dados antigos sem `vecf32`, ou versao FalkorDB incompativel | Refaça o deploy e acione `/api/admin/sync` para recriar chunks com `vecf32`; o fallback ainda calcula similaridade semantica por cosseno, mas e mais lento |
| `POST /api/admin/sync` retorna 403 | Token incorreto, header errado ou uso de `PUBLIC_TOKEN` | Use `X-API-Key` com o valor de `ADMIN_TOKEN`; `PUBLIC_TOKEN` nao pode sincronizar |
| `GOOGLE_API_KEY must be set` | Chave Gemini ausente no servico | Configure `GOOGLE_API_KEY` no indexer e no MCP server |
| Health `degraded` | MCP nao conseguiu pingar FalkorDB | Verifique se o servico `falkordb` esta healthy no Docker/Coolify |
