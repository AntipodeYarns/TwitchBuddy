from twitchbuddy import greet


def test_greet():
    assert greet("World") == "Hello, World!"


def test_greet_empty():
    try:
        greet("")
        assert False, "Expected ValueError"
    except ValueError:
        assert True
