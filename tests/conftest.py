import pytest
from api import Api

api = Api(
    headers={
        "User-Agent": f"Knew Karma/Testing "
        f"(PyTest {pytest.__version__}; +https://github.com/knewkarma-io/api)"
    }
)

TEST_USERNAME: str = "AutoModerator"
TEST_SUBREDDIT_1: str = "AskScience"
TEST_SUBREDDIT_2: str = "AskReddit"
