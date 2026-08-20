"""A deliberately small, deterministic retriever for the Dispute Responder's RAG.

Chunking is by REASON-CODE SECTION, not fixed size (ADR-020): the corpus is
highly structured — each reason code's requirements form one coherent unit — and
naive fixed-size chunking would split a reason code from its evidence list,
which the retrieval eval confirms hurts recall. No embeddings, no network: a
transparent term-overlap score, so retrieval is testable and offline.

Every claim the agent makes cites its source chunk id; uncited claims are a
failure asserted in evals.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sentinel.common.config import repo_root

CORPUS_DIR = repo_root() / "corpus" / "dispute_evidence"
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Chunk:
    id: str            # the reason-code section id
    title: str
    text: str
    requirements: tuple[str, ...]


def _parse(md: str, chunk_id: str) -> Chunk:
    title = ""
    reqs: list[str] = []
    in_req = False
    for line in md.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.strip().lower().startswith("## required evidence"):
            in_req = True
        elif line.startswith("## "):
            in_req = False
        elif in_req and line.strip().startswith("- "):
            reqs.append(line.strip()[2:])
    return Chunk(id=chunk_id, title=title, text=md, requirements=tuple(reqs))


def load_corpus() -> list[Chunk]:
    chunks = []
    for path in sorted(CORPUS_DIR.glob("*.md")):
        chunks.append(_parse(path.read_text(), path.stem))
    return chunks


def _score(query: str, chunk: Chunk) -> float:
    q = set(_WORD.findall(query.lower()))
    d = _WORD.findall(chunk.text.lower())
    if not q or not d:
        return 0.0
    dset = set(d)
    overlap = len(q & dset)
    # boost an exact reason-code id match (the structured signal)
    boost = 2.0 if chunk.id in query.lower().replace(" ", "_") else 0.0
    return overlap / len(q) + boost


def retrieve(query: str, k: int = 1) -> list[Chunk]:
    scored = sorted(load_corpus(), key=lambda c: _score(query, c), reverse=True)
    return [c for c in scored if _score(query, c) > 0][:k]
