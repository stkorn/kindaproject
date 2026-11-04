"""CLI: python -m generator --start YYYY-MM-DD --end YYYY-MM-DD [--out data/bronze]

ช่วงวันเป็น argument ไม่ใช่ config เพราะ backfill (M6) ต้องสั่งทีละช่วงได้
"""

import argparse
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

from generator.bronze import write_day
from generator.config import load_config, load_simulation
from generator.orders import Order, OrderItem, generate_day

BUSINESS_CONFIG = Path("config/business.yaml")
SIMULATION_CONFIG = Path("config/simulation.yaml")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="generator", description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, default=Path("data/bronze"))
    args = parser.parse_args(argv)
    if args.start > args.end:
        parser.error(f"--start {args.start} is after --end {args.end}")

    cfg = load_config(BUSINESS_CONFIG)
    sim = load_simulation(SIMULATION_CONFIG, cfg)

    n_days = (args.end - args.start).days + 1
    n_orders = n_items = 0
    for offset in range(n_days):
        day = args.start + timedelta(days=offset)
        orders: list[Order] = []
        items: list[OrderItem] = []
        for branch in cfg.branches:
            branch_orders, branch_items = generate_day(cfg, sim, branch, day)
            orders += branch_orders
            items += branch_items
        write_day(orders, items, day, args.out)
        n_orders += len(orders)
        n_items += len(items)
    print(f"wrote {n_orders} orders, {n_items} items, {n_days} days to {args.out}")


if __name__ == "__main__":
    main()
