"""Exact bounded multiplicative unit conversion using a trusted host unit table.

No physical dimension inference, currency conversion, affine temperature scale,
range interpretation, or extraction from prose. This normalizes already extracted
values; it cannot establish that a quantity describes the requested entity.
"""
from decimal import Decimal, localcontext
import re

_NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z')


def _decimal(text):
    if type(text) is not str or len(text) > 66 or not _NUMBER.fullmatch(text):
        raise ValueError('Plain bounded decimal required')
    value = Decimal(text)
    if len(value.as_tuple().digits) > 32 or abs(value.as_tuple().exponent) > 32:
        raise ValueError('Decimal precision budget exceeded')
    return value


def canonical_quantity(text, *, base_unit, factors):
    """Return exact canonical text and conversion provenance.

factors maps accepted unit spellings to decimal-string multipliers in base_unit.
The host is responsible for same-dimension factors. base_unit must map to 1.
Only unambiguous scalar quantities such as '2 kilograms' are accepted. The table
must never be supplied or extended by untrusted source content.
"""
    if (type(base_unit) is not str or not base_unit.strip() or base_unit != base_unit.strip()
            or len(base_unit) > 64 or type(factors) is not dict or not 1 <= len(factors) <= 32):
        raise ValueError('Bounded host unit table required')
    scales = {}
    for unit, factor in factors.items():
        if (type(unit) is not str or not unit.strip() or unit != unit.strip()
                or len(unit) > 64 or any(c.isspace() for c in unit)):
            raise ValueError('Single-token unit names required')
        scale = _decimal(factor)
        if scale <= 0:
            raise ValueError('Positive multiplier required')
        scales[unit] = scale
    if scales.get(base_unit) != Decimal(1):
        raise ValueError('Base unit must have multiplier one')
    if type(text) is not str or len(text) > 160:
        raise ValueError('Bounded scalar quantity required')
    parts = text.split()
    if len(parts) != 2 or parts[1] not in scales:
        raise ValueError('One scalar and one declared unit required')
    number = _decimal(parts[0])
    with localcontext() as context:
        context.prec = 80  # Product of two <=32-digit decimals is exact.
        context.Emax = 128
        context.Emin = -128
        converted = number * scales[parts[1]]
    canonical = '0' if converted == 0 else format(converted, 'f')
    if '.' in canonical:
        canonical = canonical.rstrip('0').rstrip('.')
    return dict(value=canonical+' '+base_unit, original=text, base_unit=base_unit,
                source_unit=parts[1], multiplier=factors[parts[1]], arithmetic='exact-decimal')
