"""Deliberate registration only; no arbitrary plugin code loading."""
import re
import threading
from dataclasses import asdict

from nova.adapters.base import ExternalAdapter

_adapters = {}
_builtins_loaded = False
_registry_lock = threading.RLock()


def ensure_builtins():
    """Load NOVA integration code, never import optional scientific packages."""
    global _builtins_loaded
    with _registry_lock:
        if not _builtins_loaded:
            from nova.adapters.openfast import OpenFASTAdapter
            from nova.adapters.pywake import PyWakeAdapter
            register(PyWakeAdapter())
            register(OpenFASTAdapter())
            _builtins_loaded = True


def register(adapter: ExternalAdapter):
    descriptor = adapter.describe()
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', descriptor.id) or descriptor.id in _adapters:
        raise ValueError('Adapter ID must be unique and nonempty')
    _adapters[descriptor.id] = adapter


def unregister(id):
    _adapters.pop(id, None)


def get(id):
    ensure_builtins()
    return _adapters[id]


def descriptors():
    ensure_builtins()
    return [asdict(adapter.describe()) for adapter in _adapters.values()]
