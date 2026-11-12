"""Both clients work without any additional HTTP dependency."""
import subprocess
import sys


def test_async_client_works_without_aiohttp():
    code = """
import sys
import importlib.abc
class BlockAsync(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'aiohttp' or fullname.startswith('aiohttp.'):
            raise ImportError('blocked optional dependency')
sys.meta_path.insert(0, BlockAsync())
import redfish_sdk
import asyncio
import requests
from unittest.mock import Mock
assert 'aiohttp' not in sys.modules
async def main():
    with requests.Session() as session:
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"ok": true}'
        session.request = Mock(return_value=response)
        async with redfish_sdk.AsyncRedfishClient('example.test', 'test', 'test',
                session=session, auth_mode=redfish_sdk.AuthenticationMode.BASIC) as client:
            assert (await client.get('/redfish/v1/'))['ok'] is True
asyncio.run(main())
assert 'aiohttp' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
