# Manual Tecnico - Integracao de Agentes com ERP KB GraphRAG

Este manual explica como conectar agentes de IA a base de conhecimento ERP KB GraphRAG usando OpenAPI ou MCP, como a arquitetura funciona e como os dados sao estruturados no FalkorDB.

## 1. Objetivo do projeto

O ERP KB GraphRAG e uma base de conhecimento para suporte tecnico da ATS Informatica. Ele transforma documentos Markdown da wiki em uma base consultavel por agentes de IA.

O sistema serve para:

- Buscar solucoes tecnicas por significado, nao apenas por palavra exata.
- Recuperar documentos completos por ID.
- Manter uma base versionada em Markdown.
- Atualizar a base automaticamente apos alteracoes na wiki.
- Expor ferramentas seguras para GPTs, agentes e sistemas externos.

## 2. Visao geral da arquitetura

```text
Wiki Markdown no GitHub
        |
        v
Indexer Service
        |
        v
FalkorDB Graph + Vector Index
        |
        v
MCP Server / REST API
        |
        v
ChatGPT Actions, agentes MCP ou sistemas externos
```

Componentes:

- `indexer`: le arquivos `.md`, extrai metadados, divide conteudo em chunks, gera embeddings Gemini e grava no FalkorDB.
- `falkordb`: banco de grafo que armazena documentos, chunks, tags, modulos e vetores.
- `mcp_server`: expoe endpoints REST/OpenAPI e MCP JSON-RPC para agentes.
- `GitHub Actions`: gera imagens Docker e pode acionar sincronizacao da wiki.

## 3. Formas de integracao

Existem duas formas principais de conectar agentes.

### 3.1 OpenAPI

Use OpenAPI quando o consumidor for:

- GPT customizado do ChatGPT com Actions.
- Ferramentas que importam schema OpenAPI.
- Automacoes REST simples.
- Scripts internos.

Endpoint publico do schema:

```text
https://mcp.base.atsinformatica.com.br/openapi.json
```

Esse schema e somente leitura e expoe apenas:

```text
POST /api/knowledge/search
GET  /api/knowledge/document/{doc_id}
```

Autenticacao:

```text
Header: X-API-Key: <ADMIN_TOKEN>
```

Escopos por token:

| Token | Escopo | Acesso |
|---|---|---|
| `ADMIN_TOKEN` | `full` | Acessa todos os documentos, incluindo `audience: analyst` |
| `PUBLIC_TOKEN` | `non_analyst` | Acessa somente documentos que nao sejam `audience: analyst` |

Nao inclua endpoints administrativos no GPT, como:

```text
/api/admin/sync
/sync
/mcp
```

### 3.2 MCP

Use MCP quando o consumidor for um agente que entende chamadas de ferramenta no padrao MCP ou uma ponte que fale JSON-RPC sobre HTTP.

Endpoint:

```text
POST /mcp
```

Autenticacao:

```text
Header: X-API-Key: <ADMIN_TOKEN>
```

Ferramentas MCP expostas:

| Tool | Uso |
|---|---|
| `search_knowledge` | Busca semantica por pergunta ou termo tecnico |
| `get_document` | Recupera documento completo pelo `doc_id` |
| `graph_neighbors` | Explora relacoes entre entidades, documentos, tags e modulos |

Observacao: o indexador cria entidades deterministicas a partir de tags, modulos, titulos e padroes tecnicos. Para respostas de suporte, a integracao principal continua sendo `search_knowledge` e `get_document`; `graph_neighbors` serve para exploracao do grafo.

## 4. Integracao via OpenAPI

### 4.1 Configurando no ChatGPT Actions

No GPT Builder:

1. Abra **Configure**.
2. Em **Actions**, clique em **Create new action**.
3. Em **Authentication**, configure:
   - Authentication Type: `API Key`
   - Auth Type: `Custom`
   - Custom Header Name: `X-API-Key`
   - API Key: valor de `ADMIN_TOKEN`
4. Em **Schema**, importe:

```text
https://mcp.base.atsinformatica.com.br/openapi.json
```

O GPT deve passar a enxergar duas operacoes:

- `searchKnowledge`
- `getKnowledgeDocument`

Para GPTs diferentes, use o mesmo OpenAPI e troque apenas a API Key:

- GPT interno/analista: `ADMIN_TOKEN`.
- GPT publico/cliente: `PUBLIC_TOKEN`.

### 4.2 Exemplo de busca REST

```bash
curl -X POST "https://mcp.base.atsinformatica.com.br/api/knowledge/search" \
  -H "X-API-Key: SEU_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"Backup Now unable to load dbxfb.dll","limit":3}'
```

Resposta esperada:

```json
{
  "result": "Doc ID: PROC-backup-now-identificar-alterar-caminho-bd\nTitle: ...\n..."
}
```

### 4.3 Exemplo de recuperacao de documento

```bash
curl -X GET "https://mcp.base.atsinformatica.com.br/api/knowledge/document/PROC-backup-now-identificar-alterar-caminho-bd" \
  -H "X-API-Key: SEU_TOKEN"
```

Resposta esperada:

```json
{
  "result": "Title: Identificar e Alterar Caminho do Banco no Backup Now\nType: procedimento\nPath: ...\n\n---\n..."
}
```

### 4.4 Padrao recomendado para agentes OpenAPI

Fluxo recomendado:

1. Receber pergunta do usuario.
2. Chamar `searchKnowledge` com a pergunta completa.
3. Avaliar os `Doc ID` retornados.
4. Se precisar de mais contexto, chamar `getKnowledgeDocument` com o melhor `doc_id`.
5. Responder ao usuario citando o documento usado.

Regra importante: nao responder troubleshooting tecnico apenas com memoria local. Sempre consultar a base.

## 5. Integracao via MCP JSON-RPC

### 5.1 Listar tools

```bash
curl -X POST "https://mcp.base.atsinformatica.com.br/mcp" \
  -H "X-API-Key: SEU_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
  }'
```

### 5.2 Chamar busca semantica

```bash
curl -X POST "https://mcp.base.atsinformatica.com.br/mcp" \
  -H "X-API-Key: SEU_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "search_knowledge",
      "arguments": {
        "query": "erro ao fechar caixa valores ausentes",
        "limit": 3
      }
    }
  }'
```

### 5.3 Chamar recuperacao de documento

```bash
curl -X POST "https://mcp.base.atsinformatica.com.br/mcp" \
  -H "X-API-Key: SEU_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "get_document",
      "arguments": {
        "doc_id": "TS-windows-caixa-fechamento-valores-ausentes"
      }
    }
  }'
```

## 6. Como a base e indexada

O indexador processa arquivos Markdown da wiki.

Fluxo:

1. Faz `git pull` do repositorio configurado em `GITHUB_REPO_URL`.
2. Percorre arquivos `.md` dentro de `WIKI_PATH`.
3. Ignora `index.md` e `log.md`.
4. Le frontmatter YAML e corpo do documento.
5. Se `status: draft`, remove o documento antigo do banco e nao indexa.
6. Calcula SHA-256 do conteudo completo.
7. Se o hash nao mudou, pula o arquivo.
8. Divide o conteudo em chunks por headings `#` e `##`.
9. Gera embeddings com `models/gemini-embedding-2`.
10. Extrai entidades tecnicas de forma deterministica.
11. Grava documento, chunks, tags, modulos, entidades e relacoes no FalkorDB.
12. Remove do banco documentos que foram apagados da wiki.

## 7. Estrutura esperada dos documentos Markdown

Exemplo:

```markdown
---
title: "Identificar e Alterar Caminho do Banco no Backup Now"
id: PROC-backup-now-identificar-alterar-caminho-bd
type: procedimento
audience: analyst
modulos: ["windows/backup"]
tags: ["backup", "backup now", "registro", "banco de dados"]
data_criacao: 2026-05-07
data_atualizacao: 2026-05-07
status: active
---

# Identificar e Alterar Caminho do Banco no Backup Now

Texto introdutorio.

## Situacao

Descricao do problema.

## Passo a Passo

1. Primeiro passo.
2. Segundo passo.
```

Campos importantes:

| Campo | Uso |
|---|---|
| `id` | Identificador unico usado em `get_document` |
| `title` | Titulo retornado nas buscas |
| `type` | Tipo do conteudo, como `procedimento`, `troubleshooting`, `referencia` |
| `audience` | Publico-alvo, como `client`, `analyst` ou `internal` |
| `modulos` | Modulos relacionados |
| `tags` | Palavras-chave auxiliares |
| `status` | `active` para indexar, `draft` para ignorar |
| `data_atualizacao` | Data informativa para manutencao |

## 8. Estrutura do banco FalkorDB

O FalkorDB armazena a base em formato de grafo. Isso permite representar documentos, partes do documento e classificacoes como nos conectados por relacoes.

### 8.1 Nos principais

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
```

Representa o documento Markdown completo.

```cypher
(:Chunk {
  id,
  heading,
  content,
  position,
  embedding
})
```

Representa uma parte pesquisavel do documento. Cada chunk tem um vetor de embedding.

```cypher
(:Tag {name})
(:Module {slug})
(:Entity {name, display_name, type})
```

Representam classificacoes auxiliares.

`Entity` representa conceitos tecnicos extraidos do documento, como produto, modulo, DLL, arquivo de banco, rejeicao fiscal, objeto de banco ou termo recorrente.

### 8.2 Relacoes

```cypher
(:Document)-[:HAS_CHUNK]->(:Chunk)
(:Document)-[:HAS_TAG]->(:Tag)
(:Document)-[:BELONGS_TO_MODULE]->(:Module)
(:Document)-[:MENTIONS]->(:Entity)
(:Entity)-[:IN_MODULE]->(:Module)
(:Entity)-[:HAS_TAG_ENTITY]->(:Tag)
```

Uso das relacoes:

- `HAS_CHUNK`: liga o documento aos trechos indexados.
- `HAS_TAG`: permite agrupar documentos por tags.
- `BELONGS_TO_MODULE`: permite agrupar documentos por modulo.
- `MENTIONS`: liga documentos aos conceitos tecnicos extraidos.
- `IN_MODULE`: liga entidades de modulo ao no `Module`.
- `HAS_TAG_ENTITY`: liga entidades de tag ao no `Tag`.

Entidades relacionadas podem ser descobertas em profundidade 2 pelo caminho:

```cypher
(:Entity)<-[:MENTIONS]-(:Document)-[:MENTIONS]->(:Entity)
```

### 8.3 Extracao de entidades

A extracao inicial nao usa LLM. Ela e deterministica para manter o indexador previsivel.

Fontes usadas:

- `tags` do frontmatter.
- `modulos` do frontmatter.
- `title` do documento.
- Termos conhecidos, como `Backup Now`, `Firebird`, `SPED`, `NFe`, `NFC-e`, `Monitor API`.
- Padroes regex, como `.dll`, `.fdb`, `.xml`, `Rejeicao 539`, `Vendor Error 99` e nomes em caixa alta.

Exemplos de entidades:

```cypher
(:Entity {name: "backup now", type: "product"})
(:Entity {name: "dbxfb.dll", type: "dll"})
(:Entity {name: "empresa.fdb", type: "database_file"})
(:Entity {name: "rejeicao 539", type: "sefaz_rejection"})
(:Entity {name: "windows/backup", type: "module"})
```

### 8.4 Indice vetorial

Os embeddings sao gravados em `Chunk.embedding`.

Configuracao atual:

```text
Modelo: models/gemini-embedding-2
Dimensoes: 3072
Similaridade: cosine
Formato: vecf32([...])
```

Busca vetorial usada pelo MCP Server:

```cypher
CALL db.idx.vector.queryNodes('Chunk', 'embedding', $limit, vecf32([...]))
YIELD node, score
MATCH (node)<-[:HAS_CHUNK]-(d:Document)
RETURN d.id, d.title, d.path, node.heading, node.content, score
```

## 9. Como a busca funciona

Quando o agente chama `searchKnowledge`:

1. O MCP Server recebe a pergunta.
2. Gera embedding da pergunta com Gemini.
3. Consulta o indice vetorial dos chunks no FalkorDB.
4. Recupera os chunks mais semelhantes.
5. Retorna texto com:
   - `Doc ID`
   - `Title`
   - `Path`
   - `Heading`
   - `Content`
   - `Score`

O agente deve usar `Doc ID` para buscar o documento completo quando a resposta exigir mais contexto.

## 10. Administracao e sincronizacao

Endpoints administrativos nao devem ser expostos a GPTs de atendimento.

Endpoint de sync:

```text
POST /api/admin/sync
Header: X-API-Key: <ADMIN_TOKEN>
```

Esse endpoint aciona internamente:

```text
http://indexer:9000/trigger
```

Use apenas em automacoes controladas, GitHub Actions, operadores ou painel administrativo.

## 11. Seguranca

Regras recomendadas:

- Nunca exponha `ADMIN_TOKEN` em documentos, exemplos publicos ou prints.
- Use `PUBLIC_TOKEN` para agentes que nao podem ver documentos `audience: analyst`.
- Trate documentos sem `audience` como restritos no servidor.
- Em GPT Actions, exponha apenas rotas de leitura.
- Use `X-API-Key` como header customizado.
- Nao exponha FalkorDB diretamente para a internet.
- Mantenha FalkorDB apenas na rede interna Docker.
- Restrinja `/api/admin/sync` a automacoes confiaveis.
- Use tokens diferentes por ambiente, se possivel.

## 12. Troubleshooting de integracao

### 12.1 GPT nao chama a ferramenta

Causas comuns:

- Arquivo anexado contem resposta direta e o GPT decide responder localmente.
- Instructions nao exigem chamada obrigatoria da Action.
- Usuario fez pergunta generica demais.

Correcao:

- Instrua que toda pergunta tecnica concreta deve chamar `searchKnowledge`.
- Use arquivos anexados apenas como contexto estrutural.
- Remova anexos que contenham solucoes finais.

### 12.2 GPT retorna 403

Causas comuns:

- Header configurado errado.
- API key com espacos ou aspas.
- Schema antigo declarando `X-Admin-Token`.

Correcao:

- Authentication Type: `API Key`.
- Auth Type: `Custom`.
- Custom Header Name: `X-API-Key`.
- API Key: valor exato de `ADMIN_TOKEN`.

### 12.3 OpenAPI importado mostra rotas admin

Isso indica deploy antigo. O `/openapi.json` correto deve conter apenas:

```text
/api/knowledge/search
/api/knowledge/document/{doc_id}
```

Se aparecer `/api/admin/sync`, `/sync` ou `/mcp`, faca redeploy da imagem atual.

### 12.4 Busca vetorial cai em fallback

Causa comum:

- Dados antigos sem `vecf32`.
- Indice vetorial ausente.
- Versao antiga da imagem.

Correcao:

1. Redeploy da imagem atual.
2. Executar `POST /api/admin/sync`.
3. Confirmar logs sem erro `Invalid arguments for procedure db.idx.vector.queryNodes`.

## 13. Checklist de validacao

Use estes testes apos deploy.

Health:

```bash
curl "https://mcp.base.atsinformatica.com.br/health"
```

OpenAPI:

```bash
curl "https://mcp.base.atsinformatica.com.br/openapi.json"
```

Busca:

```bash
curl -X POST "https://mcp.base.atsinformatica.com.br/api/knowledge/search" \
  -H "X-API-Key: SEU_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"fechamento de caixa","limit":3}'
```

Documento:

```bash
curl -X GET "https://mcp.base.atsinformatica.com.br/api/knowledge/document/DOC_ID" \
  -H "X-API-Key: SEU_TOKEN"
```

## 14. Boas praticas para agentes

- Sempre pesquisar antes de responder incidentes.
- Usar a pergunta original do usuario como query inicial.
- Fazer segunda busca com termos tecnicos se o primeiro resultado for fraco.
- Recuperar documento completo quando houver risco operacional.
- Citar `Doc ID` ou titulo na resposta.
- Alertar quando o procedimento for `audience: analyst`.
- Nao inventar tabelas, scripts ou comandos que nao estejam validados na base.
