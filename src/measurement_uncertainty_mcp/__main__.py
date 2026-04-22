"""CLI entry point — starts the stdio MCP server."""
import asyncio
import logging
import sys

from .server import run


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
