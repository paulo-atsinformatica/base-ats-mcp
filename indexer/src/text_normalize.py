"""Normalizacao de texto para a busca lexical (full-text do FalkorDB).

Vive num modulo proprio porque indexer e mcp_server precisam aplicar
EXATAMENTE a mesma transformacao: o que for gravado em Chunk.search_text tem
de casar com o que a consulta vira na hora da busca. Se as duas pontas
divergirem, a busca lexical simplesmente para de achar as coisas, sem erro
nenhum aparecendo.

Por que normalizar em vez de indexar o texto cru:

- Acento. O RediSearch nao equipara "rejeicao" a "rejeicao" acentuada, e o
  usuario digita das duas formas (verificado contra o indice real).
- Pontuacao. "NFC-e" nao retorna nada com o hifen: o hifen e sintaxe de
  negacao do RediSearch. "@", aspas e ":" chegam a causar erro de sintaxe.
"""
import re
import unicodedata

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def normalize(text: str) -> str:
    """Texto pronto para gravar em search_text ou para montar a consulta."""
    return " ".join(_TOKEN_RE.findall(strip_accents(str(text).lower())))


def to_fulltext_query(text: str, max_terms: int = 40) -> str:
    """Monta a consulta RediSearch a partir do texto do usuario.

    Os termos sao unidos por OR (`|`). O default do RediSearch e AND, que numa
    pergunta de suporte de 15 palavras nao casaria com nada. Como a saida so
    contem [a-z0-9] e `|`, nao ha como injetar sintaxe.
    """
    termos = _TOKEN_RE.findall(strip_accents(str(text).lower()))
    termos = [t for t in termos if len(t) > 1][:max_terms]
    return "|".join(dict.fromkeys(termos))
