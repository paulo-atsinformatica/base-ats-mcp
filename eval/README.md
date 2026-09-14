# Harness de avaliação de recuperação

Mede, com número, se uma mudança no indexador melhora ou piora a busca da base
de conhecimento. Sem isso, qualquer ajuste de chunking, embedding ou busca
híbrida é chute.

## Por que existe

A base tem 5.360 páginas em `wiki/`, e o agente de suporte só é tão bom quanto
o trecho que ele recupera. As decisões em aberto hoje — chunk por H2 ou
documento inteiro, embeddar com ou sem contexto, acrescentar busca lexical,
truncar o vetor para 768 dimensões — só podem ser resolvidas comparando
recall@k entre configurações. Este harness produz esse número.

## Arquivos

| Arquivo | O que faz |
|---|---|
| `common.py` | Carrega o corpus, replica o chunking da produção, BM25 local sem dependência externa |
| `build_goldenset.py` | Deriva o golden set do próprio corpus (uma consulta → um documento alvo) |
| `paraphrase_goldenset.py` | Reescreve as consultas como um usuário real as faria (Gemini) |
| `run_eval.py` | Roda o golden set contra um backend e imprime/salva as métricas |
| `goldenset.jsonl` | Consultas literais (extraídas do documento) |
| `goldenset_paraphrased.jsonl` | Consultas parafraseadas — **é este que vale para decidir** |
| `reports/` | Um JSON por execução, para comparar antes/depois |

## Uso

```bash
cd eval

# 1. gerar o golden set (determinístico, sem rede)
python build_goldenset.py --corpus E:/Projetos/obsidian/wiki --per-track 200

# 2. parafrasear (usa GOOGLE_API_KEY do ../.env; retoma de onde parou)
python paraphrase_goldenset.py

# 3. medir as configurações locais de indexação
python run_eval.py --backend all --goldenset goldenset_paraphrased.jsonl

# 4. medir o sistema real implantado
python run_eval.py --backend api --goldenset goldenset_paraphrased.jsonl \
  --api-url https://mcp.base.atsinformatica.com.br --api-token "$ADMIN_TOKEN" \
  --limit-queries 200

# 5. conferir vazamento de audience=analyst para token público
python run_eval.py --backend api --scope public --api-token "$PUBLIC_TOKEN" ...
```

## As trilhas do golden set

Cada trilha imita um jeito real de perguntar, e cada uma tem um viés diferente
de vazamento lexical — por isso os números são reportados separados, nunca só
o total.

| Trilha | Origem | Realismo |
|---|---|---|
| `erro_literal` | mensagem de erro em negrito nas páginas de `erros/` | **Alta.** O analista cola a mensagem exata: a consulta literal É a consulta real. Único número absoluto confiável |
| `fewshot_pergunta` | `## Pergunta` das 1.004 páginas de `few-shot/` | Perguntas reais de ticket. Parafraseadas, viram o melhor proxy de cliente final |
| `sintoma` | `## Problema` de `troubleshooting/` | Descrição do sintoma |
| `sintoma_hard` | idem, sem os termos do título do alvo | Remove o atalho lexical |
| `rotina_objetivo` | `## Visão Geral` de `rotinas/`, `procedimentos/`, `faq/` | Intenção ("quero fazer X") |
| `rotina_objetivo_hard` | idem, sem os termos do título | A mais difícil |

## Limitações — ler antes de citar qualquer número

1. **Um alvo por consulta.** Se o retriever trouxer uma página equivalente em
   vez da marcada, conta como erro — o recall real é um piso. O efeito é
   pequeno: só 2,2% das consultas têm alvo com outra página de título ≥ 80%
   semelhante (medido sobre `goldenset.jsonl`).
2. **Consultas literais saturam.** No `goldenset.jsonl` sem paráfrase, BM25
   marca R@5 ≈ 0,99 em todas as trilhas exceto `erro_literal` — a consulta é um
   trecho do alvo. Esse arquivo serve para detectar regressão grosseira, não
   para comparar configurações. **Use o parafraseado.**
3. **Os backends BM25 não simulam o retriever denso.** Eles medem o formato da
   unidade indexada (chunk vs documento, com vs sem contexto), que afeta os dois
   tipos de busca, e servem de piso de referência. Para o número do sistema real
   existe o backend `api`.
4. **As paráfrases são geradas por LLM.** São realistas, mas não são tickets
   reais. A trilha `fewshot_pergunta` é a que mais se aproxima disso, porque a
   pergunta de origem veio mesmo de atendimento.
5. **Páginas `status: draft` são excluídas** dos dois lados (índice e alvos),
   porque o indexer não as indexa.

## Ligação com o indexador

`common.chunk_by_headings` e `common.context_header` são cópias fiéis de
`indexer/src/chunker.py`. Se o chunker da produção mudar, estas cópias têm de
mudar junto — senão o harness passa a medir outra coisa.

O preâmbulo de contexto que os backends `*-ctx` avaliam **já está aplicado na
produção** (`chunker.embedding_text`, desde `INDEX_SCHEMA_VERSION = context-v2`).
Os backends `bm25-chunk` e `bm25-doc`, sem preâmbulo, ficam como referência do
que havia antes.
