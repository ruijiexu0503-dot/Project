import sys
from .cli import main

main(["build-nodes", *sys.argv[1:]])

