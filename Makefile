# The Pico is picked by its USB id, in case other serial devices are plugged in.
MPREMOTE = mpremote connect $$(mpremote devs | awk '/2e8a:0005/ {print $$1; exit}')

.PHONY: test build deploy diag repl

test:
	python3 -m unittest discover -s tests

# Reads its settings from the environment; see local.env.example.
build:
	python3 tools/build.py

deploy:
	$(MPREMOTE) cp build/*.py : + reset

diag:
	$(MPREMOTE) run src/diag.py

repl:
	$(MPREMOTE)
