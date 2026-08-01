from scripts._agent_wipe_leads import _delete_models


def test_delete_models_include_lead_children_in_dependency_order() -> None:
    table_names = [model.__tablename__ for model in _delete_models()]

    expected_tables = {
        "customer_timing_candidates",
        "lead_classification_artifacts",
        "lead_paused_search_history",
        "lead_routing_reviews",
        "paused_search_occurrences",
        "paused_search_reviews",
    }
    assert expected_tables <= set(table_names)

    assert table_names.index("lead_routing_reviews") < table_names.index(
        "lead_classification_artifacts"
    )
    assert table_names.index("paused_search_occurrences") < table_names.index("lead_workflows")
    assert table_names.index("paused_search_reviews") < table_names.index("outbound_messages")
    assert table_names.index("customer_timing_candidates") < table_names.index("leads")