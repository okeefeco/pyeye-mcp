# Overview

The demo needs Python <!-- fact:begin demo.requires_python -->`>=3.11`<!-- fact:end -->.
A request times out after <!-- fact:begin demo.timeout -->`30`<!-- fact:end --> seconds.
Its storage backends are <!-- fact:begin demo.backends -->`memory`, `disk`<!-- fact:end -->.
It deploys to <!-- fact:begin demo.region -->`ap-southeast-2`<!-- fact:end --> with <!-- fact:begin demo.workers -->`4`<!-- fact:end --> workers.

Start it with <!-- fact:begin cli.script.demo -->`demo`<!-- fact:end --> or <!-- fact:begin cli.module.app -->`python -m app`<!-- fact:end -->:

<!-- fact:begin cli.all -->
| Command | Kind | Runs |
|---|---|---|
| `demo` | console script | `app.cli:main` |
| `python -m app` | module | `app` |
<!-- fact:end -->
