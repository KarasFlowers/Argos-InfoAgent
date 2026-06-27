from app.models.domain import ModelApiConfig, mask_secret


def test_mask_secret_handles_empty_and_short_values():
    assert mask_secret("") == ""
    assert mask_secret(None) == ""
    assert mask_secret("short") == "***"


def test_mask_secret_preserves_edges_for_long_values():
    assert mask_secret("sk-abcdefghijklmnopqrstuvwxyz") == "sk-a...wxyz"


def test_model_api_config_safe_dict_masks_api_key():
    config = ModelApiConfig(
        name="default",
        base_url="https://api.example.com/v1",
        api_key="sk-secret-provider-key",
        model_name="example-model",
    )

    payload = config.safe_dict()

    assert payload["api_key"] == "sk-s...-key"
    assert "sk-secret-provider-key" not in str(payload)
    assert payload["name"] == "default"
    assert payload["model_name"] == "example-model"
