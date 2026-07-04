"""Integration test: verify LLM connection is working."""

from dotenv import load_dotenv

load_dotenv(".env.local")

from noval_workflow.llm import get_llm  # noqa: E402


def test_llm_hello():
    llm = get_llm()
    response = llm.invoke("Say hello in one sentence.")
    print("\nLLM response:", response.content)
    assert response.content
