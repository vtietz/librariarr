from __future__ import annotations

import argparse
import logging

from .config import load_config
from .service import LibrariArrService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LibrariArr: nested media folders -> flat Arr symlink roots (Radarr/Sonarr)"
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING, ERROR")
    parser.add_argument("--once", action="store_true", help="Run one reconcile cycle and exit")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    config = load_config(args.config)
    service = LibrariArrService(config)
    if args.once:
        service.reconcile()
        return
    service.run()


if __name__ == "__main__":
    main()
