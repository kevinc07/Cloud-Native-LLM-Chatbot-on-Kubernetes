def test_deliberate_failure():
    assert 1 + 1 == 3, "demo: this failing test must block the build stage"
