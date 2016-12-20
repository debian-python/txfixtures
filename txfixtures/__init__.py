from pbr.version import VersionInfo

from extras import try_import

from .reactor import (
    Reactor,
)
from .service import Service

# Since the PhantomJS fixure requires the Selenium Python package, we make
# the import fail gracefully if it's not installed.
PhantomJS = try_import("txfixtures.phantomjs.PhantomJS")

__all__ = [
    "Reactor",
    "Service",
    "PhantomJS",
]

_v = VersionInfo("txfixtures").semantic_version()
__version__ = _v.release_string()
version_info = _v.version_tuple()
