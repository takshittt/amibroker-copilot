import psycopg
from psycopg.rows import dict_row

from copilot.admin import main

from .conftest import sign_up


def test_reset_password(client, api_database_url, capsys):
    sign_up(client, "trader@example.in", "the old passphrase")
    with psycopg.connect(api_database_url, row_factory=dict_row) as conn:
        assert main(["reset-password", "TRADER@example.in"], conn=conn) == 0
    out = capsys.readouterr().out
    new_password = out.split(": ", 1)[1].splitlines()[0]
    assert len(new_password) >= 20

    old = client.post(
        "/v1/auth/login", json={"email": "trader@example.in", "password": "the old passphrase"}
    )
    assert old.status_code == 401
    new = client.post(
        "/v1/auth/login", json={"email": "trader@example.in", "password": new_password}
    )
    assert new.status_code == 200


def test_reset_password_for_an_unknown_email(api_database_url, capsys):
    with psycopg.connect(api_database_url, row_factory=dict_row) as conn:
        assert main(["reset-password", "nobody@example.in"], conn=conn) == 1
    assert "No account" in capsys.readouterr().err
