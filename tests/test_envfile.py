import pytest

from core.envfile import records, values
from core.state import StateError


@pytest.mark.parametrize('text,expected', [
    ('KEY=plain value $() `cmd` #literal\n', 'plain value $() `cmd` #literal'),
    ("KEY=' leading trailing $!#= '\n", ' leading trailing $!#= '),
    ('KEY="double \\"quote\\" \\\\ \\$"\n', 'double "quote" \\ $'),
    ('KEY=ab\\\ncd\n', 'abcd'),
    ("KEY='first\nsecond'\n", 'first\nsecond'),
    ('KEY=has"literal"quotes\n', 'has"literal"quotes'),
])
def test_environment_values_without_evaluation(text, expected):
    assert values(text)['KEY'] == expected
    assert ''.join(raw for _, _, raw in records(text)) == text


def test_unclosed_quote_rejected():
    with pytest.raises(StateError):
        values("APP_PASSWORD='unfinished\n")
