import frontmatter
from typing import Dict, Any, List
from .telemetry import tracer

class MarkdownParser:
    @staticmethod
    def parse(content: str) -> Dict[str, Any]:
        with tracer.start_as_current_span("parse_markdown"):
            post = frontmatter.loads(content)
            return {
                "metadata": post.metadata,
                "content": post.content
            }

markdown_parser = MarkdownParser()
