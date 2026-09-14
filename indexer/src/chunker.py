import re
from typing import List, Dict
from .telemetry import tracer

class Chunker:
    @staticmethod
    def chunk_by_headings(content: str) -> List[Dict[str, str]]:
        with tracer.start_as_current_span("chunk_content"):
            # Split by any H2 or H1 heading
            chunks = []
            lines = content.split('\n')
            
            current_heading = "Intro"
            current_content = []
            
            for line in lines:
                if line.startswith('## ') or line.startswith('# '):
                    if current_content:
                        chunks.append({
                            "heading": current_heading,
                            "content": '\n'.join(current_content).strip()
                        })
                    current_heading = line.strip('#').strip()
                    current_content = []
                else:
                    current_content.append(line)
            
            if current_content:
                chunks.append({
                    "heading": current_heading,
                    "content": '\n'.join(current_content).strip()
                })
                
            return [c for c in chunks if c["content"]]

    @staticmethod
    def context_header(metadata: dict, heading: str = None) -> str:
        """Preambulo com o contexto do documento, prefixado ao texto EMBEDDADO.

        Sem ele, um chunk "## Solucao" com "1. Acesse o cadastro..." nao contem
        o erro que resolve, nem o modulo a que pertence: fica orfao no espaco
        vetorial. Medido em eval/: recall@1 na mensagem de erro literal sobe de
        0,82 para 0,94 (harness BM25, 1.200 consultas).

        Vale so para o vetor. O `content` gravado no chunk continua limpo, que
        e o que vai para o contexto do LLM.
        """
        bits = [str(metadata.get("title", "")).strip()]
        if metadata.get("type"):
            bits.append("tipo: " + str(metadata["type"]))
        if metadata.get("modulos"):
            bits.append("modulos: " + ", ".join(str(m) for m in metadata["modulos"]))
        if metadata.get("tags"):
            bits.append("tags: " + ", ".join(str(t) for t in metadata["tags"]))
        if heading and heading != "Intro":
            bits.append("secao: " + heading)
        return " | ".join(b for b in bits if b)

    @staticmethod
    def embedding_text(metadata: dict, chunk: dict) -> str:
        return Chunker.context_header(metadata, chunk.get("heading")) + "\n" + chunk["content"]

chunker = Chunker()
