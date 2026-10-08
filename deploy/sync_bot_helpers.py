"""Compare (default) or synchronize adapters in explicitly provided local checkouts."""
import argparse
import hashlib
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
FILES = {'domain_bridge.py': 'progressor_bridge.py', 'progressor_client.py': 'progressor_client.py',
         'progressor_bot.py': 'progressor_bot.py', 'ai_guard.py': 'progressor_ai_guard.py'}


def main():
    parser = argparse.ArgumentParser(description='Canonical helpers from MarkKoro/progressor_core')
    parser.add_argument('--gym', type=Path, required=True)
    parser.add_argument('--food', type=Path, required=True)
    parser.add_argument('--supply', type=Path, required=True)
    parser.add_argument('--write', action='store_true', help='Copy into the explicitly supplied local checkouts')
    args = parser.parse_args()
    mismatches = []
    for name in ('gym', 'food', 'supply'):
        checkout = getattr(args, name).resolve(strict=True)
        if not (checkout / '.git').exists() or not (checkout / 'bot.py').is_file():
            raise SystemExit('Expected a bot Git checkout: ' + name)
        if str(checkout).startswith('/srv/') and args.write:
            raise SystemExit('Synchronize in development; publish main and use the backed-up deployment.')
        files = {**FILES, **({'workout_metrics.py': 'progressor_workout_metrics.py'} if name == 'gym' else {}),
                 **({'nutrition_plan.py': 'progressor_nutrition_plan.py'} if name == 'food' else {})}
        for source, target in files.items():
            canonical = (CORE / 'shared' / source).read_bytes()
            destination = checkout / target
            if args.write:
                destination.write_bytes(canonical)
            if not destination.is_file() or destination.read_bytes() != canonical:
                mismatches.append(name + '/' + target)
            else:
                print(name + '/' + target + ' ' + hashlib.sha256(canonical).hexdigest())
    if mismatches:
        raise SystemExit('Mismatched helpers: ' + ', '.join(mismatches))


if __name__ == '__main__':
    main()
