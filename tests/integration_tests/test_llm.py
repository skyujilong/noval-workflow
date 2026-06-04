"""Integration test: verify LLM connection is working."""

from dotenv import load_dotenv

load_dotenv(".env.local")

from src.novel_workflow.nodes import _get_llm  # noqa: E402


def test_llm_hello():
    llm = _get_llm(None)
    response = llm.invoke("Say hello in one sentence.")
    print("\nLLM response:", response.content)
    assert response.content
