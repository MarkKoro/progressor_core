#!/usr/bin/env python3
"""Core-only entry point; all recovery and locking lives in update_all.py."""
import sys


def main():
    from update_all import main as update_all_main
    update_all_main(['--only', 'core', *sys.argv[1:]])


if __name__ == '__main__':
    try: main()
    except Exception as error:
        # Raw subprocess/provider output belongs only in the private transaction log.
        reason = str(error)[:180] if isinstance(error, RuntimeError) else type(error).__name__
        print('Core не обновлён: ' + reason, flush=True)
        raise SystemExit(1)
