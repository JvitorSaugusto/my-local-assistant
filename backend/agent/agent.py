from typing import cast
from langchain_core.language_models import BaseChatModel
from langchain.chat_models import init_chat_model


def load_llm() -> BaseChatModel:
    model = cast(
        "BaseChatModel",
        init_chat_model(
            model="gpt-oss:20b",
            model_provider="ollama",
            temperature=0.2,
            configurable_fields=("model", "model_provider", "temperature", "max_tokens"),
        ),
    )

    assert hasattr(model, "bind_tools")
    assert hasattr(model, "invoke")
    assert hasattr(model, "with_config")

    return model