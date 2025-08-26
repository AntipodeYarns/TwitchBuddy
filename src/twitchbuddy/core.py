def greet(name: str) -> str:
    """Return a greeting string for `name`."""
    if not name:
        raise ValueError("name must be non-empty")
    return f"Hello, {name}!"
