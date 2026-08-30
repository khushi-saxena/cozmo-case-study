# Cozmo Case Study

Pipeline that turns a handheld iPhone capture into a dimensioned whole-property
floor plan with damage regions, scope line items, and a confidence interval on
every measurement. Three input tiers (photo, video, LiDAR) share one pipeline.

## Status

In progress. See `COMPLIANCE.csv` for requirement coverage.

## Install the capture app

TODO — timed on a clean checkout.

## Run

```
make run CAPTURE=benchmark/captures/<capture_id> TIER=<photo|video|lidar>
```

## Repo layout

```
ios/CozmoCapture/     capture app (Swift, ARKit)
pipeline/             ingest per tier, geometry, damage, uncertainty, render, schema
benchmark/            captures, ground truth, harness, runs
protocol/             capture protocol page, device matrix
reports/              technical report, benchmark report, fix declaration
scripts/              weight fetching, setup
```

## Disclosure

Pretrained models, datasets and APIs used are listed in
`reports/technical_report.md`. Everything runs locally with no calls to
external infrastructure.
