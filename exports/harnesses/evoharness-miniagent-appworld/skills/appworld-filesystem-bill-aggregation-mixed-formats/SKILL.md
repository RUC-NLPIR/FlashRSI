---
name: appworld-filesystem-bill-aggregation-mixed-formats
description: >-
  AppWorld file_system tasks that aggregate bills or financial documents over a
  date range. Use when a directory mixes .txt and .pdf bill files and an
  in-scope period appears only as a PDF, or when file_system.show_file returns
  a binary placeholder and the plan would skip PDF files as duplicates.
flashrsi:
  algorithm: evo_harness
  level: topic
  source_task_ids: [76f2c72_1]
---
# AppWorld file_system bill aggregation: include PDF bills too

When summing bills over a date range, every in-scope period must be accounted
for regardless of file format.

## Rules
- List all files in the directory and map each one to its billing period
  before summing.
- A `.pdf` bill is a real bill, not a duplicate of `.txt` bills. Do not skip
  it just because `file_system.show_file` returns binary content or a
  placeholder.
- If a required period appears only as a PDF, extract its amount with an
  appropriate PDF reader/parser before finalizing; do not silently omit that
  period.
- Sum only after every period in the requested range is covered.

## Verification
Before answering, confirm each period in the requested range has a
corresponding amount, including PDF-only periods. If any period is missing or
represented only by a skipped PDF, extract that PDF amount and recompute the
total.
