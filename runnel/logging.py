import datetime
import logging
import logging.config
import os
from io import StringIO
from typing import Dict

import colorama
import structlog

from runnel.context import executor_id, partition_id, stream, worker_id


def init_logging(level="debug", format="console"):
    level = level.upper()

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": True,
        "formatters": {
            "standard": {
                "format": "%(message)s"
            }
        },
        "handlers": {
            "default": {
                "level": level,
                "formatter": "standard",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            }
        },
        "loggers": {
            "": {
                "handlers": ["default"],
                "level": level,
            },
            "runnel": {
                "handlers": ["default"],
                "level": level,
                "propagate": False,
            },
        },
    })

    structlog.configure(
        logger_factory=logging.getLogger,
        processors=[
            _add_meta,
            structlog.stdlib.filter_by_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer() if format == "json" else _renderer,
        ],
    )


def _add_meta(logger: str, method_name: str, event_dict: Dict) -> Dict:
    event_dict = {
        "event": event_dict.pop("event"),
        "exc_info": event_dict.pop("exc_info", None),
        "extra": event_dict,
    }

    if not event_dict["extra"]:
        event_dict.pop("extra")

    event_dict["timestamp"] = datetime.datetime.utcnow().isoformat() + "Z"
    event_dict["level"] = method_name.upper()
    event_dict["pid"] = os.getpid()
    event_dict["worker_id"] = worker_id.get()
    event_dict["executor_id"] = executor_id.get()
    event_dict["stream"] = stream.get()
    event_dict["partition_id"] = partition_id.get()
    return event_dict


reset = colorama.Style.RESET_ALL
bright = colorama.Style.BRIGHT
dim = colorama.Style.DIM

red = colorama.Fore.RED
yellow = colorama.Fore.YELLOW
blue = colorama.Fore.BLUE
green = colorama.Fore.GREEN

colours = {
    "CRITICAL": red + bright,
    "EXCEPTION": red + bright,
    "ERROR": red + bright,
    "WARNING": yellow + bright,
    "INFO": green + bright,
    "DEBUG": blue + bright,
}


def _renderer(logger: str, method_name: str, event_dict: Dict) -> str:
    s = StringIO()

    ts = event_dict.pop("timestamp", None)
    if ts:
        s.write(f"{reset}{dim}{str(ts)}{reset} ")

    level = event_dict.pop("level", None)
    if level:
        s.write(f"{colours[level]}{level:>9}{reset} ")

    event = event_dict.pop("event")
    s.write(f"{bright}{event:<17}{reset} ")

    worker_id = event_dict.pop("worker_id", None)
    if worker_id:
        s.write(f"{blue}worker_id{reset}={worker_id} ")

    executor_id = event_dict.pop("executor_id", None)
    if executor_id:
        s.write(f"{blue}executor_id{reset}={executor_id} ")

    stream = event_dict.pop("stream", None)
    partition_id = event_dict.pop("partition_id", None)
    suffix = f"-{partition_id}" if partition_id is not None else ""
    if stream:
        s.write(f"{blue}stream{reset}={stream+suffix} ")

    for key, value in event_dict.pop("extra", {}).items():
        s.write(f"{blue}{key}{reset}={value}{reset} ")

    stack = event_dict.pop("stack", None)
    exc = event_dict.pop("exception", None)

    if stack is not None:
        s.write("\n" + stack)
        if exc is not None:
            s.write("\n\n" + "=" * 88 + "\n")
    if exc is not None:
        s.write("\n" + exc)

    return s.getvalue()
