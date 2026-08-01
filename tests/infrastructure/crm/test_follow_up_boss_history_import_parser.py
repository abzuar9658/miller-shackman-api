from app.infrastructure.crm.follow_up_boss.history_import_parser import (
    parse_fub_people_response,
)


def test_people_response_maps_matching_lead_text_summaries_and_deduplicates() -> None:
    payload = {
        "people": [
            {
                "id": 12456,
                "lastTextDate": "2026-07-20T22:57:13Z",
                "lastReceivedTextBody": "Can we see it?",
                "lastReceivedTextId": 101,
                "lastSentTextBody": "When are you available?",
                "lastSentTextId": 102,
                "lastTextBody": "When are you available?",
                "lastTextId": 102,
                "lastSentTextUser": "Marc Kalman",
            },
            {"id": 99999, "lastReceivedTextBody": "must not import"},
        ]
    }

    events = parse_fub_people_response(payload, "12456", "https://fub.test/api/v1/people")

    assert len(events) == 2
    assert {event.external_activity_id for event in events} == {"101", "102"}
    assert {event.direction.value for event in events if event.direction} == {"inbound", "outbound"}
    assert all(event.details["source"] == "fub_people_response" for event in events)


def test_people_response_supports_structured_history_collections() -> None:
    payload = {
        "people": [{"id": "12456"}],
        "events": [
            {
                "id": "event-1",
                "type": "note",
                "content": "Agent note",
                "occurredAt": "2026-07-21T12:00:00Z",
            }
        ],
    }

    events = parse_fub_people_response(payload, "12456")

    assert len(events) == 1
    assert events[0].external_activity_id == "event-1"
    assert events[0].activity_type == "note"


def test_people_response_maps_marketing_text_body_from_real_people_shape() -> None:
    payload = {
        "people": [
            {
                "id": 12456,
                "lastReceivedMarketingText": "2026-07-20T23:50:12Z",
                "lastReceivedMarketingTextBody": "Marketing message",
                "lastReceivedMarketingTextId": 5678,
            }
        ]
    }

    events = parse_fub_people_response(payload, "12456")

    assert len(events) == 1
    assert events[0].activity_type == "marketing_text"
    assert events[0].external_activity_id == "5678"
