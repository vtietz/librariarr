from __future__ import annotations

from .bootstrap import ServiceBootstrapMixin
from .matching import ServiceMatchingMixin
from .preflight import ServicePreflightMixin
from .reconcile import ServiceReconcileMixin
from .scope import ServiceScopeMixin


class LibrariArrService(
    ServiceBootstrapMixin,
    ServicePreflightMixin,
    ServiceScopeMixin,
    ServiceReconcileMixin,
    ServiceMatchingMixin,
):
    pass


__all__ = ["LibrariArrService"]
