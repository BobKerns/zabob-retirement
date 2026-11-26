# Entry point for the zabob.retirement package.

from zabob.retirement.cli import main
from zabob.retirement.oscompat import rerun_with_console

if __name__ == "__main__":
    # Windows's hourly task runs this under pythonw, with no window (#748).
    rerun_with_console()
    main()
