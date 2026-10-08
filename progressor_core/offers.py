"""Honest product examples. Never read unavailable health/workout/meal records."""
from .access import active_until

NAMES = {'gym': 'Тренировки', 'food': 'Еда', 'supply': 'БАДы'}
EXAMPLES = {
    ('gym', 'food'): ('Питание рядом с тренировками', 'Сравнивайте записи белка и свою цель питания с тренировками.',
                     'Пример: «В записанных днях белок ниже вашей цели — проверьте дневник питания».'),
    ('gym', 'supply'): ('Профиль для вашего плана', 'Используйте согласованный профиль из БАДов при подготовке тренировочного плана.',
                       'Пример: рост и вес уже заполнены — их не придётся вводить повторно.'),
    ('food', 'gym'): ('Тренировка рядом с питанием', 'Видите записанную нагрузку и сравниваете питание со своей целью на день.',
                     'Пример: «Сегодня тренировка учтена — проверьте белок и полноту записей».'),
    ('food', 'supply'): ('Один профиль для питания', 'Используйте согласованный профиль и видите свои записи добавок рядом с рационом.',
                        'Пример: «В БАДах уже записана добавка — проверьте её вместе с блюдами».'),
    ('supply', 'food'): ('Рацион рядом с добавками', 'Смотрите источники нутриентов в записанных блюдах и свой список добавок.',
                        'Пример: «В дневнике мало источников B12 — проверьте полноту записей и блюда».'),
    ('supply', 'gym'): ('Нагрузка рядом с профилем', 'Учитывайте записанные тренировки, когда проверяете своё питание и профиль.',
                       'Пример: «Тренировок стало больше — сравните журнал питания со своей целью».'),
}


def bundle_preview(entities, access, target, now, enabled_sources=None):
    enabled = set(enabled_sources) if enabled_sources is not None else set(NAMES)
    if target not in enabled or target not in NAMES: return None
    # Trial/gift activity affects the offer only, never grants access to paid cross-source data.
    native = {s for s in enabled if access['domains'].get(s)}
    for e in entities:
        if e['source'] in enabled and e['entity_id'].startswith('profile:') and active_until(e['payload'].get('native_trial_until'), now):
            native.add(e['source'])
    missing = [s for s in NAMES if s in enabled and not access['domains'].get(s)]
    if not missing: return None
    alternatives = [s for s in NAMES if s in enabled and s != target and not access['domains'].get(s)]
    if not alternatives:
        alternatives=[s for s in NAMES if s in enabled and s!=target]
    if not alternatives: return None
    peers=[s for s in alternatives if s not in native] or alternatives
    peer = next((s for s in ('food', 'gym', 'supply') if s in peers), peers[0])
    title, message, example = EXAMPLES[(target, peer)]
    if len(native)==2: message='Два раздела уже доступны. Общая подписка добавит связь с третьим. '+message
    elif len(native)==3: message='Сохраните общий доступ после окончания пробных периодов. '+message
    return {'key': 'bundle_example.' + target + '.' + peer + '.v1', 'kind': 'locked_example',
            'title': title, 'message': message, 'example': example, 'is_personal_result': False,
            'current_access_domains': sorted(native), 'missing_domains': missing,
            'offer_reason': 'continue_three_products' if len(native)==3 else 'complete_three_products' if len(native)==2 else 'connect_products',
            'action': {'kind': 'bundle', 'label': 'Посмотреть общую подписку'},
            'details': 'Это пример возможности, а не вывод о ваших данных. Подсказки появятся при доступе к нужным продуктам и достаточных свежих записях. Профиль и здоровье используются с вашим согласием. Можно подключить отдельный продукт или общую подписку; сроки отдельных подписок сохраняются.'}
