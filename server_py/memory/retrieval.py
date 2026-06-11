from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any


CODE_PATH_RE = re.compile(r"(?:[A-Za-z0-9_.@-]+[\\/])+[A-Za-z0-9_.@-]+")
ASCII_RE = re.compile(r"[a-z0-9_./:@-]{2,}")
CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
SPLIT_SYMBOL_RE = re.compile(r"[_./:@\\-]+|(?<=[a-z])(?=[A-Z])")


KIND_BOOSTS = {
    "instruction": 2.4,
    "search_intent": 2.0,
    "curated": 1.9,
    "repo": 1.8,
    "failure": 1.7,
    "decision": 1.5,
    "skill": 1.2,
    "requirement": 1.0,
    "delivery": 0.9,
    "preview": 0.9,
    "agent": 0.6,
}


class MemoryRetriever:
    """Multi-signal local memory retrieval.

    This is intentionally model-free and deterministic for the runtime path.
    It is stronger than raw term overlap: BM25 ranks evidence, phrase/path/code
    signals catch project-specific references, importance/pin/recency provide a
    memory prior, and a diversity pass avoids one noisy bucket taking the whole
    context budget.
    """

    def recall(self, entries: list[dict[str, Any]], query: str, limit: int = 10) -> dict[str, Any]:
        candidates = [self._normalize_entry(entry) for entry in entries if self._entry_content(entry)]
        query_tokens = self.tokens(query)
        if not candidates:
            return self._empty(query, 0)

        docs = [self.tokens(candidate["searchText"]) for candidate in candidates]
        avg_doc_len = max(sum(len(doc) for doc in docs) / len(docs), 1.0)
        document_frequency = self._document_frequency(docs)
        total_docs = len(docs)

        scored: list[dict[str, Any]] = []
        for candidate, tokens in zip(candidates, docs):
            signals = self._score_signals(candidate, tokens, query, query_tokens, document_frequency, total_docs, avg_doc_len)
            score = sum(signals.values())
            if score <= 0:
                continue
            scored.append({**candidate, "score": score, "matchSignals": signals, "reason": self._reason(signals)})

        scored.sort(key=lambda item: item["score"], reverse=True)
        # 质量门槛:limit 是上限不是配额。低于绝对底线或与榜首差距过大的
        # 候选不进上下文——凑数的弱相关条目就是噪音,宁缺毋滥。
        if scored:
            top_score = scored[0]["score"]
            floor = max(3.0, top_score * 0.22)
            scored = [item for item in scored if item["score"] >= floor or item.get("pinned")]
        selected = self._diversify(scored, limit)
        return {
            "query": query,
            "strategy": "bm25+phrase+path+symbol+importance+recency+pin+diversity",
            "candidateCount": len(candidates),
            "items": [self._to_recall_item(item) for item in selected],
        }

    def tokens(self, text: str) -> list[str]:
        lowered = str(text or "").lower()
        tokens: list[str] = []
        tokens.extend(ASCII_RE.findall(lowered))
        for path in CODE_PATH_RE.findall(text or ""):
            normalized_path = path.replace("\\", "/").lower()
            tokens.append(normalized_path)
            tokens.extend(part for part in re.split(r"[/._:@-]+", normalized_path) if len(part) >= 2)
        for ascii_token in ASCII_RE.findall(text or ""):
            parts = [part.lower() for part in SPLIT_SYMBOL_RE.split(ascii_token) if len(part) >= 2]
            tokens.extend(parts)
        for block in CJK_RE.findall(text or ""):
            if 2 <= len(block) <= 16:
                tokens.append(block)
            tokens.extend(block[index : index + 2] for index in range(max(len(block) - 1, 0)))
            tokens.extend(block[index : index + 3] for index in range(max(len(block) - 2, 0)))
        return [token for token in tokens if token and len(token) >= 2]

    def _score_signals(
        self,
        entry: dict[str, Any],
        tokens: list[str],
        query: str,
        query_tokens: list[str],
        document_frequency: Counter[str],
        total_docs: int,
        avg_doc_len: float,
    ) -> dict[str, float]:
        bm25 = self._bm25(tokens, query_tokens, document_frequency, total_docs, avg_doc_len)
        phrase = self._phrase_score(entry["searchText"], query)
        path = self._path_score(entry, query)
        kind = KIND_BOOSTS.get(str(entry.get("kind")), 0.5)
        importance = min(float(entry.get("importance") or 1.0), 5.0) * 0.8
        recency = self._recency_score(entry.get("createdAt"))
        pinned = 4.0 if entry.get("pinned") else 0.0
        long_term = 0.45 if entry.get("scope") in {"workspace", "repository"} else 0.0
        tag = self._tag_score(entry, query_tokens)
        return {
            "bm25": round(bm25 * 2.2, 4),
            "phrase": round(phrase, 4),
            "path": round(path, 4),
            "kind": round(kind, 4),
            "importance": round(importance, 4),
            "recency": round(recency, 4),
            "pinned": round(pinned, 4),
            "longTerm": round(long_term, 4),
            "tag": round(tag, 4),
        }

    def _bm25(
        self,
        tokens: list[str],
        query_tokens: list[str],
        document_frequency: Counter[str],
        total_docs: int,
        avg_doc_len: float,
    ) -> float:
        if not tokens or not query_tokens:
            return 0.0
        counts = Counter(tokens)
        doc_len = len(tokens)
        k1 = 1.4
        b = 0.72
        score = 0.0
        for token in set(query_tokens):
            frequency = counts[token]
            if not frequency:
                continue
            df = document_frequency[token]
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            denom = frequency + k1 * (1 - b + b * doc_len / avg_doc_len)
            score += idf * (frequency * (k1 + 1)) / max(denom, 0.0001)
        return score

    def _document_frequency(self, docs: list[list[str]]) -> Counter[str]:
        counter: Counter[str] = Counter()
        for doc in docs:
            counter.update(set(doc))
        return counter

    def _phrase_score(self, text: str, query: str) -> float:
        lowered_text = text.lower()
        lowered_query = (query or "").lower().strip()
        if not lowered_query:
            return 0.0
        score = 0.0
        if lowered_query and lowered_query in lowered_text:
            score += 4.0
        query_parts = [part for part in re.split(r"\s+", lowered_query) if len(part) >= 3]
        for size in (4, 3, 2):
            for index in range(0, max(len(query_parts) - size + 1, 0)):
                phrase = " ".join(query_parts[index : index + size])
                if phrase in lowered_text:
                    score += 0.7 * size
        return score

    def _path_score(self, entry: dict[str, Any], query: str) -> float:
        query_paths = {path.replace("\\", "/").lower() for path in CODE_PATH_RE.findall(query or "")}
        if not query_paths:
            return 0.0
        haystack = f"{entry.get('sourcePath', '')}\n{entry.get('content', '')}".replace("\\", "/").lower()
        return sum(2.5 for path in query_paths if path in haystack)

    def _tag_score(self, entry: dict[str, Any], query_tokens: list[str]) -> float:
        tags = {str(tag).lower() for tag in entry.get("tags", [])}
        if not tags:
            return 0.0
        overlap = len(tags & set(query_tokens))
        priority = len(tags & {"failure", "decision", "instructions", "repo", "skill", "checkpoint", "rollback"})
        return overlap * 0.8 + priority * 0.3

    def _recency_score(self, created_at: Any) -> float:
        if not created_at:
            return 0.0
        try:
            created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        age_days = max((datetime.now(timezone.utc) - created).total_seconds() / 86400, 0.0)
        return 0.8 / (1.0 + age_days / 14.0)

    def _diversify(self, scored: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        kind_counts: Counter[str] = Counter()
        max_per_kind = max(2, math.ceil(limit / 3))

        for item in scored:
            if item.get("pinned"):
                selected.append(item)
                kind_counts[str(item.get("kind"))] += 1
            if len(selected) >= limit:
                return selected[:limit]

        seen = {item["id"] for item in selected}
        for item in scored:
            if item["id"] in seen:
                continue
            kind = str(item.get("kind"))
            if kind_counts[kind] >= max_per_kind and len(selected) < limit - 2:
                continue
            selected.append(item)
            seen.add(item["id"])
            kind_counts[kind] += 1
            if len(selected) >= limit:
                break
        return selected

    def _normalize_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        content = self._entry_content(entry)
        tags = [str(tag) for tag in entry.get("tags", [])]
        title = str(entry.get("title") or "")
        return {
            **entry,
            "id": str(entry.get("id") or ""),
            "kind": str(entry.get("kind") or "memory"),
            "title": title,
            "content": content,
            "tags": tags,
            "scope": str(entry.get("scope") or "conversation"),
            "importance": float(entry.get("importance") or entry.get("weight") or 1.0),
            "pinned": bool(entry.get("pinned")),
            "sourcePath": str(entry.get("sourcePath") or ""),
            "searchText": "\n".join([title, content, " ".join(tags), str(entry.get("sourcePath") or "")]),
        }

    def _entry_content(self, entry: dict[str, Any]) -> str:
        return str(entry.get("content") or "").strip()

    def _reason(self, signals: dict[str, float]) -> str:
        ranked = sorted(((key, value) for key, value in signals.items() if value > 0), key=lambda item: item[1], reverse=True)
        labels = {
            "bm25": "文本相关",
            "phrase": "短语命中",
            "path": "路径命中",
            "kind": "类型优先",
            "importance": "重要性高",
            "recency": "近期记忆",
            "pinned": "已置顶",
            "longTerm": "长期记忆",
            "tag": "标签命中",
        }
        return "、".join(labels.get(key, key) for key, _ in ranked[:3]) or "综合排序"

    def _to_recall_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item["id"],
            "kind": item["kind"],
            "title": item["title"],
            "content": item["content"][-1600:],
            "score": round(float(item["score"]), 3),
            "sourcePath": item["sourcePath"],
            "tags": item.get("tags", []),
            "createdAt": item.get("createdAt"),
            "scope": item.get("scope", "conversation"),
            "importance": round(float(item.get("importance") or 1.0), 3),
            "pinned": bool(item.get("pinned")),
            "reason": item.get("reason", ""),
            "matchSignals": item.get("matchSignals", {}),
        }

    def _empty(self, query: str, candidate_count: int) -> dict[str, Any]:
        return {
            "query": query,
            "strategy": "bm25+phrase+path+symbol+importance+recency+pin+diversity",
            "candidateCount": candidate_count,
            "items": [],
        }
