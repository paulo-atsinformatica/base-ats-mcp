# Deploy no Coolify — ERP KB FalkorDB

## Pré-requisitos

- VPS com **Coolify** instalado
- Domínio ou IP apontado para a VPS
- Porta `8000` liberada no firewall (ou use o proxy reverso do Coolify)

---

## Passo 1 — Criar o Repositório GitHub

1. Crie um novo repositório no GitHub (ex: `ats-erp-kb`).
2. Copie o conteúdo de `erp-kb-falkordb/` para a raiz do repositório.
3. Crie a pasta `wiki/` na raiz e adicione seus arquivos Markdown.
4. Estrutura esperada:
   ```
   /
   ├── docker-compose.yml
   ├── .env.example
   ├── indexer/
   ├── mcp_server/
   ├── wiki/          ← arquivos .md da base de conhecimento
   └── .github/
       └── workflows/
           └── sync.yml
   ```

---

## Passo 2 — Configurar Secrets no GitHub

No repositório GitHub: **Settings → Secrets and variables → Actions**

| Secret | Valor |
|---|---|
| `MCP_SERVER_URL` | URL pública do seu MCP Server (ex: `https://erp-kb.seudominio.com.br`) |
| `ADMIN_TOKEN` | Mesmo valor definido no `.env` do Coolify |

---

## Passo 3 — Criar o Serviço no Coolify

1. Acesse o painel do Coolify.
2. Clique em **New Resource → Docker Compose**.
3. Aponte para o seu repositório GitHub.
4. Coolify vai detectar o `docker-compose.yml` automaticamente.

---

## Passo 4 — Configurar as Variáveis de Ambiente

No painel do serviço Coolify, vá em **Environment Variables** e adicione:

```env
GITHUB_REPO_URL=https://github.com/seu-usuario/seu-repo.git
GITHUB_TOKEN=seu_github_personal_access_token
MCP_PORT=8000
ADMIN_TOKEN=uma_senha_segura_e_longa
FALKORDB_HOST=falkordb
FALKORDB_PORT=6379
EMBEDDING_MODEL=all-MiniLM-L6-v2
OTEL_EXPORTER_OTLP_ENDPOINT=  # Deixe vazio se não tiver OTEL
```

---

## Passo 5 — Configurar Volume Persistente

Para que os dados do FalkorDB sobrevivam a reinicializações, o Coolify deve mapear o volume:

- **Volume name:** `falkordb_data`
- **Mount path:** `/data`
- **Service:** `falkordb`

> O Coolify cria volumes nomeados automaticamente ao ler o `docker-compose.yml`. Confirme na aba **Volumes** do serviço.

---

## Passo 6 — Deploy

1. Clique em **Deploy** no Coolify.
2. Acompanhe os logs de build em tempo real.
3. Após subir, verifique o health check:
   ```bash
   curl https://erp-kb.seudominio.com.br/health
   # Esperado: {"status": "ok", "database": true}
   ```

---

## Passo 7 — Primeira Indexação Manual

Após o deploy, acione a indexação inicial:

```bash
curl -X POST https://erp-kb.seudominio.com.br/sync \
  -H "X-Admin-Token: sua_senha_admin" \
  -H "Content-Type: application/json"
```

Acompanhe os logs do indexador no Coolify para confirmar que os arquivos estão sendo processados.

---

## Fluxo Automático (Após Configuração)

1. Você edita um `.md` na wiki e faz commit + push no GitHub.
2. O GitHub Actions detecta a mudança em `wiki/**/*.md`.
3. O workflow `sync.yml` faz `POST /sync` automaticamente.
4. O indexador re-processa apenas os arquivos alterados (verificação por hash).
5. O agente de IA já consulta o conteúdo atualizado na próxima chamada.

---

## Troubleshooting

| Problema | Solução |
|---|---|
| `FalkorDB não conecta` | Verifique se o service `falkordb` está healthy nos logs do Coolify |
| `Modelo de embedding não carrega` | Primeira inicialização baixa ~80MB; aguarde ou verifique acesso à internet |
| `POST /sync retorna 403` | Verifique se `ADMIN_TOKEN` bate entre o `.env` e o Secret do GitHub |
| `Arquivos não indexados` | Confirme que o `status` do frontmatter é `active` (não `draft`) |
