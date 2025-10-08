# Copyright (c) Continental. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for details.

from packaging import version as packaging_version
from importlib.metadata import version as importlib_version

#TODO: need to find a compatible way to check the ecal version!
ecal_version = packaging_version.parse(importlib_version("eclipse_ecal"))

if ecal_version.major == 5:
    from .middleware_ecal5 import MiddlewareContext, Monitoring, Publisher, Subscriber, MIDDLEWARE_VERSION
elif ecal_version.major == 6:
    from .middleware_ecal6 import MiddlewareContext, Monitoring, Publisher, Subscriber, MIDDLEWARE_VERSION
else:
    raise ImportError(f"Unsupported eCAL version {ecal_version}. Supported versions are 5.x and 6.x.")

from .middleware import MonitoringListener

__all__ = ["MiddlewareContext", "Monitoring", "Publisher", "Subscriber", "MonitoringListener", "MIDDLEWARE_VERSION"]