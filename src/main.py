"""Chart Digitizer – entry point."""

import sys


def main():
    from src.gui.app import run_application
    sys.exit(run_application(sys.argv))


if __name__ == "__main__":
    main()
