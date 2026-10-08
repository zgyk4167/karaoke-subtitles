# ASS style

These values define the look of the output. Change them only when the user asks. They live in `HEADER`, `GREEN`, `WHITE`, `BLUE` and `POP_*` in `scripts/pipeline.py`.

Colors are `&HAABBGGRR` (alpha, blue, green, red).

| Setting | Value | Where |
|---|---|---|
| Spoken (fill) color | `&H0000FF00` green | Style PrimaryColour |
| Unspoken color | `&H00FFFFFF` white | Style SecondaryColour |
| Outline | black, 4 px | OutlineColour / Outline |
| Font | Noto Sans CJK SC, 64, bold | Fontname / Fontsize |
| Position | bottom center, MarginV 70 | Alignment 2 |
| Gloss color | `&HFFA030&` (RGB 48,160,255 blue) | inline `\1c` + `\2c` |

## Line breaking
A new subtitle line starts at a sentence end, after 7 words, past 42 characters, or at a pause longer than 1.2 s (`MAXW`, `MAXC`, `PAUSE`).

Lines shorter than 1.0 s (`MIN_LINE`) are fixed in this order:
1. If the line continues a sentence from the previous line, words move over from the end of the previous line.
2. If the result still fits 7 words and 42 characters, the line joins the next line or the previous line. The gap must be 1.2 s or less.

Each line stays on screen 0.4 s after its last word (`TAIL`), and at least 1.0 s in total, but never past the start of the next line. In very fast speech, a line that cannot be joined can therefore stay on screen for less than 1.0 s.

## Per-word karaoke
`{\k<centiseconds>}word`: the word switches from SecondaryColour to PrimaryColour when its turn comes. Gaps between words become empty `{\kN}`.

## Pop effect
Per word, times in ms relative to line start:
```
{\k24\fscx100\fscy100\t(t1,t1+90,\fscx122\fscy122)\t(t2,t2+120,\fscx100\fscy100)}word{\fscx100\fscy100}
```
t1 = word start, t2 = word end. Change 122 for a bigger/smaller pop.

## Gloss
Inserted after the last word of the term (`gloss` is the Chinese text). Sometimes the term crosses a line break, or the model gives a neighbouring line number. The gloss then goes after the term's last word, on whichever line holds that word.
```
{\k0\1c&HFFA030&\2c&HFFA030&}[gloss]{\1c&H0000FF00&\2c&H00FFFFFF&}
```

## Burn-in
`ffmpeg -i in.mp4 -vf "ass=subs.ass:fontsdir=assets/fonts" -c:v libx264 -preset veryfast -crf 22 -c:a copy out.mp4`
For segment renders: `-ss S -t D -vf "setpts=PTS+S/TB,ass=...,setpts=PTS-STARTPTS"` keeps subtitle timing aligned.
