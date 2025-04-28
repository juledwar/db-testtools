from .test_pgfixture import TestPostgresContainer

# Override the scenarios to only run Podman
TestPostgresContainer.scenarios = [
    ("podman", {"podman": True}),
]

# Optional: re-export the test class to make unittest discovery happy
__all__ = ["TestPostgresContainer"]
