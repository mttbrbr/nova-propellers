"""Reusable immutable scientific cases, independent of machine integrations."""
import copy
from pathlib import Path

from nova.adapters.base import AdapterConfiguration
from nova.adapters.pywake import PyWakeAdapter
from nova.core.data import canonical_json, content_hash
from nova.infrastructure import library

MAX_CASE_BYTES = 1_000_000


def save_case(name, case, *, notes='', demonstration=False):
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValueError('Case name must contain 1–120 characters')
    if not isinstance(notes, str) or len(notes) > 800 or type(demonstration) is not bool:
        raise ValueError('Invalid case notes or demonstration flag')
    # This placeholder is never resolved or invoked. Validation only checks the
    # adapter environment kind and numerical case, without probing an installation.
    configuration = AdapterConfiguration(Path('unused-python-validation-only'), 'python_environment')
    if len(canonical_json(case).encode('utf-8')) > MAX_CASE_BYTES:
        raise ValueError('Saved PyWake cases are limited to 1 MB')
    PyWakeAdapter().validate(case, configuration)
    frozen = copy.deepcopy(case)
    return library.make_asset({'kind': 'external_case', 'adapter_id': 'pywake', 'name': name,
                               'case': frozen, 'notes': notes, 'demonstration': demonstration,
                               'case_hash': content_hash(frozen), 'source_origin': 'user_saved'})


def list_cases():
    return [asset for asset in library.list_records('asset')
            if asset.get('kind') == 'external_case' and asset.get('adapter_id') == 'pywake']


def get_case(id):
    asset = library.get('asset', id)
    if asset.get('kind') != 'external_case' or asset.get('adapter_id') != 'pywake':
        raise KeyError(id)
    return asset
