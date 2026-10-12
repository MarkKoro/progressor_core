import unittest
from shared.food_sources import REGISTRY,SOURCES,examples,matches

class FoodSources(unittest.TestCase):
    def test_every_registered_nutrient_has_a_curated_entry_without_fake_amounts(self):
        self.assertEqual(set(REGISTRY),set(SOURCES));self.assertEqual(len(REGISTRY),54)
        for code in REGISTRY:
            value=examples(code);self.assertTrue(value['items']);self.assertIsNone(value['amounts']);self.assertTrue(value['source_url'].startswith('https://'))
    def test_vegan_b12_only_explicit_fortified_labels_and_epa_not_replaced_by_ala(self):
        b=examples('vitamin_b12',{'diet':'vegan'});self.assertEqual([i['example_id'] for i in b['items']],['fortb12'])
        self.assertFalse(examples('epa',{'diet':'vegan'})['items'])
        self.assertNotIn('flax',[i['example_id'] for i in examples('dha')['items']])
    def test_exclusions_and_informational_substances(self):
        for code in REGISTRY:
            for item in examples(code,{'diet':'vegan','excluded_food_groups':['nuts','soy','gluten']})['items']:
                self.assertFalse(set(item['groups']).intersection(('nuts','soy','gluten','fish','meat','dairy','eggs')))
        self.assertIn('не предложение увеличивать',examples('trans_fat')['note'])
    def test_unambiguous_aliases_and_unknown_do_not_guess_composition(self):
        self.assertEqual(matches('B12'),['vitamin_b12']);self.assertEqual(matches('Омега-3'),['omega_3'])
        self.assertEqual(matches('complex with magnesium and iron'),[])
        with self.assertRaises(ValueError):examples('made_up')
