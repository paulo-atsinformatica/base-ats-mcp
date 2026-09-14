"""Reescreve as consultas do golden set como um usuario real as escreveria.

Por que isso existe: as consultas extraidas do proprio documento sao trechos
literais dele. Qualquer retriever, denso ou lexical, acerta quase 100% nelas
(medimos: BM25 chega a R@5 = 0,99), entao a metrica satura e nao consegue
distinguir uma configuracao boa de uma ruim. A parafrase remove o atalho
lexical e deixa a avaliacao discriminativa.

A trilha erro_literal NAO e parafraseada de proposito: o analista realmente
cola a mensagem de erro exata, entao ali a consulta literal e a consulta real.

Usa a REST API do Gemini direto (sem SDK). Retoma de onde parou: consultas ja
presentes no arquivo de saida sao puladas.

Uso:
  python paraphrase_goldenset.py                 # usa GOOGLE_API_KEY do .env
  python paraphrase_goldenset.py --limit 100     # amostra menor / teste
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path

import httpx

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
SKIP_TRACKS = {"erro_literal"}

PROMPT = """Voce recebe {n} trechos extraidos de uma base de conhecimento de suporte de um ERP brasileiro.

Para cada trecho, escreva a pergunta que um usuario REAL faria ao suporte sobre aquele assunto.

Regras:
- Portugues do Brasil, tom de quem abre chamado ("nao consigo...", "como faco para...", "da erro quando...").
- Uma frase, no maximo 25 palavras.
- NAO copie sequencias de 3 ou mais palavras seguidas do trecho: use palavras do dia a dia no lugar dos termos tecnicos sempre que existir equivalente.
- Mantenha apenas os nomes proprios indispensaveis para identificar o assunto (nome de tela, modulo, documento fiscal). Nao invente codigo, numero de versao nem nome de tabela.
- Se o trecho descreve um problema, escreva do ponto de vista de quem sofre o problema, nao de quem ja sabe a causa.

Responda SOMENTE com um array JSON de {n} strings, na mesma ordem, sem markdown.

Trechos:
{items}"""


def load_key(env_path: Path) -> str:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("GOOGLE_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("GOOGLE_API_KEY nao encontrada em " + str(env_path))


def call_model(key: str, model: str, prompt: str) -> str:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
    }
    # a URL ja contem /models/: aceitar tanto "gemini-x" quanto "models/gemini-x"
    url = ENDPOINT.format(model=model.removeprefix("models/"))
    for attempt in range(6):
        try:
            response = httpx.post(url, params={"key": key}, json=payload, timeout=120.0)
            if response.status_code == 429:
                raise httpx.HTTPStatusError("429", request=response.request, response=response)
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except httpx.HTTPStatusError as exc:
            # 4xx que nao seja 429 e erro permanente: nao adianta insistir.
            if exc.response.status_code not in (429, 500, 502, 503, 504):
                raise SystemExit("erro %d do Gemini: %s"
                                 % (exc.response.status_code, exc.response.text[:300]))
            wait = (2 ** attempt) + random.random()
            print("  retry %d apos %.1fs (%s)" % (attempt + 1, wait, str(exc)[:90]))
            time.sleep(wait)
        except Exception as exc:  # noqa: BLE001 - backoff generico proposital
            wait = (2 ** attempt) + random.random()
            print("  retry %d apos %.1fs (%s)" % (attempt + 1, wait, str(exc)[:90]))
            time.sleep(wait)
    raise SystemExit("falha ao chamar o modelo apos 6 tentativas")


def parse_array(text: str, expected: int) -> list[str] | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, list) or len(data) != expected:
        return None
    return [str(x).strip() for x in data]


def main() -> None:
    here = Path(__file__).parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--goldenset", default=str(here / "goldenset.jsonl"))
    parser.add_argument("--out", default=str(here / "goldenset_paraphrased.jsonl"))
    parser.add_argument("--env", default=str(here.parent / ".env"))
    parser.add_argument("--model", default="models/gemini-3.5-flash-lite")
    parser.add_argument("--batch", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    key = load_key(Path(args.env))
    rows = [json.loads(line) for line in open(args.goldenset, encoding="utf-8")]

    out_path = Path(args.out)
    done: dict[str, dict] = {}
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            row = json.loads(line)
            done[row["qid"]] = row
        print("retomando: %d consultas ja parafraseadas" % len(done))

    pendentes = [r for r in rows if r["qid"] not in done and r["track"] not in SKIP_TRACKS]
    if args.limit:
        pendentes = pendentes[: args.limit]
    print("a parafrasear: %d (de %d no golden set)" % (len(pendentes), len(rows)))

    novos: list[dict] = []
    for start in range(0, len(pendentes), args.batch):
        lote = pendentes[start : start + args.batch]
        items = "\n".join(
            "%d. %s" % (i + 1, r["query"][:400]) for i, r in enumerate(lote)
        )
        prompt = PROMPT.format(n=len(lote), items=items)
        text = call_model(key, args.model, prompt)
        parafrases = parse_array(text, len(lote))
        if parafrases is None:
            print("  lote %d: resposta fora do formato, mantendo original" % (start // args.batch))
            parafrases = [r["query"] for r in lote]
        for row, nova in zip(lote, parafrases):
            novo = dict(row)
            novo["query_original"] = row["query"]
            novo["query"] = nova
            novo["parafraseada"] = nova != row["query"]
            novos.append(novo)
        print("  lote %d/%d ok" % (start // args.batch + 1,
                                   (len(pendentes) + args.batch - 1) // args.batch))
        time.sleep(1.0)

    # Trilhas nao parafraseadas entram verbatim, para o arquivo ficar completo.
    verbatim = [
        dict(r, query_original=r["query"], parafraseada=False)
        for r in rows
        if r["track"] in SKIP_TRACKS and r["qid"] not in done
    ]

    todas = list(done.values()) + novos + verbatim
    todas.sort(key=lambda r: r["qid"])
    with out_path.open("w", encoding="utf-8") as fh:
        for row in todas:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    n_par = sum(1 for r in todas if r.get("parafraseada"))
    print("escrito: %s (%d consultas, %d parafraseadas)" % (out_path, len(todas), n_par))


if __name__ == "__main__":
    main()
