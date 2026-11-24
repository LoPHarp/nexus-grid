# Demo script (about 3 minutes)

Setup: public server https://nexus-grid-2ivy.onrender.com, the key in an untracked `.env`. Wake the server first (open the dashboard, wait until the green dot shows). Do not show `.env` or the key on screen.

| Time | Action | What is visible |
|---|---|---|
| 0:00 | Browser: dashboard; next to it the desktop worker window | empty graph, HUD at 0 |
| 0:20 | In the worker window enter server URL and key, press Connect | status "connected", the node appears in the graph |
| 0:40 | Terminal: `set -a; . ./.env; set +a; demo/demo.sh` (starts 3 more workers and a 192-tile job) | mosaic fills with tiles in worker colours, pulses on the graph, HUD tasks/s |
| 1:20 | The script kills worker w1 | node turns red, toast "re-queued", the other workers take its tiles, mosaic completes |
| 1:50 | Terminal: `curl $NEXUS_URL/api/jobs/1`, `curl $NEXUS_URL/api/workers` (or Swagger at `/docs`) | job `done 192/192`, dead worker listed |
| 2:15 | Dashboard charts and HUD | CPU, temperature, throughput, queue depth, latency per worker |
| 2:40 | `python tools/submit_images.py ./photos --max-side 800 --format WEBP` | practical task: files shrunk, results unpacked |
| 2:55 | Press Demo Mode on the dashboard (no local workers needed) | server-side demo workers and job; click one to kill it |

Notes: the demo script prints a worker table at the end. `DELAY=0.4 WORKERS=4` can be changed through environment variables to make the render slower or faster.
