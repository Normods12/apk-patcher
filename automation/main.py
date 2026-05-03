import argparse

from automation.monitor.monitor import run_monitor
from automation.worker.worker import run_worker


def main() -> None:
    parser = argparse.ArgumentParser(description="Automation entrypoint")
    parser.add_argument("mode", choices=["monitor", "worker"], help="Service mode")
    parser.add_argument("--app-name", help="Filter jobs by app name", default=None)
    parser.add_argument("--app-id", type=int, help="Filter jobs by app ID", default=None)
    args = parser.parse_args()

    if args.mode == "monitor":
        run_monitor()
    else:
        run_worker(app_name=args.app_name, app_id=args.app_id)


if __name__ == "__main__":
    main()
