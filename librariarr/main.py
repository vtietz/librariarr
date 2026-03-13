from __future__ import annotations

import argparse
import logging
import os

from .config import load_config
from .service import LibrariArrService
from .web import run_web_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LibrariArr: nested media folders -> flat Arr symlink roots (Radarr/Sonarr)"
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING, ERROR")
    parser.add_argument("--once", action="store_true", help="Run one reconcile cycle and exit")
    parser.add_argument(
        "--web",
        action="store_true",
        help="Run embedded web UI and API server",
    )
    parser.add_argument(
        "--web-host",
        default=os.getenv("LIBRARIARR_WEB_HOST", "0.0.0.0"),
        help="Web server host",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=int(os.getenv("LIBRARIARR_WEB_PORT", "8787")),
        help="Web server port",
    )
    parser.add_argument(
        "--web-no-runtime",
        action="store_true",
        help="Run web API/UI without starting the background reconcile loop",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    if args.web:
        run_web_app(
            config_path=args.config,
            host=args.web_host,
            port=args.web_port,
            log_level=args.log_level,
            run_runtime_loop=not args.web_no_runtime,
        )
        return

    config = load_config(args.config)
    service = LibrariArrService(config)
    if args.once:
        service.reconcile()
        return
    service.run()


if __name__ == "__main__":
    main()
