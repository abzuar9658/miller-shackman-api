from app.main import create_app


def test_outbound_send_exception_list_and_detail_routes_are_registered() -> None:
    paths = set(create_app().openapi()["paths"])

    assert "/api/v1/workspaces/{workspace_id}/outbound-send-exceptions" in paths
    assert (
        "/api/v1/workspaces/{workspace_id}/outbound-send-exceptions/{request_id}"
        in paths
    )