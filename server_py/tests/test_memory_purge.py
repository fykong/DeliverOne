import json

from server_py.memory.long_term_store import LongTermMemoryStore
from server_py.memory.pattern_store import MemoryPatternStore


def test_long_term_purge_removes_only_target_conversation(tmp_path):
    path = tmp_path / "long-term.json"
    path.write_text(
        json.dumps(
            [
                {"id": "a", "conversationId": "conv_bad", "content": "幻觉路径 ArticleCard 不存在"},
                {"id": "b", "conversationId": "conv_good", "content": "真实方案"},
            ]
        ),
        encoding="utf-8",
    )
    store = LongTermMemoryStore.__new__(LongTermMemoryStore)
    store.path = path
    removed = store.purge_conversation("conv_bad")
    assert removed == 1
    remaining = json.loads(path.read_text(encoding="utf-8"))
    assert [item["id"] for item in remaining] == ["b"]


def test_pattern_purge_trims_examples_but_keeps_multi_source_patterns(tmp_path):
    path = tmp_path / "patterns.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "p1",
                    "conversationId": "conv_bad",
                    "examples": [{"conversationId": "conv_bad"}],
                },
                {
                    "id": "p2",
                    "conversationId": "conv_bad",
                    "examples": [{"conversationId": "conv_bad"}, {"conversationId": "conv_good"}],
                },
            ]
        ),
        encoding="utf-8",
    )
    store = MemoryPatternStore.__new__(MemoryPatternStore)
    store.path = path
    removed = store.purge_conversation("conv_bad")
    assert removed == 1  # p1 整条删;p2 保留但摘掉 conv_bad 的例证
    remaining = json.loads(path.read_text(encoding="utf-8"))
    assert [item["id"] for item in remaining] == ["p2"]
    assert remaining[0]["examples"] == [{"conversationId": "conv_good"}]
