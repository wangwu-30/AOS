import json


def generate_telegram_webhook_fixture(
    update_id: int = 1000, 
    message_id: int = 200,
    chat_id: int = 12345,
    user_id: int = 555,
    text: str = "Hello Assistant",
    budget: int = 5
) -> str:
    """
    Generates a standard JSON string representing a Telegram Webhook payload.
    This fixture is used by THREAD-033/035 (PA-EV1/PA-MTR0) downstream integration tests
    to simulate payloads originating from THREAD-034 (PA-CH1).
    """
    payload = {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "date": 1600000000,
            "chat": {
                "id": chat_id, 
                "type": "private"
            },
            "from": {
                "id": user_id, 
                "is_bot": False, 
                "first_name": "FixtureUser"
            },
            "text": text
        }
    }
    return json.dumps(payload)

def generate_telegram_webhook_malformed_fixture() -> str:
    """
    Generates a malformed JSON payload designed to trigger PA-CH1's E_CHANNEL_PAYLOAD_INVALID.
    """
    return '{ "update_id": 999, "message": '

def generate_secret_token_fixture() -> str:
    """
    Standard secret token expected by the tests.
    """
    return "secret-token-fixture-12345"
