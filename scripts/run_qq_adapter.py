"""Run the QQ OneBot adapter service."""

from __future__ import annotations

import logging
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from aiops.qq_adapter import AdapterConfig, create_adapter_app, load_runtime_env


def main() -> None:
    load_runtime_env()
    logging.basicConfig(
        level=os.getenv("QQ_ADAPTER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app = create_adapter_app(AdapterConfig.from_env())
    host = os.getenv("QQ_ADAPTER_HOST", "0.0.0.0")
    port = int(os.getenv("QQ_ADAPTER_PORT", "18088"))
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    main()
