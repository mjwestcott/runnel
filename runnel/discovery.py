import importlib
from pathlib import Path

import structlog

logger = structlog.get_logger()


def autodiscover(app, basedir=None):
    """
    Automatically import Python modules matching the pattern in
    :attr:`runnel.settings.Settings.autodiscover`. If the pattern is None or "" then
    autodiscovery will be skipped.

    This is necessary because processors and tasks are registered with apps via
    decorators. When the worker process starts up, these decorators must be executed so
    that the app knows they exist.

    Parameters
    ----------
    app : runnel.App
        The app instance for which to discover processors and tasks.
    basedir : str
        The directory relative to which we will search the filesystem.
    """
    pattern = app.settings.autodiscover  # e.g. "myproj/**/streams.py"

    if pattern:
        for filename in Path(basedir or Path('.')).glob(pattern):
            module = ".".join(filename.parts)[:-3]
            logger.debug("discovered", module=module)
            importlib.import_module(module)
