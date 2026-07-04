from __future__ import annotations

from rdagent.oai.backend.litellm import LiteLLMAPIBackend

from a_share_pipeline.embeddings import local_embedding


class LocalEmbeddingLiteLLMBackend(LiteLLMAPIBackend):
    """DeepSeek chat through LiteLLM with a zero-service local embedding path."""

    def _create_embedding_inner_function(self, input_content_list: list[str]) -> list[list[float]]:
        return [local_embedding(text) for text in input_content_list]
