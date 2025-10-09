# Copyright 2025 AUMOVIO and subsidiaries. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for details.

from packaging import version as packaging_version
from importlib.metadata import version as importlib_version, PackageNotFoundError

def get_ecal_version():
    try:
        # New package name (ecal >= 6)
        return packaging_version.parse(importlib_version("eclipse_ecal"))
    except PackageNotFoundError:
        try:
            # Old package name (ecal < 6)
            return packaging_version.parse(importlib_version("ecal5"))
        except PackageNotFoundError:
            raise ImportError(
                "Neither 'ecal5' (eCAL < 6) nor 'eclipse_ecal' (eCAL >= 6) is installed. "
                "Please install one of them."
            )

ecal_version = get_ecal_version()

if ecal_version.major == 5:
    from .middleware_ecal5 import MiddlewareContext, Monitoring, Publisher, Subscriber, MIDDLEWARE_VERSION
elif ecal_version.major == 6:
    from .middleware_ecal6 import MiddlewareContext, Monitoring, Publisher, Subscriber, MIDDLEWARE_VERSION
else:
    raise ImportError(f"Unsupported eCAL version {ecal_version}. Supported versions are 5.x and 6.x.")

from .middleware import MonitoringListener

__all__ = ["MiddlewareContext", "Monitoring", "Publisher", "Subscriber", "MonitoringListener", "MIDDLEWARE_VERSION"]