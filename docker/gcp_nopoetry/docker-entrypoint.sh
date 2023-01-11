#!/bin/bash
set -e

PYTHONPATH="/app"

# Run the container the default way
if [[ "$1" =~ 'envshell' ]]; then
    /bin/bash
fi

if [[ "$1" =~ 'tests' ]]; then
    /bin/bash python -m unittest discover -s tests -p '*.py'
fi

# Run a custom command on container start
exec "$@"
