import copy
import unittest
from datetime import datetime,timedelta,timezone
from progressor_core.pricing import calculate
from progressor_core.billing import PLANS

NOW = datetime(2026,10,8,12,tzinfo=timezone.utc)

def inputs():
    return {s:{'monthly_prices':{'RUB':rub,'XTR':stars},'paid_intervals':[]} for s,rub,stars in [('gym',10000,67),('food',39900,266),('supply',20000,250)]}

def paid(rows,source,days,start=NOW,key='paid'):
    rows[source]['paid_intervals'].append({'grant_id':source+':'+key,'starts_at':start.isoformat(),'expires_at':(start+timedelta(days=days)).isoformat()})

def quote(rows,plan='m1',currency='RUB',scheduled=None):
    return calculate(rows,[{**value,'id':key} for key,value in PLANS.items()],plan,currency,NOW,scheduled)

class UpgradePricing(unittest.TestCase):
    def test_without_paid_access_price_and_full_coverage(self):
        rows=inputs()
        for currency,amount in [('RUB',59900),('XTR',450)]:
            result=quote(rows,currency=currency)
            self.assertEqual(result['amount'],amount)
            self.assertEqual(len(result['grants']),3)
            self.assertEqual(sum(c['credit_amount'] for c in result['components']),0)
    def test_food_remaining_twenty_has_both_period_options(self):
        rows=inputs();paid(rows,'food',20)
        aligned=quote(rows,'align');month=quote(rows)
        self.assertEqual(aligned['expires_at'],(NOW+timedelta(days=20)).isoformat())
        self.assertEqual(month['expires_at'],(NOW+timedelta(days=30)).isoformat())
        self.assertLess(aligned['amount'],month['amount'])
        self.assertLess(month['amount'],month['base_amount'])
        self.assertFalse(any(g['source']=='food' for g in aligned['grants']))
        food=next(g for g in month['grants'] if g['source']=='food')
        self.assertEqual(food['starts_at'],(NOW+timedelta(days=20)).isoformat())
    def test_prices_differ_by_product_in_both_currencies(self):
        for currency in ['RUB','XTR']:
            amounts=[]
            for source in ['gym','food','supply']:
                rows=inputs();paid(rows,source,20)
                amounts.append(quote(rows,currency=currency)['amount'])
            self.assertEqual(len(set(amounts)),3)
            self.assertTrue(all(x<PLANS['m1'][currency] for x in amounts))
    def test_two_paid_products_add_two_credits_exactly(self):
        rows=inputs();paid(rows,'food',20);paid(rows,'supply',10)
        result=quote(rows)
        self.assertEqual(sum(c['credit_amount'] for c in result['components']),result['credit_amount'])
        self.assertEqual(result['amount']+result['credit_amount'],result['base_amount'])
    def test_duplicate_paid_windows_never_double_the_credit(self):
        rows=inputs();paid(rows,'food',20)
        before=quote(rows)
        rows['food']['paid_intervals'].append(copy.deepcopy(rows['food']['paid_intervals'][0]))
        after=quote(rows)
        self.assertEqual(after['amount'],before['amount'])
    def test_future_paid_days_credit_only_actual_overlap(self):
        rows=inputs();paid(rows,'food',10,start=NOW+timedelta(days=5))
        result=quote(rows)
        periods=[g for g in result['grants'] if g['source']=='food']
        self.assertEqual(len(periods),2)
        self.assertEqual(periods[0]['expires_at'],(NOW+timedelta(days=5)).isoformat())
        self.assertEqual(periods[1]['starts_at'],(NOW+timedelta(days=15)).isoformat())
    def test_renewal_cannot_reuse_already_credited_period(self):
        rows=inputs();paid(rows,'food',20)
        result=quote(rows,scheduled=(NOW+timedelta(days=30)).isoformat())
        self.assertEqual(result['credit_amount'],0)
        self.assertEqual(result['starts_at'],(NOW+timedelta(days=30)).isoformat())
    def test_all_standalones_paid_offer_the_next_period(self):
        rows=inputs()
        for source,days in [('gym',10),('food',80),('supply',90)]:paid(rows,source,days)
        result=quote(rows)
        self.assertEqual(result['starts_at'],(NOW+timedelta(days=10)).isoformat())
        self.assertGreater(result['amount'],0)
        self.assertLess(result['amount'],result['base_amount'])
    def test_all_paid_alignment_is_not_a_token_payment(self):
        rows=inputs()
        for source in rows:paid(rows,source,20)
        result=quote(rows,'align')
        self.assertTrue(result['already_covered'])
        self.assertEqual(result['amount'],0)
        self.assertEqual(result['grants'],[])
    def test_single_star_credit_for_very_short_remaining_access(self):
        rows=inputs();paid(rows,'gym',1/86400)
        result=quote(rows,currency='XTR')
        self.assertEqual(result['amount'],449)
    def test_missing_or_invalid_prices_never_guess_a_discount(self):
        rows=inputs();rows['food']['monthly_prices']['RUB']=0
        with self.assertRaisesRegex(ValueError,'invalid_native_tariff'):quote(rows)
        rows=inputs();rows.pop('supply')
        with self.assertRaisesRegex(ValueError,'native_pricing_unavailable'):quote(rows)

if __name__=='__main__':unittest.main()
