from packaging import version as packaging_version
from importlib.metadata import version as importlib_version

ecal_version = packaging_version.parse(importlib_version("ecal"))

if ecal_version.major == 5:
    from .middleware_ecal5 import Monitoring, Publisher, Subscriber
elif ecal_version.major == 6:
    from .middleware_ecal6 import Monitoring, Publisher, Subscriber
else:
    raise ImportError(f"Unsupported eCAL version {ecal_version}. Supported versions are 5.x and 6.x.")

from .middleware import MonitoringListener

__all__ = ["Monitoring", "Publisher", "Subscriber", "MonitoringListener"]