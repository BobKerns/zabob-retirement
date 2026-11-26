# Entry point for the zabob.retirement package.

from zabob.retirement.oscompat import rerun_with_console

if __name__ == "__main__":
    # Windows's hourly task runs this under pythonw, with no window (#748);
    # rerun first, before importing the whole CLI only to throw it away.
    rerun_with_console()
    from zabob.retirement.cli import main

    main()
