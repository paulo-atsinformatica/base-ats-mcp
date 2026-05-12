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
        """Gera embedding para um único texto (legado)."""
        return self.generate_batch([text])[0]

    def generate_batch(self, texts: list[str]):
        """Gera embeddings para uma lista de textos usando a API de lote."""
        if not texts:
            return []
            
        # Limite da API do Gemini: 100 instâncias por request
        batch_size = 100
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            current_batch = texts[i : i + batch_size]
            max_retries = 10
            for attempt in range(max_retries):
                try:
                    result = self.client.models.embed_content(
                        model=self.model_name,
                        contents=current_batch,
                        config=genai_types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
                    )
                    all_embeddings.extend([e.values for e in result.embeddings])
                    break # Sucesso, sai do loop de retry do batch atual
                except Exception as e:
                    err_msg = str(e)
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        # Backoff mais agressivo para a cota gratuita (100 RPM)
                        wait_time = (2 ** attempt) + (random.random() * 2)
                        logger.warning("quota_exceeded_retrying_batch", 
                                       attempt=attempt, 
                                       wait=round(wait_time, 2), 
                                       size=len(current_batch))
                        time.sleep(wait_time)
                        continue
                    raise e
            else:
                logger.error("max_retries_reached_for_batch", size=len(current_batch))
                raise Exception(f"Failed to generate embeddings after {max_retries} retries due to quota")
        
        return all_embeddings

embedding_generator = EmbeddingGenerator()
