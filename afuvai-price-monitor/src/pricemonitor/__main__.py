# Entry point: python3 -m pricemonitor <subcommand> (run from src/, or with
# PYTHONPATH=src from the afuvai-price-monitor root).
from pricemonitor.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
