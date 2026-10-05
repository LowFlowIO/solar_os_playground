# Vision Basics (Python)

A script tutorial for classical computer vision in SolarOS 4.16.0. Step through
a bundled dog photograph and see what each native operation does. No camera,
network connection, or neural model is needed.

Read `main()` in [vision.py](vision.py) first. It shows five steps directly:

1. **Open:** `image.open(path)` decodes a picture into a native image handle.
2. **Blur:** `vision.gaussian(original, options)` smooths noise and produces a
   grayscale image. `ksize=1` means a kernel radius of one, or a 3x3 neighborhood.
3. **Threshold:** `vision.binary(smooth, {"thresholds": [[0, 100]]})` selects
   dark pixels. Matching pixels become **white**, regardless of their original
   brightness; the rest become black.
4. **Clean:** `vision.opening(mask, {"ksize": 1})` erodes then dilates the white
   foreground, removing small specks. It can also remove narrow features.
5. **Find regions:** `vision.blobs(clean, options)` finds connected white
   regions and returns bounding boxes, centroids, and matching pixel counts.
   The last screen draws their boxes and centers on the original picture.

`dog.jpg` is the bundled 320x240 grayscale photograph. The dog's dark fur and
the textured grass show how smoothing, thresholding, and cleanup affect a real
picture. Connected regions are not semantic object recognition: a region may
contain part of the dog, grass, or several touching features. A different
threshold can change the count. This pipeline does not identify a dog.

## Run and controls

From the shell on the device's display:

```text
playground install vision-basics
playground run vision-basics
playground run vision-basics --file /sdcard/pictures/example.png
```

Space, Enter, or Right advances to the next step. On the last step, advancing
finishes the tutorial. Q, Escape, or the normal app-exit key exits at any step.
Run it again to repeat the walkthrough. Images update only when advancing.

To launch an installed flash copy from a port shell onto a ready `display0`:

```text
session create python display0 /flash/playground/python/vision-basics/vision.py
```

Use the actual target reported by `display list`; substitute `/sdcard` for
`/flash` when installed on SD. Bare `gfx.begin()` needs the display session that
owns the foreground application.

## Adapt the script

Start with a picture of dark, separated objects against a plain light background.
Use `--file PATH` to supply a PNG, JPEG, GIF, or WebP. Change the upper limit of
`[0, 100]` in `main()` to include more or fewer grayscale pixels. For light objects
on a dark background, select a bright range such as `[160, 255]` instead.

The first filter resizes large inputs to fit 320x240 while preserving aspect
ratio. Later steps operate on that resized image. Blob coordinates refer to
the **clean mask**, which is the input to `blobs()`. `show()` scales them to the
displayed original; they are neither display coordinates nor automatically
coordinates of the file before resizing. `pixels_threshold` counts matching
pixels; `area_threshold` checks bounding-box area, both at processed resolution.

`max_blobs=16` bounds results. Check `truncated` before treating the count as
complete; the script prints it and adds `+` to the on-screen count when set.
Region details also print to the launching session's terminal.

Transforms leave their source unchanged and return new image handles. Analyses
such as `blobs()` return dictionaries. Every opened or transformed image needs
`image.close()`; the script's `finally` block releases all of its handles and
the graphics display on completion, interruption, or an exception.

For measurements, try `vision.statistics(smooth)["channels"]["gray"]`. For
operation timing and scratch usage, use `vision.process(smooth, "binary",
{"thresholds": [[0, 100]]})`; its dictionary includes `image`, `elapsed_us`,
and `workspace_peak_bytes`. Close that returned `image` too. Native timings
exclude source decoding, worker launch/cleanup, and interpreter result creation.

## Requirements

- SolarOS 4.16.0 or newer with Python, `media.image`, and `service.imlib`.
  The `vision` group selects imlib; the full flavor includes it on supported
  PSRAM boards. The script detects missing optional APIs before opening graphics.
- PSRAM and a graphic display of at least 128x96 pixels.
- Input through a keyboard, mapped buttons, or a displayd browser session.

Vision processing is bounded to 640x480 by the service; this example chooses
320x240 to keep its four native images small. Source decoding has its own
2-million-pixel limit. Images stay outside the MicroPython pixel heap. The
example uses classical imlib operations and does not require ESP32-S3 inference.
