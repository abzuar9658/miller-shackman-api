import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live-llm",
        action="store_true",
        default=False,
        help="run tests marked live_llm against the configured external LLM provider",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    if config.getoption("--run-live-llm"):
        return
    skip_live_llm = pytest.mark.skip(
        reason="live LLM tests require the explicit --run-live-llm flag"
    )
    for item in items:
        if "live_llm" in item.keywords:
            item.add_marker(skip_live_llm)
