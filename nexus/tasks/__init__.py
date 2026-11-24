"""Task handlers. A new task type = one module with split() and compute(), registered here."""
from . import mandelbrot

HANDLERS = {"mandelbrot": mandelbrot}
