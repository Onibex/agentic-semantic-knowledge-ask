"""
Infrastructure layer — pipeline v2.

Estado actual: VACÍO. Reusamos la infra de v1:
  - OpenSearchAskRepository (src/pipeline/infrastructure/repositories/)
  - SAPAICoreEmbedder       (src/pipeline/infrastructure/embedders/)
  - get_chat_llm            (utils/llm_factory.py)

Si v2 necesita infra específica (p.ej. un repo con query patterns distintos),
se agrega aquí sin tocar v1.
"""
