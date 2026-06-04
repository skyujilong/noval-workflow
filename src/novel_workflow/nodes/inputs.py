"""Phase 0: Collect user inputs."""

from __future__ import annotations

from langgraph.types import interrupt

from noval_workflow.state import NovelState


def collect_user_inputs(state: NovelState) -> dict:
    """Interrupt to collect the 6 basic novel parameters from the user."""
    # Allow pre-populated values via thread input (langgraph dev API)
    if (
        state.genre
        and state.writing_style
        and state.target_audience
        and state.core_tone
        and state.chapter_word_count
        and state.total_word_count
    ):
        return {}

    answers = interrupt(
        {
            "message": "请提供以下小说创作参数：",
            "fields": {
                "genre": "小说类型（如：玄幻、都市、悬疑、言情等）",
                "writing_style": "写作风格（如：硬核、轻松、意识流、简洁白描等）",
                "target_audience": "目标读者（如：青少年、成年男性、职场女性等）",
                "core_tone": "核心基调（如：热血励志、压抑沉重、温馨治愈等）",
                "chapter_word_count": "每章字数目标（如：3000字、5000字）",
                "total_word_count": "总字数目标（如：30万字、100万字）",
            },
            "current_values": {
                "genre": state.genre,
                "writing_style": state.writing_style,
                "target_audience": state.target_audience,
                "core_tone": state.core_tone,
                "chapter_word_count": state.chapter_word_count,
                "total_word_count": state.total_word_count,
            },
        }
    )

    VALID_FIELDS = frozenset({
        "genre", "writing_style", "target_audience",
        "core_tone", "chapter_word_count", "total_word_count",
    })

    if isinstance(answers, dict):
        result = {k: str(v) for k, v in answers.items() if k in VALID_FIELDS}
        if result:
            return result

    # Non-dict or empty dict: re-interrupt with error guidance
    return interrupt({
        "error": "请提供一个包含所有必填字段的 dict 作为回答。",
        "required_fields": list(VALID_FIELDS),
        "received": str(answers),
    })
