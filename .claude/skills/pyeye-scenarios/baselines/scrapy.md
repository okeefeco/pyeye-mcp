---
date: 2026-11-23
command: pyeye-verify probe suite and task trial on scenario scrapy (pyeye-scenarios skill), project_path <TARGET>/scrapy
commit: f053174e
machine: dev01 (Linux, 8 GB)
---

# `scrapy` scenario baseline

The first record for Scrapy 2.20.0 (`4a421e45`), a plain single-tree project, captured by the first structured-verification run (#1140). Record a new baseline as a new record rather than editing this one.

## Probe suite + recorded baseline *(captured 2026-11-23, build `2.2.1.dev75+gf053174ea`)*

| # | Probe | Expected (baseline) | Demonstrates / tracking |
|---|-------|---------------------|-------------------------|
| 1 | `resolve("scrapy.Spider")` | `scrapy.spiders.Spider`, `class`, `project` | re-export collapses to the definition site |
| 2 | `outline("scrapy.linkextractors.lxmlhtml.LxmlLinkExtractor")` | 8 children; `_extract_links` has `signature: "_extract_links(self, *args: Any, **kwargs: Any) -> list[Link]"` | ✅ **#1125** (was an invented signature from the forwarded callee) |
| 3 | `expand("scrapy.spidermiddlewares.referer", "imports")` | 22 stubs; `warn` reported as `_warnings.warn` (`external`, `stub: true`); `scrapy.crawler.Crawler` and `scrapy.settings.BaseSettings` `type_only: true`; `unresolved_imports: []` | ✅ **#1133** closed: the `_warnings` name is the canonical site of `from warnings import warn`, not a stdlib node's imports; `type_only` (#1081) |
| 4 | the `scrapy.http.request.Request` stub in row 3 | `signature` cut at `headers: Mapping[str, Any]`, no closing paren | ❌ **#1159** (an annotation that spans lines truncates the signature). Also `scrapy.http.response.Response` |
| 5 | `expand("scrapy.linkextractors.lxmlhtml.LxmlLinkExtractor._link_allowed", "callees")` | 4 stubs, including `scrapy.linkextractors.lxmlhtml._has_extension` and not `scrapy.utils.url.url_has_any_extension`; `unresolved_call_sites: 0` | the task trial's structural proof |

## Round-trip probe

`scripts/roundtrip_probe.py <TARGET>/scrapy scrapy.spidermiddlewares.referer`: 22 stubs, **0** don't round-trip.

## Task trial

The discovery task: "Is there an existing helper that checks whether a URL's path ends in one of a given set of file extensions? Name every such helper by its full dotted path, and say which one `LxmlLinkExtractor` actually uses to filter links."

Ground truth: the public `scrapy.utils.url.url_has_any_extension`, and the private `scrapy.linkextractors.lxmlhtml._has_extension`. `LxmlLinkExtractor._link_allowed` uses `_has_extension`.

| Arm | Correct | Turns | Tokens | Time |
|-----|---------|-------|--------|------|
| grep-only control | yes, both helpers, the right one used | 8 | 209,335 | 32 s |
| `python-explore` skill + pyeye | yes, both helpers, the right one used, proved by `callees` with no unresolved call sites | 10 | 245,611 | 32 s |
