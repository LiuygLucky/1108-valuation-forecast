"""FAISS retrieval rebuilt from the time-filtered SQLite evidence set."""

import faiss
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

from forecast_agent.config import Settings
from forecast_agent.schemas import Evidence


class VectorMemory:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.encoder = None

    def encode(self, texts: list[str]) -> np.ndarray:
        if self.settings.embedding_backend == "hashing":
            vectorizer = HashingVectorizer(
                n_features=self.settings.embedding_dimensions,
                alternate_sign=False,
                analyzer="char_wb",
                ngram_range=(2, 4),
                norm="l2",
            )
            return vectorizer.transform(texts).toarray().astype("float32")
        if self.encoder is None:
            from sentence_transformers import SentenceTransformer

            self.encoder = SentenceTransformer(self.settings.embedding_model, device="cpu")
        return np.asarray(self.encoder.encode(texts, normalize_embeddings=True), dtype="float32")

    def retrieve(self, question: str, evidence: list[Evidence], limit=20, category: str | None = None):
        eligible = [
            e for e in evidence if not e.exclusion_reasons and (category is None or e.category == category)
        ]
        if not eligible:
            return []
        vectors = self.encode(
            [e.claim + " " + e.category + " " + " ".join(e.causal_mechanisms) for e in eligible]
        )
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        _, positions = index.search(self.encode([question]), min(limit, len(eligible)))
        return [eligible[i] for i in positions[0] if i >= 0]
