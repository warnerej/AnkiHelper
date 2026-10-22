import pytest

from app.ratelimit import reset_all


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    reset_all()
    yield
