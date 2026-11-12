"""Core imports do not require installing aiohttp."""
import subprocess
import sys


def test_sync_import_and_explicit_optional_dependency_error():
    code = """
import sys
import importlib.abc
class BlockAsync(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'aiohttp' or fullname.startswith('aiohttp.'):
            raise ImportError('blocked optional dependency')
sys.meta_path.insert(0, BlockAsync())
import redfish_sdk
assert 'aiohttp' not in sys.modules
try:
    redfish_sdk.AsyncRedfishClient('example.test', 'test', 'test', session=object())
except ImportError as error:
    assert '[async]' in str(error)
else:
    raise AssertionError('Expected optional dependency error')
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
