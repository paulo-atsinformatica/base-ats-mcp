# ERP KB FalkorDB GraphRAG

Este projeto implementa uma base de conhecimento em grafo (GraphRAG) para a ATS Informática, integrando o FalkorDB com embeddings do Google Gemini.

## Arquitetura
- **Indexer:** Processa a wiki em Markdown, gera embeddings e popula o FalkorDB.
- **MCP Server:** Interface Stateless HTTP (JSON-RPC) e REST para consulta à base.
- **FalkorDB:** Banco de dados de grafos com suporte a busca vetorial.

## CI/CD (GitHub Actions)
O projeto está configurado para gerar imagens Docker automaticamente no **GHCR.io** a cada push.

### Como subir para o GitHub:
1. Crie um repositório vazio no GitHub chamado `erp-kb-falkordb`.
2. Execute os comandos abaixo no seu terminal:
   ```bash
   git remote add origin https://github.com/paulo-atsinformatica/erp-kb-falkordb.git
   git branch -M main
   git push -u origin main
   ```

### Como rodar em Produção:
Após o GitHub Actions completar o build das imagens:
1. Copie o `docker-compose.yml` e o seu `.env` para o servidor.
2. Execute:
   ```bash
   docker compose up -d
   ```

## Segurança
A API está protegida via header `X-API-Key`. Certifique-se de configurar o `ADMIN_TOKEN` no seu arquivo `.env`.
