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

chunker = Chunker()
