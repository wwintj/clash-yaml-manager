import re

from conftest import ROOT
from core.version import read_version


def test_readme_latest_stable_matches_version():
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    markers = re.findall(
        r'<!-- RELEASE:START -->(.*?)<!-- RELEASE:END -->', readme, re.DOTALL
    )
    tag = 'v' + read_version(ROOT / 'VERSION')
    assert markers == [
        f'\n**Latest Stable: [{tag}]'
        f'(https://github.com/wwintj/clash-yaml-manager/releases/tag/{tag})**\n'
    ]
    for line in readme.splitlines():
        if re.search(r'\b(?:hysteria2|hy2)\b', line, re.IGNORECASE):
            assert not re.search(
                r'\b(?:main[- ]only|unreleased)\b|[僅仅]在\s*main|'
                r'尚未(?:[發发]布|包含在\s*Stable)', line, re.IGNORECASE
            ), line


def test_current_hysteria2_contract_has_released_status():
    # Only the current status introduction; historical reports remain historical.
    intro = (ROOT / 'docs/HYSTERIA2_PROTOCOL.md').read_text(encoding='utf-8').split('\n## ', 1)[0]
    status = ' '.join(intro.replace('*', '').replace('`', '').lower().split())
    assert 'frozen' in status
    # The input subset first shipped in v1.4.0; metadata-only patch releases do
    # not require this contract to adopt the current VERSION.
    assert 'stable v1.4.0' in status
    assert not re.search(r'\b(?:candidate|main[- ]only|unreleased)\b', status)
    assert not re.search(
        r'\bnot (?:yet )?(?:stable\b|in\b.{0,80}\bstable\b|'
        r'(?:released|included)\b.{0,80}\bstable\b)', status
    )
    assert not re.search(r'latest stable.{0,80}\bv?1\.3\.2\b', status)
