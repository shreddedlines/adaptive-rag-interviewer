from functools import lru_cache

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.config import settings
from app.models import ResumeProfile, SourceChunk
from app.services.documents import DocumentChunk, knowledge_role_for_target, load_knowledge_chunks


class KnowledgeIndex:
    def __init__(self, chunks: list[DocumentChunk]):
        self.chunks = chunks
        self.vectorizer = TfidfVectorizer(stop_words="english", max_features=18000, ngram_range=(1, 2))
        self.matrix = self.vectorizer.fit_transform([chunk.text for chunk in chunks]) if chunks else None

    def search(self, query: str, limit: int | None = None) -> list[SourceChunk]:
        if not self.chunks or self.matrix is None:
            return []
        limit = limit or settings.top_k
        query_vector = self.vectorizer.transform([query])
        scores = cosine_similarity(query_vector, self.matrix).flatten()
        top_local_indices = np.argsort(scores)[::-1][:limit]

        results: list[SourceChunk] = []
        for local_index in top_local_indices:
            score = float(scores[local_index])
            chunk = self.chunks[int(local_index)]
            if score <= 0:
                continue
            results.append(
                SourceChunk(
                    document=chunk.document,
                    role=chunk.role,
                    page=chunk.page,
                    score=round(score, 4),
                    text=chunk.text[:900],
                )
            )
        return results


@lru_cache(maxsize=8)
def get_index(role: str) -> KnowledgeIndex:
    return KnowledgeIndex(load_knowledge_chunks(knowledge_role_for_target(role)))


def build_query(role: str, profile: ResumeProfile, previous_answer: str | None = None) -> str:
    profile_terms = " ".join(profile.skills + profile.domains + profile.technologies)
    seniority = profile.seniority_signal.replace("-", " ")
    answer_terms = previous_answer or ""
    return f"{role} interview {seniority} {profile_terms} {answer_terms}".strip()
