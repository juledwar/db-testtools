from .test_pgfixture import TestPostgresContainer

# Override the scenarios to only run Docker
TestPostgresContainer.scenarios = [
    ("docker", {"podman": False}),
]

# Optional: re-export the test class to make unittest discovery happy
__all__ = ["TestPostgresContainer"]
