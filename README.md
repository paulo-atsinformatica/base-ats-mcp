# ERP KB - FalkorDB GraphRAG

Sistema de base de conhecimento para agentes de IA, utilizando a wiki Obsidian da ATS Informática integrada ao FalkorDB.

## Estrutura do Projeto

- `indexer/`: Serviço Python que lê os arquivos Markdown, gera embeddings e salva no FalkorDB.
- `mcp_server/`: Servidor que expõe ferramentas (tools) para agentes de IA via protocolo MCP.
- `wiki/`: (Volume montado) Contém os arquivos Markdown da wiki.

## Pré-requisitos

- Docker e Docker Compose
- Acesso à internet (para download inicial do modelo de embedding ~80MB)

## Como Iniciar (Local)

1. Configure o arquivo `.env`:
   ```bash
   cp .env.example .env
   # Edite as variáveis conforme necessário
   ```

2. Inicie os containers:
   ```bash
   docker-compose up -d
   ```

3. Verifique os logs do indexador:
   ```bash
   docker logs -f erp-kb-indexer
   ```

4. O servidor MCP estará disponível em `http://localhost:8000`.

## Ferramentas Disponíveis (MCP)

- `search_knowledge(query)`: Busca semântica nos chunks de texto.
- `get_document(doc_id)`: Retorna o conteúdo original completo de um arquivo.
- `graph_neighbors(entity_name, depth)`: Explora relações no grafo (Módulos, Tags, Entidades).

## Deploy no Coolify

1. Crie um novo **Service** no Coolify usando **Docker Compose**.
2. Cole o conteúdo do `docker-compose.yml`.
3. Configure as **Environment Variables** baseadas no `.env.example`.
4. O Coolify cuidará do build das imagens e exposição do serviço.
