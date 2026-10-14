import pytest

from copilot.config import ConfigError, load_settings


def test_defaults_when_nothing_is_set():
    settings = load_settings({})
    assert settings.database_url is None
    assert settings.openai_api_key is None
    assert settings.db_prepared_statements is True
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.embedding_dimensions == 1536


def test_values_come_from_the_environment():
    settings = load_settings(
        {
            "DATABASE_URL": " postgresql:///copilot_dev ",
            "OPENAI_API_KEY": "sk-test",
            "DB_PREPARED_STATEMENTS": "false",
            "EMBEDDING_MODEL": "other-model",
            "EMBEDDING_DIMENSIONS": "256",
        }
    )
    assert settings.database_url == "postgresql:///copilot_dev"
    assert settings.openai_api_key == "sk-test"
    assert settings.db_prepared_statements is False
    assert settings.embedding_model == "other-model"
    assert settings.embedding_dimensions == 256


def test_empty_values_count_as_not_set():
    settings = load_settings({"DATABASE_URL": "", "OPENAI_API_KEY": "  ", "EMBEDDING_MODEL": ""})
    assert settings.database_url is None
    assert settings.openai_api_key is None
    assert settings.embedding_model == "text-embedding-3-small"


@pytest.mark.parametrize("value", ["TRUE", "1", "yes", "On"])
def test_flag_true_forms(value):
    assert load_settings({"DB_PREPARED_STATEMENTS": value}).db_prepared_statements is True


@pytest.mark.parametrize("value", ["false", "0", "No", "OFF"])
def test_flag_false_forms(value):
    assert load_settings({"DB_PREPARED_STATEMENTS": value}).db_prepared_statements is False


def test_flag_that_is_neither():
    with pytest.raises(ConfigError, match="DB_PREPARED_STATEMENTS"):
        load_settings({"DB_PREPARED_STATEMENTS": "maybe"})


@pytest.mark.parametrize("value", ["0", "-5", "1.5", "big"])
def test_dimensions_must_be_a_positive_whole_number(value):
    with pytest.raises(ConfigError, match="EMBEDDING_DIMENSIONS"):
        load_settings({"EMBEDDING_DIMENSIONS": value})


# Pipeline settings


def test_pipeline_defaults():
    settings = load_settings({})
    assert settings.strong_model is None
    assert settings.cheap_model is None
    assert settings.max_attempts == 3
    assert settings.rerank_keep == 10
    assert settings.search_limit == 30
    assert settings.strong_price_in is None


def test_pipeline_values_come_from_the_environment():
    settings = load_settings(
        {
            "STRONG_MODEL": "strong-id",
            "CHEAP_MODEL": "cheap-id",
            "MAX_ATTEMPTS": "2",
            "RERANK_KEEP": "8",
            "MAX_REQUEST_CHARS": "500",
            "STRONG_PRICE_IN": "2.5",
            "STRONG_PRICE_OUT": "10",
        }
    )
    assert (settings.strong_model, settings.cheap_model) == ("strong-id", "cheap-id")
    assert settings.max_attempts == 2
    assert settings.rerank_keep == 8
    assert settings.max_request_chars == 500
    assert (settings.strong_price_in, settings.strong_price_out) == (2.5, 10.0)
    assert settings.cheap_price_in is None


@pytest.mark.parametrize("value", ["cheap", "-1"])
def test_price_must_be_a_number_not_below_zero(value):
    with pytest.raises(ConfigError, match="STRONG_PRICE_IN"):
        load_settings({"STRONG_PRICE_IN": value})


def test_max_attempts_must_be_at_least_one():
    with pytest.raises(ConfigError, match="MAX_ATTEMPTS"):
        load_settings({"MAX_ATTEMPTS": "0"})
