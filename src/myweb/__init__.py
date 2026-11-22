"""Build, author and deploy my web sites from a datalad dataset of org sources."""

__version__ = "0.1.0"


def main() -> None:
    from .cli import main as _main

    _main()
