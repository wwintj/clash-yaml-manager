from pathlib import Path
import shutil
import subprocess
import pytest


def test_draft_policy_contract_with_real_node():
    node=shutil.which('node')
    if not node:pytest.skip('Node required for local draft contract')
    subprocess.run([node,str(Path(__file__).with_suffix('.js'))],check=True,timeout=15)
