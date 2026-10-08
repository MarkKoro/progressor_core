"""Money stays integer and source-owned paid intervals are never cash balances.

Allocate a bundle price by current monthly native tariffs in the same currency;
charge only for the parts of the selected period not already paid for. No FX.
The complement intervals also define exactly what the new payment must grant.
"""
import math
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from .contracts import SOURCES

TERMS = 'progressor.bundle.v2'
VERSION = 'paid_coverage.v1'
DAY = 86400

def instant(value):
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

def ticks(value):
    return int(instant(value).timestamp() * 1000000)

def merged(intervals, start, end):
    rows = sorted((max(ticks(row['starts_at']), start), min(ticks(row['expires_at']), end)) for row in intervals)
    result = []
    for lo, hi in rows:
        if hi <= lo:
            continue
        if result and lo <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], hi))
        else:
            result.append((lo, hi))
    return result

def contiguous_end(intervals, now):
    start = ticks(now)
    rows = merged(intervals, start, start + DAY * 36600 * 1000000)
    return datetime.fromtimestamp(rows[0][1] / 1000000, timezone.utc) if rows and rows[0][0] == start else None

def validate_inputs(inputs):
    if set(inputs) != set(SOURCES):
        raise ValueError('native_pricing_unavailable')
    for source, row in inputs.items():
        prices = row['monthly_prices']
        if any(type(prices.get(currency)) is not int or not 1 <= prices[currency] <= 10000000 for currency in ('RUB','XTR')):
            raise ValueError('invalid_native_tariff')
        intervals = row['paid_intervals']
        if not isinstance(intervals, list) or len(intervals) > 100:
            raise ValueError('invalid_paid_intervals')
        for interval in intervals:
            if not isinstance(interval.get('grant_id'), str) or not 1 <= len(interval['grant_id']) <= 300:
                raise ValueError('invalid_paid_grant')
            if not 0 < (instant(interval['expires_at'])-instant(interval['starts_at'])).total_seconds() <= DAY*36600:
                raise ValueError('invalid_paid_grant_period')

def calculate(inputs, plans, plan, currency, now, scheduled_until=None):
    validate_inputs(inputs)
    if currency not in ('RUB','XTR'):
        raise ValueError('invalid_currency')
    now = instant(now)
    starts = max(now, instant(scheduled_until)) if scheduled_until else now
    native_ends = {s: contiguous_end(inputs[s]['paid_intervals'], now) for s in SOURCES}
    if plan == 'align':
        if starts > now:
            raise ValueError('alignment_already_covered_by_bundle')
        choices = [value for value in native_ends.values() if value and now+timedelta(hours=1) < value <= now+timedelta(days=365)]
        if not choices:
            raise ValueError('no_paid_period_to_align')
        ends = min(choices)
        days = max(1, math.ceil((ends-starts).total_seconds()/DAY))
        reference = next((p for p in sorted(plans,key=lambda p:p['days']) if p['days'] >= days), None)
        if reference is None:
            raise ValueError('alignment_period_too_long')
        base = Fraction(reference[currency]) * Fraction(ticks(ends)-ticks(starts), reference['days']*DAY*1000000)
        label = 'До ' + ends.strftime('%d.%m.%Y')
    else:
        reference = next((p for p in plans if p['id'] == plan), None)
        if reference is None:
            raise ValueError('invalid_bundle_plan')
        days = reference['days']
        # All three standalone products are already paid: offer the next period.
        if starts == now and all(native_ends.values()):
            starts = min(native_ends.values())
        ends = starts + timedelta(days=days)
        base = Fraction(reference[currency])
        label = reference['label']
    lo, hi = ticks(starts), ticks(ends)
    total_weight = sum(inputs[s]['monthly_prices'][currency] for s in SOURCES)
    pieces = []
    grants = []
    for source in SOURCES:
        covered = merged(inputs[source]['paid_intervals'], lo, hi)
        seconds = sum(b-a for a,b in covered)
        credit = base * Fraction(inputs[source]['monthly_prices'][currency], total_weight) * Fraction(seconds, hi-lo)
        pieces.append({'source':source,'fraction':credit,'covered_days':round(seconds / (DAY*1000000), 5),
                       'grant_ids':sorted({r['grant_id'] for r in inputs[source]['paid_intervals'] if ticks(r['starts_at'])<hi and ticks(r['expires_at'])>lo})})
        cursor = lo
        for a,b in covered:
            if a > cursor:
                grants.append({'source':source,'starts_at':datetime.fromtimestamp(cursor/1000000,timezone.utc).isoformat(),'expires_at':datetime.fromtimestamp(a/1000000,timezone.utc).isoformat()})
            cursor = b
        if cursor < hi:
            grants.append({'source':source,'starts_at':datetime.fromtimestamp(cursor/1000000,timezone.utc).isoformat(),'expires_at':ends.isoformat()})
    base_amount = math.ceil(base)
    # Round the total credit in the customer's favour, then allocate exact units.
    discount = min(base_amount, math.ceil(sum(p['fraction'] for p in pieces)))
    credits = {p['source']:math.floor(p['fraction']) for p in pieces}
    remainder = discount - sum(credits.values())
    for row in sorted(pieces,key=lambda p:(-(p['fraction']-math.floor(p['fraction'])),p['source']))[:remainder]:
        credits[row['source']] += 1
    return {'pricing_version':VERSION,'plan':plan,'label':label,'days':days,'currency':currency,
            'amount':base_amount-discount,'base_amount':base_amount,'credit_amount':discount,
            'starts_at':starts.isoformat(),'expires_at':ends.isoformat(),
            'already_covered':base_amount==discount,'terms_version':TERMS,
            'components':[{'source':p['source'],'credit_amount':credits[p['source']],'covered_days':p['covered_days'],'grant_ids':p['grant_ids']} for p in pieces],
            'grants':grants,'native_inputs':inputs,'quote_valid_until':(now+timedelta(minutes=20)).isoformat()}
