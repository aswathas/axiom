"""Naive RAG — the strawman this project is measured against.

WHAT THIS IS
------------
A deliberately simple retrieval-augmented generation pipeline: split documents
into overlapping character windows, score them with TF-IDF-weighted
bag-of-words cosine similarity, take the top k, and ask an LLM to answer the
question using only that text. That is roughly what a competent team builds in
a weekend, and it is roughly what a clinician gets when they paste a chart into
ChatGPT. It is here so the comparison against AXIOM is honest.

IT IS NOT HERE
--------------
  * not a strawman in the rigged sense — no sabotaged retrieval, no
    deliberately weak prompt, no forced failure;
  * not a claim about all RAG systems. Dense retrievers, query rewriting and
    citation-constrained decoding all do improve on this. None of them address
    the failure below, which is a failure of *epistemics*, not of retrieval.

THE FAILURE THIS DEMONSTRATES
-----------------------------
Ask "Does this patient have a DVT / blood clot?" on a record containing no
coagulation panel, no D-dimer, no INR, no venous ultrasound. This pipeline
retrieves the nearest-looking text (a note about dyspnea, a renal panel), the
prompt says "answer using only the context provided", and the model replies
"No documented evidence of DVT." That sentence is technically faithful to the
context. It is also indistinguishable, to a human reader under time pressure,
from "this patient does not have a blood clot."

The record supports neither. It supports "this was never looked for."

MEASURED, not assumed
----------------------
Running this class with a real model (``openai/gpt-4o-mini`` via OpenRouter)
against a renal-panel + discharge-summary record with no coagulation workup,
verbatim:

    Q: Does this patient have a DVT / blood clot?
    A: "No, the patient does not have a DVT / blood clot."

    Q: Is there evidence of a pulmonary embolism?
    A: "No, there is no evidence of a pulmonary embolism."

    Q: Is this patient anaemic?
    A: "The provided context does not include any information about the
        patient's hemoglobin levels ... Therefore, it cannot be determined if
        the patient is anaemic."

Read that honestly: the strawman does **not** fail uniformly. It fails hardest
on disease-absence questions ("does this patient have X?"), where the model
commits to a flat denial. It behaves better when the question maps onto a
specific measurement the reader can see is missing — anaemia maps onto
hemoglobin, and the model notices the gap. Use disease-absence queries in the
demo; they are both the realistic clinician question and the one that fails.

`answer()` therefore NEVER sets ``refused=True`` on absence of evidence, has no
relevance-score floor, and contains no hedging instruction in the prompt. Those
are the demonstration. AXIOM's refusal is the other half of the split screen
and lives in `axiom/pipeline.py`.

Standard library only for retrieval — no embeddings model, no vector store.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Iterable, Optional

__all__ = ["NaiveRAG", "tokenize", "SYSTEM_PROMPT", "DEFAULT_CHUNK_SIZE",
           "DEFAULT_OVERLAP"]

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------

# 800 characters is ~130 words: about one short paragraph of a narrative note
# or one full block of a lab table. Large enough that a negating scope ("she
# denies ...") is not routinely split across a chunk boundary; small enough
# that five retrieved chunks still fit comfortably in a prompt.
DEFAULT_CHUNK_SIZE = 800

# 120 characters of overlap (~20 words) is the smallest overlap that reliably
# keeps a sentence intact when the window slides. A fact stated in one sentence
# and its negation in the next is exactly the boundary that must not be cut.
DEFAULT_OVERLAP = 120

DEFAULT_TOP_K = 5

# The prompt a competent engineer writes on a weekend. No hedging, no
# "say if the context is insufficient", no refusal instruction. Adding any of
# those would make the baseline look good and destroy the comparison.
SYSTEM_PROMPT = "Answer the question using only the context provided."

USER_TEMPLATE = (
    "Context:\n"
    "{context}\n"
    "\n"
    "Question: {query}\n"
    "\n"
    "Return JSON: {{\"answer\": \"<your answer>\"}}"
)

STOPWORDS = frozenset("""
a an the and or but if then than that this these those of in on at to for from
by with without into over under is are was were be been being am do does did
have has had having it its as not no nor so such can could will would shall
should may might must i you he she they we me him her them us my your his their
there here when where which who whom whose what how why all any both each few
more most other some only own same too very s t just don now
""".split())

_WORD_RE = re.compile(r"[A-Za-z0-9]+")

_LOG = logging.getLogger("axiom.baseline_rag")


# --------------------------------------------------------------------------
# Tokenisation and vectors
# --------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    """Lowercase word tokens with stopwords removed.

    No stemming, no n-grams, no synonyms. A bag of words is the honest cheap
    first move; stemming would help marginally and costs a dependency.
    """
    return [t for t in (w.lower() for w in _WORD_RE.findall(text or ""))
            if t not in STOPWORDS and len(t) > 1]


class _VectorSpace:
    """TF-IDF bag-of-words index with cosine similarity.

    IDF is included because any competent implementation uses it, and using it
    makes retrieval *better*. We are not handicapping the strawman.
    """

    def __init__(self) -> None:
        self._df: dict[str, int] = {}
        self._n_docs: int = 0
        self._vectors: list[dict[str, float]] = []
        self._norms: list[float] = []

    def add(self, text: str) -> dict[str, float]:
        tf: dict[str, int] = {}
        for tok in tokenize(text):
            tf[tok] = tf.get(tok, 0) + 1

        new_terms = [t for t in tf if t not in self._df]
        # Document frequency must include this document for the IDF to be right.
        for t in new_terms:
            self._df[t] = 0
        for t in tf:
            self._df[t] += 1
        self._n_docs += 1

        idf = {t: math.log((self._n_docs + 1.0) / (self._df[t] + 1.0)) + 1.0
               for t in tf}
        vec = {t: (1.0 + math.log(c)) * idf[t] for t, c in tf.items()}
        self._vectors.append(vec)
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        self._norms.append(norm)
        return vec

    def cosine(self, query_vec: dict[str, float]) -> list[float]:
        qnorm = math.sqrt(sum(v * v for v in query_vec.values())) or 1.0
        q_items = list(query_vec.items())
        out = []
        for vec, dnorm in zip(self._vectors, self._norms):
            # iterate the shorter side and probe the longer one
            if len(vec) <= len(query_vec):
                small, large = vec, query_vec
            else:
                small, large = query_vec, vec
            total = sum(w * large.get(t, 0.0) for t, w in small.items())
            out.append(total / (qnorm * dnorm))
        return out

    @staticmethod
    def query_vector(text: str, idf: dict[str, int], n_docs: int) -> dict[str, float]:
        tf: dict[str, int] = {}
        for tok in tokenize(text):
            tf[tok] = tf.get(tok, 0) + 1
        vec = {}
        for t, c in tf.items():
            idf_t = (math.log((n_docs + 1.0) / (idf.get(t, 0) + 1.0)) + 1.0
                     if n_docs else 1.0)
            vec[t] = (1.0 + math.log(c)) * idf_t
        return vec


# --------------------------------------------------------------------------
# The baseline
# --------------------------------------------------------------------------

class NaiveRAG:
    """Chunk -> bag-of-words retrieve -> prompt the LLM -> answer.

    Demonstration baseline. Deliberately simple. Present so that the side-by-
    side comparison against AXIOM's refusal behaviour is honest rather than a
    rigged contest.

    Example
    -------
    >>> rag = NaiveRAG()
    >>> out = rag.answer("Does this patient have a DVT?", docs)
    >>> out["refused"]
    False
    """

    def __init__(self, llm: Any = None, chunk_size: int = DEFAULT_CHUNK_SIZE,
                 overlap: int = DEFAULT_OVERLAP, top_k: int = DEFAULT_TOP_K):
        self.llm = llm
        self.chunk_size = int(chunk_size)
        self.overlap = max(0, int(overlap))
        self.top_k = int(top_k)
        self.chunks: list[dict[str, Any]] = []
        self._space = _VectorSpace()

    # -- indexing ---------------------------------------------------------

    def index(self, documents: list[dict]) -> None:
        """(Re)build the index. Documents are ``{"doc_id","page","text"}``."""
        self.chunks = []
        self._space = _VectorSpace()
        for doc in documents or []:
            self.chunks.extend(self._chunk_doc(doc))

    @property
    def _stride(self) -> int:
        return max(1, self.chunk_size - self.overlap)

    def _chunk_doc(self, doc: dict) -> list[dict[str, Any]]:
        text = doc.get("text") or ""
        doc_id = str(doc.get("doc_id") or "")
        page = doc.get("page", 1)
        if not text.strip():
            return []

        bounds = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
        starts = [b[0] for b in bounds]
        ends = [b[1] for b in bounds]

        out: list[dict[str, Any]] = []
        i = 0
        while i < len(bounds):
            # extend to the first word starting at/after chunk_size chars
            limit = starts[i] + self.chunk_size
            end_i = i
            while end_i < len(bounds) and starts[end_i] < limit:
                end_i += 1
            if end_i == i:
                end_i = i + 1
            c_start, c_end = starts[i], ends[end_i - 1]

            body = text[c_start:c_end]
            out.append({
                "chunk_id": f"{doc_id}#p{page}#{len(out)}",
                "doc_id": doc_id,
                "page": page,
                "char_start": c_start,
                "char_end": c_end,
                "text": body,
            })

            if end_i >= len(bounds):
                break
            # The next window re-enters `overlap` characters back from where
            # this one ended, so the boundary sentence is never orphaned.
            target = c_end - self.overlap
            nxt = i
            while nxt < len(bounds) and starts[nxt] < target:
                nxt += 1
            i = nxt if nxt > i else i + 1

        for c in out:
            self._space.add(c["text"])
        return out

    # -- retrieval --------------------------------------------------------

    def retrieve(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
        """Return the ``top_k`` highest-similarity chunks.

        There is no minimum-score gate. A query with zero term overlap still
        gets chunks back, because a pipeline that checks "did I retrieve
        anything relevant?" and then admits it did not is no longer the naive
        baseline.
        """
        k = min(int(top_k), len(self.chunks))
        if k <= 0:
            return []
        qvec = _VectorSpace.query_vector(query, self._space._df, self._space._n_docs)
        if not qvec:
            ranked = [(c, 0.0) for c in self.chunks[:k]]
        else:
            scores = self._space.cosine(qvec)
            order = sorted(range(len(self.chunks)), key=lambda j: -scores[j])[:k]
            ranked = [(self.chunks[j], scores[j]) for j in order]

        hits = []
        for chunk, score in ranked:
            hit = dict(chunk)
            hit["score"] = float(score)
            hits.append(hit)
        return hits

    # -- answering --------------------------------------------------------

    def answer(self, query: str, patient_docs: Optional[list[dict]] = None,
               top_k: Optional[int] = None) -> dict[str, Any]:
        """Answer ``query`` from ``patient_docs``.

        Returns ``{"answer": str, "citations": list[dict], "refused": bool}``.

        ``refused`` is always False. This class does not implement refusal; the
        whole demonstration is that it does not need to know one. If a
        ``refused=True`` ever appears here, the comparison has been rigged.

        If ``patient_docs`` is ``None`` the existing index is reused, so callers
        can index once and ask many questions.
        """
        k = self.top_k if top_k is None else int(top_k)
        if patient_docs is not None:
            self.index(patient_docs)
        hits = self.retrieve(query, top_k=k)
        citations = [
            {"chunk_id": h["chunk_id"], "doc_id": h["doc_id"],
             "page": h["page"], "char_start": h["char_start"],
             "char_end": h["char_end"], "score": h["score"]}
            for h in hits
        ]

        context = _format_context(hits)
        answer = None
        if self.llm is not None and hits:
            answer = self._call_llm(query, context)
        if not answer:
            # Fallback: quote the top chunk. Not a good answer — a *boring*
            # one. But the demo must run with no network and no API key.
            answer = hits[0]["text"].strip() if hits else (
                "No documents were available for this patient.")

        return {"answer": answer, "citations": citations, "refused": False}

    def _call_llm(self, query: str, context: str) -> Optional[str]:
        user = USER_TEMPLATE.format(context=context, query=query)
        try:
            raw = self.llm.json(SYSTEM_PROMPT, user)
        except Exception as exc:  # noqa: BLE001 - deliberate
            # LLMUnavailable, network error, or a mock that misbehaves. The
            # baseline degrades to quote-the-chunk rather than failing the demo
            # — but it logs, because a silent fallback during a live demo looks
            # like the model produced that text, and it did not.
            _LOG.warning("NaiveRAG: LLM call failed (%s: %s); quoting top chunk",
                         type(exc).__name__, exc)
            return None
        if isinstance(raw, str):
            return raw.strip() or None
        if isinstance(raw, dict):
            val = raw.get("answer")
            if isinstance(val, str) and val.strip():
                return val.strip()
        return None


def _format_context(hits: Iterable[dict[str, Any]]) -> str:
    """Render retrieved chunks as `[1] (doc, page n)` blocks.

    Numbered so the model could in principle cite them. It usually does not,
    which is why AXIOM computes citations from provenance rather than asking
    for them in the prompt.
    """
    blocks = []
    for i, h in enumerate(hits, start=1):
        blocks.append(f"[{i}] ({h['doc_id']}, page {h['page']})\n{h['text']}")
    return "\n\n".join(blocks)