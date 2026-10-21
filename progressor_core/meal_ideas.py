"""Qualitative meal ideas using the canonical curated food examples.

These are explicit ingredients, not quantified recipes or an allergy model.
No amounts, nutrient totals, deficiency claims or provider requests belong here.
"""
from shared.food_sources import FOODS

VERSION = 1
# Sesame is an explicit additional ingredient in this catalog, not a new
# nutrient example or another copy of the existing food-source registry.
COMPONENTS = {**FOODS, 'sesame': ('Кунжут', ('sesame',), False)}
IDEAS = (
    ('beans_rice', 'Бобовые, гарнир и овощи', ('beans', 'rice', 'broccoli', 'olive')),
    ('poultry_rice', 'Птица с гарниром и овощами', ('poultry', 'rice', 'greens', 'olive')),
    ('eggs_bread', 'Яйца, хлеб и овощи', ('eggs', 'wholebread', 'peppers')),
    ('tofu_rice', 'Тофу с гарниром и овощами', ('tofu', 'rice', 'greens', 'olive')),
    ('fish_rice', 'Рыба с гарниром и овощами', ('fish', 'rice', 'broccoli')),
    ('dairy_fruit', 'Йогурт или творог с фруктами', ('dairy', 'fruit')),
    ('grains_nuts', 'Каша с фруктами и орехами', ('grains', 'fruit', 'nuts')),
    ('tofu_sesame', 'Тофу с овощами и кунжутом', ('tofu', 'broccoli', 'sesame', 'rice')),
    ('meat_grains', 'Говядина с крупой и овощами', ('meat', 'grains', 'greens')),
    ('shellfish_rice', 'Приготовленные моллюски с гарниром', ('shellfish', 'rice', 'broccoli')),
)
NOTE = ('Идеи с перечисленными компонентами, без расчёта порции и КБЖУ. '
        'Учитываем выбранный рацион и десять групп исключений. '
        'Проверяйте состав конкретных продуктов: это не полный справочник аллергенов.')


def ideas(preferences, limit=3):
    from progressor_core.connections import FOOD_GROUPS
    if (not isinstance(preferences, dict)
            or preferences.get('diet') not in ('any', 'vegetarian', 'vegan')
            or not isinstance(preferences.get('excluded_food_groups'), list)
            or any(group not in FOOD_GROUPS for group in preferences['excluded_food_groups'])):
        raise ValueError('unknown_food_preferences')
    excluded = set(preferences['excluded_food_groups'])
    if preferences['diet'] in ('vegetarian', 'vegan'):
        excluded.update(('fish', 'shellfish', 'meat', 'poultry'))
    if preferences['diet'] == 'vegan':
        excluded.update(('eggs', 'dairy'))
    result = []
    for ident, title, ingredients in IDEAS:
        components = [COMPONENTS[item] for item in ingredients]
        groups = sorted({group for _, tags, _ in components for group in tags})
        if excluded.intersection(groups):
            continue
        if preferences['diet'] == 'vegan' and any(animal for _, _, animal in components):
            continue
        result.append({'id': ident, 'title': title,
                       'components': [name for name, _, _ in components],
                       'food_groups': groups, 'amounts': None})
        if len(result) >= limit:
            break
    return result
