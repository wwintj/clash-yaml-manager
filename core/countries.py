"""One offline ISO 3166-1 catalog for parsing and browser selectors.

249 assigned codes from pycountry/iso-codes; localized names generated using
Node 24 Intl.DisplayNames (Unicode CLDR). See docs/COUNTRY_DATA.md.
"""
import json
import re
from pathlib import Path

COMMON = 'US HK TW JP KR SG MY TH PH ID AU CA GB DE FR NL'.split()
CITY_ALIASES = {
    'US': ['USA', 'America', 'Los Angeles', 'LA', '美国', '美國'],
    'JP': ['Tokyo', '东京', '東京', 'Osaka', '大阪'],
    'TW': ['Taipei', '台北', '台湾', '台灣'],
    'SG': ['Singapore', '新加坡', '狮城', '獅城'],
    'KR': ['Korea', 'South Korea', 'SouthKorea', 'Seoul', '首尔', '首爾', '韓國'],
    'HK': ['Hong Kong', 'HongKong', '香港'],
    'GB': ['UK', 'Britain', 'London', '伦敦', '倫敦', '英國'],
    'DE': ['Germany', 'Frankfurt', '法兰克福', '德國'],
    'FR': ['France', 'Paris', '巴黎', '法國'],
    'NL': ['Netherlands', 'Amsterdam', '阿姆斯特丹'],
    'TH': ['Bangkok', '曼谷', 'Thai'],
}
COUNTRIES = {}
for item in json.loads(Path(__file__).with_name('countries.json').read_text(encoding='utf-8')):
    code = item['code']
    emoji = ''.join(chr(127397 + ord(c)) for c in code)
    label = {'HK': '香港', 'TW': '台湾', 'SG': '狮城'}.get(code, item['chinese'])
    COUNTRIES[code] = dict(item, emoji=emoji, label=label, group=f'{emoji} {label}节点',
                           aliases=list(dict.fromkeys(item['aliases'] + CITY_ALIASES.get(code, []))))
COUNTRIES = {code: COUNTRIES[code] for code in COMMON + sorted(set(COUNTRIES) - set(COMMON))}
UNKNOWN = dict(code='UNKNOWN', emoji='🌐', english='Unknown', chinese='未知', label='Unknown',
               group='🌐 其他节点', aliases=[])
COUNTRY_MAPPING = dict(COUNTRIES, UNKNOWN=UNKNOWN)
for code, country in COUNTRY_MAPPING.items():
    country['search_aliases'] = country['aliases'] + (['tai'] if code == 'TH' else [])


# Compile once: parsing a large paste must not repeatedly compile 1,000 patterns.
_DETECTION_PATTERNS = []
for _code, _info in COUNTRIES.items():
    _aliases = [_info['english'], _info['chinese']] + _info['aliases']
    if _code != 'LA':  # LA is the requested Los Angeles alias; Laos names/flag still work.
        _aliases.append(_code)
    for _alias in _aliases:
        _chinese = bool(re.search(r'[\u3400-\u9fff]', _alias))
        _pattern = re.escape(_alias) if _chinese else r'(?<![A-Za-z])' + re.escape(_alias) + r'(?![A-Za-z])'
        _flags = 0 if len(_alias) <= 3 and _alias.isupper() else re.IGNORECASE
        _DETECTION_PATTERNS.append((_code, re.compile(_pattern, _flags)))


def detect_country(name):
    """Bounded Latin words/uppercase codes, Chinese phrases and exact flags only.

    Specific names take precedence over contained names (North Korea over Korea,
    白俄罗斯 over 俄罗斯). Conflicting, separate hints stay Unknown. No GeoIP/DNS.
    """
    flags = {code for code, info in COUNTRIES.items() if info['emoji'] in name}
    if flags:
        return next(iter(flags)) if len(flags) == 1 else 'UNKNOWN'
    spans = [(code, match.start(), match.end()) for code, pattern in _DETECTION_PATTERNS
             for match in pattern.finditer(name)]
    matches = {code for code, start, end in spans
               if not any(other_start <= start and other_end >= end and
                          (other_start < start or other_end > end)
                          for _, other_start, other_end in spans)}
    return next(iter(matches)) if len(matches) == 1 else 'UNKNOWN'
