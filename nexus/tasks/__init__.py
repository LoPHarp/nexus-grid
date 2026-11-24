"""Task handlers. A new task type = one module with split() and compute() (+ pack()), registered here.

Handler interface:
  normalize(params) -> params   optional, validate and fill defaults (server)
  summary(params) -> dict       optional, what is stored/returned for the job (server)
  split(params) -> [dict]       one params dict per task (server)
  compute(task_params) -> obj   run one task (worker)
  pack(task_id, obj) -> bytes   binary result frame (worker)
"""
from . import image, mandelbrot

HANDLERS = {"mandelbrot": mandelbrot, "image": image}
