import sys
from .cli import main

main(["validate", *sys.argv[1:]])

