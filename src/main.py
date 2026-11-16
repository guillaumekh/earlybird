import sys
import time

import machine

try:
    import app

    app.main()
except KeyboardInterrupt:
    # Ctrl-C from mpremote or a terminal: stay at the REPL.
    try:
        app.stop_watchdog()
    except Exception:
        pass
    print("stopped")
except Exception as e:
    sys.print_exception(e)
    time.sleep(5)
    machine.reset()
