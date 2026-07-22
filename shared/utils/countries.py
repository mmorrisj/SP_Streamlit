"""
Country name <-> ISO code mapping for external economic data sources.

The config country lists (influencers/recipients in shared/config/config.yaml)
use plain-English names, while the World Bank and IMF APIs key their data on
ISO-3166 alpha-3 codes. This module provides the bridge, including aliases for
the name variants that appear in the config and in source data
(e.g. "UAE" / "United Arab Emirates", "Turkey" / "Türkiye").
"""

from typing import Dict, List, Optional

# canonical name -> (iso3, iso2)
_COUNTRIES: Dict[str, tuple] = {
    'China':                ('CHN', 'CN'),
    'Russia':               ('RUS', 'RU'),
    'Iran':                 ('IRN', 'IR'),
    'Turkey':               ('TUR', 'TR'),
    'United States':        ('USA', 'US'),
    'Bahrain':              ('BHR', 'BH'),
    'Cyprus':               ('CYP', 'CY'),
    'Egypt':                ('EGY', 'EG'),
    'Iraq':                 ('IRQ', 'IQ'),
    'Israel':               ('ISR', 'IL'),
    'Jordan':               ('JOR', 'JO'),
    'Kuwait':               ('KWT', 'KW'),
    'Lebanon':              ('LBN', 'LB'),
    'Libya':                ('LBY', 'LY'),
    'Oman':                 ('OMN', 'OM'),
    'Palestine':            ('PSE', 'PS'),
    'Qatar':                ('QAT', 'QA'),
    'Saudi Arabia':         ('SAU', 'SA'),
    'Syria':                ('SYR', 'SY'),
    'United Arab Emirates': ('ARE', 'AE'),
    'Yemen':                ('YEM', 'YE'),
}

# alias (lowercased) -> canonical name
_ALIASES: Dict[str, str] = {
    'uae': 'United Arab Emirates',
    'u.a.e.': 'United Arab Emirates',
    'türkiye': 'Turkey',
    'turkiye': 'Turkey',
    'usa': 'United States',
    'us': 'United States',
    'united states of america': 'United States',
    'russian federation': 'Russia',
    'islamic republic of iran': 'Iran',
    'iran, islamic republic of': 'Iran',
    'iran, islamic rep.': 'Iran',
    'syrian arab republic': 'Syria',
    'egypt, arab rep.': 'Egypt',
    'yemen, rep.': 'Yemen',
    'west bank and gaza': 'Palestine',
    'palestinian territories': 'Palestine',
    "china, people's republic of": 'China',
    'saudi arabia, kingdom of': 'Saudi Arabia',
}

_ISO3_TO_NAME: Dict[str, str] = {iso3: name for name, (iso3, _) in _COUNTRIES.items()}


def canonical_name(name: str) -> Optional[str]:
    """Resolve a country name (or alias) to its canonical config name."""
    if not name:
        return None
    stripped = name.strip()
    if stripped in _COUNTRIES:
        return stripped
    alias = _ALIASES.get(stripped.lower())
    if alias:
        return alias
    # case-insensitive match on canonical names
    for canon in _COUNTRIES:
        if canon.lower() == stripped.lower():
            return canon
    return None


def to_iso3(name: str) -> Optional[str]:
    """Country name (or alias) -> ISO-3166 alpha-3 code. None if unknown."""
    canon = canonical_name(name)
    return _COUNTRIES[canon][0] if canon else None


def to_iso2(name: str) -> Optional[str]:
    """Country name (or alias) -> ISO-3166 alpha-2 code. None if unknown."""
    canon = canonical_name(name)
    return _COUNTRIES[canon][1] if canon else None


def iso3_to_name(iso3: str) -> Optional[str]:
    """ISO-3 code -> canonical config country name. None if unknown."""
    if not iso3:
        return None
    return _ISO3_TO_NAME.get(iso3.strip().upper())


def names_to_iso3(names: List[str]) -> Dict[str, str]:
    """
    Map a list of country names to ISO-3 codes, deduplicating aliases
    (e.g. 'UAE' and 'United Arab Emirates' collapse to one ARE entry).
    Unknown names are silently dropped — callers that care should compare
    the input and output sizes.
    """
    result: Dict[str, str] = {}
    for name in names:
        iso3 = to_iso3(name)
        if iso3 and iso3 not in result.values():
            canon = canonical_name(name)
            result[canon] = iso3
    return result
