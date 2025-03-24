import argparse
import asyncio
from pathlib import Path


from package.download import QueryClient


class DownloadArgs:
    key_path: Path
    cache_dir: Path
    retry_failed: bool
    debug: bool


async def main(args: DownloadArgs):
    async with QueryClient(args.key_path, args.cache_dir, args.retry_failed, debug=args.debug) as client:
        try:
            await client.update_apps()
        except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download Altinn apps")
    parser.add_argument(
        "--retry-failed",
        help="Retry downloading apps that previously failed",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--cache-dir",
        help="Where to store downloaded apps",
        type=Path,
        default="./data",
    )
    parser.add_argument(
        "--key-path",
        help="Location of Altinn Studio key file",
        type=Path,
        default="./keys.json",
    )
    parser.add_argument(
        "--debug",
        help="Enable debug logging",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    args = parser.parse_args(namespace=DownloadArgs())
    asyncio.run(main(args))
