"""Allow running minilake as a module: python -m minilake"""

from minilake.cli import main

if __name__ == "__main__":
    exit(main())
