# Task: Add a rule-based document-level split detector

I need you to implement a **rule-based PDF split detector** for my current project.

The goal is simple:

> For each document, decide whether the whole document should be split into left/right logical pages.

This is **not** a page-type classifier.
Do **not** use Qwen, VLM, LLM, OCR semantic reasoning, page-role recognition, advertisement detection, or page-number recognition in this module.

This module should only answer:

```json
{
  "should_split": true,
  "split_axis": "vertical",
  "split_position_norm": 0.5
}
```

or:

```json
{
  "should_split": false,
  "split_axis": null,
  "split_position_norm": null
}
```

---

## Important design principle

The decision is **document-level**, not page-level.

If a magazine PDF is stored as two-page spreads, then the whole document should be split consistently.
Do not decide separately for every page.

The module should sample a few pages, let them vote, then make one final decision for the whole document.

---

## What I want

Please implement a script, preferably:

```text
src/detect_document_split_mode.py
```

or another reasonable location if the current project structure suggests one.

The script should take a PDF or rendered page-image directory as input and output a JSON decision file.

Example CLI:

```bash
python src/detect_document_split_mode.py \
  --input data/incoming/CERNCourier2022NovDec-digitaledition.pdf \
  --out output/split_decisions/CERNCourier2022NovDec-digitaledition/split_decision.json
```

If my current project already stores rendered page images in something like:

```text
output/render_result/<doc_id>/page_0001.png
```

or similar, support that too if easy.

---

## Output JSON

The final output should be something like:

```json
{
  "document_id": "CERNCourier2022NovDec-digitaledition",
  "should_split": true,
  "split_axis": "vertical",
  "split_position_norm": 0.5,
  "decision_level": "document",
  "method": "rule_based_visual_vote",
  "sample_count": 5,
  "votes_for_split": 4,
  "threshold_votes": 3,
  "confidence": 0.8,
  "sampled_pages": [
    {
      "page_index": 0,
      "aspect_ratio": 1.41,
      "aspect_ratio_candidate": true,
      "ink_valley_score": 0.73,
      "edge_valley_score": 0.68,
      "left_right_independence_score": 0.81,
      "visual_score": 0.74,
      "vote_split": true
    }
  ]
}
```

The downstream pipeline only needs:

```json
{
  "should_split": true,
  "split_axis": "vertical",
  "split_position_norm": 0.5
}
```

But please keep debug fields in the JSON because I need to inspect why the decision was made.

---

## Sampling strategy

Use 5 sampled pages per document.

Preferred sample positions:

```text
0%, 25%, 50%, 75%, 100%
```

or:

```text
first page, three evenly spaced middle pages, last page
```

Make sure duplicate indices are removed for short PDFs.

Example:

```python
sample_indices = sorted(set([
    0,
    round(0.25 * (num_pages - 1)),
    round(0.50 * (num_pages - 1)),
    round(0.75 * (num_pages - 1)),
    num_pages - 1
]))
```

If the PDF has fewer than 5 pages, just use all pages.

---

## Decision logic

The page aspect ratio is only a **precondition / candidate filter**.

Do not decide only from width / height.

For each sampled page:

1. Render page to image if input is a PDF.
2. Compute aspect ratio.
3. If aspect ratio is obviously not compatible with two portrait pages side by side, the page should not vote for split.
4. If aspect ratio is plausible, compute visual features:

   * center ink-density valley
   * center Canny edge-density valley
   * left/right independence score
5. Combine these into a visual score.
6. The sampled page votes for split if the visual score passes a threshold.
7. The document should be split if enough sampled pages vote for split.

Suggested thresholds:

```python
ASPECT_MIN = 1.15
ASPECT_MAX = 1.75
VISUAL_SCORE_THRESHOLD = 0.55
VOTE_THRESHOLD = 3
```

So for 5 sampled pages:

```text
>= 3 votes → should_split = true
< 3 votes → should_split = false
```

If you think 4/5 is safer, make it configurable. Default can be 3.

---

## If should_split is true

The split should be:

```json
{
  "split_axis": "vertical",
  "split_position_norm": 0.5
}
```

Do not try to estimate a different split position for each page.

For now, I want only center vertical split.

Do not handle horizontal split in the first version.

---

## Feature 1: center ink-density valley

Convert page image to a foreground mask:

```text
foreground / ink / text / image content = 1
background = 0
```

Use grayscale + Otsu threshold or another robust method.

Suggested implementation:

```python
gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
gray = cv2.GaussianBlur(gray, (3, 3), 0)

_, bw = cv2.threshold(
    gray, 0, 255,
    cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
)

kernel = np.ones((2, 2), np.uint8)
bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel)

mask = (bw > 0).astype(np.uint8)
```

Then crop out top and bottom margins before calculating density:

```python
h, w = mask.shape
y0 = int(0.08 * h)
y1 = int(0.92 * h)
work = mask[y0:y1, :]
```

Calculate column density:

```python
col_density = work.mean(axis=0)
```

Define left, center, right bands:

```python
left_band   = col_density[int(0.20*w):int(0.42*w)]
center_band = col_density[int(0.46*w):int(0.54*w)]
right_band  = col_density[int(0.58*w):int(0.80*w)]
```

Use:

```python
left_density = median(left_band)
right_density = median(right_band)
side_density = min(left_density, right_density)
center_density = percentile(center_band, 20)
```

Then:

```python
ink_valley_score = 1 - center_density / (side_density + eps)
```

Clip to `[0, 1]`.

If left or right has almost no content, return score 0:

```python
if left_density < 0.015 or right_density < 0.015:
    ink_valley_score = 0
```

The intuition:

```text
left page content | low-density center gutter | right page content
```

A high score means the middle is much emptier than both sides.

---

## Feature 2: center Canny edge-density valley

Use Canny edges to measure whether the center area has fewer text/image edges than left and right.

Suggested implementation:

```python
edges = cv2.Canny(gray, 50, 150)
edges = (edges > 0).astype(np.uint8)
```

Again crop top and bottom:

```python
work_edges = edges[y0:y1, :]
edge_col_density = work_edges.mean(axis=0)
```

Use the same bands:

```python
left_edge = median(edge_col_density[20%-42%])
center_edge = percentile(edge_col_density[46%-54%], 20)
right_edge = median(edge_col_density[58%-80%])
side_edge = min(left_edge, right_edge)
```

Then:

```python
edge_valley_score = 1 - center_edge / (side_edge + eps)
```

Clip to `[0, 1]`.

Again, if both sides have too little edge content, return 0.

This is useful for pure text pages where the middle gutter is white but there is no dark binding line.

---

## Feature 3: left/right independence score

The idea is:

```text
A two-page spread usually has content on both the left and right side,
but relatively little content in the center.
```

Use the ink mask.

Possible simple implementation:

```python
left_content = mean(mask[:, 0.05w:0.45w])
center_content = mean(mask[:, 0.46w:0.54w])
right_content = mean(mask[:, 0.55w:0.95w])
```

Then compute:

```python
both_sides_have_content = min(left_content, right_content)
center_is_lower = 1 - center_content / (both_sides_have_content + eps)
```

Clip to `[0, 1]`.

If one side has almost no content, score should be low.

---

## Combine visual scores

Suggested weighted score:

```python
visual_score = (
    0.45 * ink_valley_score
    + 0.35 * edge_valley_score
    + 0.20 * left_right_independence_score
)
```

Then:

```python
vote_split = aspect_ratio_candidate and visual_score >= VISUAL_SCORE_THRESHOLD
```

Important:

* Aspect ratio is only a candidate filter.
* The actual vote should come from visual structure.
* Do not split just because the page is landscape.
* Do not use page semantics.

---

## Rendering PDF pages

If input is a PDF, render sampled pages to images. Use PyMuPDF if available:

```python
import fitz

doc = fitz.open(pdf_path)
page = doc[page_index]
pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
```

Then convert to OpenCV BGR or RGB array.

Rendering at moderate resolution is enough. No need for high DPI.

---

## Error handling

Please make the script robust:

* If input path does not exist, raise a clear error.
* If PDF has zero pages, raise a clear error.
* If OpenCV/PyMuPDF is missing, print a helpful message.
* Create output directory automatically.
* Write valid UTF-8 JSON with `ensure_ascii=False` and indentation.

---

## What this module should NOT do

Do not implement these here:

* Qwen / VLM inference
* page role classification
* cover / table of contents / advertisement detection
* page number OCR
* evidence graph construction
* article segmentation
* actual cropping of all pages

This module only decides whether the document should be split.

Actual splitting can be implemented in a later script using:

```json
{
  "should_split": true,
  "split_axis": "vertical",
  "split_position_norm": 0.5
}
```

---

## Please also provide

After implementation, please show me:

1. The created/modified files.
2. The exact command to run on one PDF.
3. An example output JSON.
4. Any assumptions you made about input paths or rendered page image format.

Keep the implementation simple and conservative.
