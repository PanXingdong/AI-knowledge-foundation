from agent_knowledge_hub.llm_agent import LLMAgent


def test_synthesize_includes_history(monkeypatch):
    captured: dict[str, object] = {}

    def fake_call_deepseek(messages, api_key, model, timeout):
        captured["messages"] = messages
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
