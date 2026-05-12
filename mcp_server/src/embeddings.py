import time
import random
from google import genai
from google.genai import types as genai_types
from .config import settings
from .telemetry import tracer
from .logger import logger

class EmbeddingGenerator:
    def __init__(self):
        logger.info("initializing_google_embeddings", model=settings.EMBEDDING_MODEL)
        if not settings.GOOGLE_API_KEY:
            logger.error("missing_google_api_key")
            raise ValueError("GOOGLE_API_KEY must be set")
        self.client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        self.model_name = settings.EMBEDDING_MODEL

    def generate(self, text: str):
        """Gera embedding para um único texto (busca)."""
        return self.generate_batch([text], task_type="RETRIEVAL_QUERY")[0]

    def generate_batch(self, texts: list[str], task_type: str = "RETRIEVAL_QUERY"):
        """Gera embeddings para uma lista de textos usando a API de lote."""
        if not texts:
            return []
            
        batch_size = 100
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            current_batch = texts[i : i + batch_size]
            with tracer.start_as_current_span("generate_embeddings_batch"):
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        result = self.client.models.embed_content(
                            model=self.model_name,
                            contents=current_batch,
                            config=genai_types.EmbedContentConfig(task_type=task_type),
                        )
                        all_embeddings.extend([e.values for e in result.embeddings])
                        break
                    except Exception as e:
                        err_msg = str(e)
                        if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                            wait_time = (2 ** attempt) + random.random()
                            logger.warning("quota_exceeded_retrying_batch", attempt=attempt, wait=wait_time)
                            time.sleep(wait_time)
                            continue
                        raise e
                else:
                    raise Exception("Failed to generate embeddings after multiple retries due to quota")
        
        return all_embeddings

embedding_generator = EmbeddingGenerator()
