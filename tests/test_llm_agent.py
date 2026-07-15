from agent_knowledge_hub.llm_agent import LLMAgent


def test_synthesize_includes_history(monkeypatch):
    captured: dict[str, object] = {}

    def fake_call_deepseek(messages, api_key, model, timeout, temperature=0.3):
        captured["messages"] = messages
        captured["temperature"] = temperature
        return "合成回答"

    monkeypatch.setattr("agent_knowledge_hub.llm_agent._call_deepseek", fake_call_deepseek)
    agent = LLMAgent(api_key="test-key", model="test-model")

    result = agent.synthesize(
        "继续说明",
        "参考资料",
        history=[
            {"role": "user", "content": "上一个问题"},
            {"role": "assistant", "content": "上一轮回答"},
        ],
    )

    messages = captured["messages"]
    assert result == "合成回答"
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "上一个问题"}
    assert messages[2] == {"role": "assistant", "content": "上一轮回答"}
    assert "继续说明" in messages[-1]["content"]
    assert "只输出一个 JSON 对象" in messages[-1]["content"]
    assert '"summary"' in messages[-1]["content"]
    assert '"confidence"' in messages[-1]["content"]
    assert '"solution"' in messages[-1]["content"]
    assert "solution_design" in messages[-1]["content"]
    assert "span_xxx" not in messages[-1]["content"]
    assert "evidence_ids 必须始终写空数组 []" in messages[-1]["content"]
    assert captured["temperature"] == 0.0


def test_direct_reply_keeps_nonzero_temperature(monkeypatch):
    captured: dict[str, object] = {}

    def fake_call_deepseek(messages, api_key, model, timeout, temperature=0.3):
        captured["temperature"] = temperature
        return "你好"

    monkeypatch.setattr("agent_knowledge_hub.llm_agent._call_deepseek", fake_call_deepseek)
    agent = LLMAgent(api_key="test-key", model="test-model")

    assert agent.direct_reply("你好") == "你好"
    assert captured["temperature"] == 0.3


def test_synthesize_failure_returns_safe_message_not_context_pack(monkeypatch):
    def fake_call_deepseek(messages, api_key, model, timeout, temperature=0.3):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr("agent_knowledge_hub.llm_agent._call_deepseek", fake_call_deepseek)
    agent = LLMAgent(api_key="test-key", model="test-model")

    result = agent.synthesize("技术问题", "### Evidence 1\nScore: -18\nspan_xxx")

    assert "模型生成失败" in result
    assert "Evidence" not in result
    assert "Score" not in result
    assert "span_xxx" not in result
