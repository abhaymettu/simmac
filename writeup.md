# SimMac: my Mac as a city (draft)

Draft writeup. Nothing here is published.

## The 20-second clip

It's just past midnight. The clip opens on a small island city under a starry sky.
- A tall tower in the north is Xcode. Next to it, the Python building smokes, because a background job is pinning several cores.
- In the east, the workshop quarter rises around postgres, with Claude's building wearing a blinking red beacon.
- In the south, a grid of gray blocks holds the hundreds of small macOS system processes.
- Cars stream along the avenues, one for every dozen processes.
- From the radio tower on the edge, cyan arcs drop onto rooftops as data comes in, and pink arcs fly back out.
- When the load average climbs, a faint ring pulses outward along the roads.

The second clip runs the same live city while the sky turns through a whole day in 20 seconds.

## What I built

- A small Python server, standard library only. It reads `ps`, `vm_stat`, `netstat -ib` and the load average, groups processes into apps, and serves one JSON snapshot a second on localhost.
- A single canvas page, with no framework and no downloads. It draws a 640x360 pixel buffer and scales it up with smoothing off. It includes a hand-made 3x5 pixel font for the labels and the HUD.
- A recorder that drives headless Chrome, captures the canvas with MediaRecorder, and converts the result with ffmpeg.
- 20 tests: the parsers, the model and the server, plus a smoke test that renders the page against a fake Mac and checks what it drew.

## Honest numbers

From this Mac, Oct 21, 2026 just after midnight:
- 24 GB of memory, 12 cores.
- About 840 to 910 processes.
- Load average between 18 and 54 while I worked, because other jobs were running.
- One data read took 0.1 to 1.2 s.
- The headless recordings captured about 13 to 15 frames a second. The MP4s are 30 fps with repeated frames.
- The city shows up to 60 buildings at a time.

## What it doesn't do yet

- No click or hover on buildings.
- No GPU or disk reads. powermetrics needs root, so I left it out.
- macOS only.
- Only tested in Chrome.
