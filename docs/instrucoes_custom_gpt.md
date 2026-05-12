# Custom GPT - Configuracao das Actions

Este documento contem o prompt recomendado e o schema OpenAPI para conectar um GPT customizado do ChatGPT a base GraphRAG do ERP KB.

Referencia OpenAI: GPT Actions usam duas partes principais, autenticacao e um schema OpenAPI que descreve os endpoints disponiveis. Para API Key, o ChatGPT permite header customizado.

## 1. Instructions do GPT

Cole no campo **Instructions** do GPT:

```text
Voce e a Tina Teles, Analista de Suporte Tecnico Senior da ATS Informatica.
Seu objetivo e ajudar analistas de suporte e clientes a resolverem problemas operacionais, fiscais e de infraestrutura relacionados ao ERP Resulth e seus modulos, como NFC-e, NF-e, Monitor API e Backup Now.

Regras:
1. Responda sempre em Portugues do Brasil.
2. Seja claro, objetivo e use passos praticos.
3. Quando o usuario relatar erro, rejeicao fiscal, problema operacional ou duvida tecnica do ERP, use obrigatoriamente a Action da Base de Conhecimento antes de responder.
4. Quando a busca retornar um Doc ID relevante e a resposta exigir detalhes, use a Action de documento completo.
5. Ao usar informacao da base, cite o titulo ou Doc ID encontrado e reformule a solucao em linguagem amigavel.
6. Se a base nao trouxer solucao, diga isso de forma transparente e sugira troubleshooting basico ou abertura de ticket com o cenario detalhado.
7. Procedimentos com banco Firebird, registro do Windows, certificados, servidor ou manipulacao de arquivos devem conter alerta de cautela tecnica.
```

## 2. Action da Base de Conhecimento GraphRAG

No editor do GPT:

1. Abra **Configure**.
2. Em **Actions**, clique em **Create new action**.
3. Em **Authentication**, selecione:
   - **Authentication Type:** API Key
   - **Auth Type:** Custom
   - **Custom Header Name:** `X-API-Key`
   - **API Key:** mesmo valor de `ADMIN_TOKEN` configurado no servidor
4. Em **Schema**, cole o JSON abaixo.

Troque a URL em `servers[0].url` pela URL publica real do seu MCP Server.

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "ERP KB GraphRAG API",
    "version": "1.0.0",
    "description": "API para consultar a base de conhecimento GraphRAG da ATS Informatica."
  },
  "servers": [
    {
      "url": "https://mcp-base.163.176.255.228.sslip.io"
    }
  ],
  "paths": {
    "/api/knowledge/search": {
      "post": {
        "operationId": "searchKnowledge",
        "summary": "Busca na base de conhecimento",
        "description": "Busca semantica por trechos relevantes na base de conhecimento.",
        "security": [
          {
            "ApiKeyAuth": []
          }
        ],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/SearchRequest"
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Resultado da busca",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/TextResult"
                }
              }
            }
          }
        }
      }
    },
    "/api/knowledge/document/{doc_id}": {
      "get": {
        "operationId": "getKnowledgeDocument",
        "summary": "Recupera documento completo",
        "description": "Retorna o conteudo integral de um documento pelo Doc ID.",
        "security": [
          {
            "ApiKeyAuth": []
          }
        ],
        "parameters": [
          {
            "name": "doc_id",
            "in": "path",
            "required": true,
            "description": "Doc ID retornado pela busca.",
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Documento completo",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/TextResult"
                }
              }
            }
          }
        }
      }
    }
  },
  "components": {
    "schemas": {
      "SearchRequest": {
        "type": "object",
        "required": [
          "query"
        ],
        "properties": {
          "query": {
            "type": "string",
            "description": "Pergunta, erro ou termo tecnico a pesquisar."
          },
          "limit": {
            "type": "integer",
            "description": "Quantidade maxima de trechos.",
            "default": 3,
            "minimum": 1,
            "maximum": 10
          }
        }
      },
      "TextResult": {
        "type": "object",
        "properties": {
          "result": {
            "type": "string"
          }
        }
      }
    },
    "securitySchemes": {
      "ApiKeyAuth": {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key"
      }
    }
  }
}
```

## 3. Testes no Preview do GPT

Use exemplos como:

- `Como resolvo erro de Access Violation no Monitor API?`
- `Procure na base uma solucao para rejeicao de NF-e por duplicidade.`
- `Busque fechamento de caixa e abra o documento mais relevante.`

O ChatGPT deve pedir permissao para chamar o dominio configurado no schema. Autorize e confira se a Action `searchKnowledge` retorna trechos com `Doc ID`.

## 4. Observacoes de seguranca

- Nao inclua `/api/admin/sync` no schema do GPT.
- Use uma API key longa e diferente de outras senhas.
- Se trocar `ADMIN_TOKEN` no servidor, atualize a API Key da Action.
