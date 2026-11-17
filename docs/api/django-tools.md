# Django Tools

Tools for finding the parts of a Django project: models, views, URL
configurations, templates and migrations. They're available once Django is
detected in the project or in one of its configured packages.

- **Parameters:** every tool takes `scope`, `envelope` and `project_path`
  ([Every plugin tool](README.md#every-plugin-tool)); the exact parameters and
  defaults are generated in [MCP tools](../reference/tools.md#django).
- **Examples:** each example below runs in CI against a small Django project,
  and its output is checked against the real response (`…` marks what's left
  out). A record that names a symbol carries a `handle` you can pass to
  `inspect`, `outline`, `expand` or `trace`; a file record has none.

The tools: <!-- fact:begin tools.plugin.django -->`find_django_migrations`, `find_django_models`, `find_django_templates`, `find_django_urls`, `find_django_views`<!-- fact:end -->.

## find_django_models

The model classes, found in each app's `models.py`. Expand a model's handle to
see its fields.

```json pyeye-example tool=find_django_models fixture=docs_examples_django
{}
```

```json pyeye-output
[{"name": "Product", "type": "django_model", "handle": "shop.models.Product",
  "…": "<omitted>"}]
```

## find_django_views

The views in each app's `views.py`: class-based views and function views.

```json pyeye-example tool=find_django_views fixture=docs_examples_django
{}
```

```json pyeye-output
[{"name": "ProductList", "type": "class_view", "handle": "shop.views.ProductList",
  "…": "<omitted>"},
 {"name": "product_detail", "type": "function_view",
  "handle": "shop.views.product_detail", "…": "<omitted>"}]
```

## find_django_urls

The URL configuration files. Each is a file record, so open the file, or
`outline` its module, to read the patterns.

```json pyeye-example tool=find_django_urls fixture=docs_examples_django
{}
```

```json pyeye-output
[{"type": "url_config", "handle": "<absent>", "…": "<omitted>"}]
```

## find_django_templates

The template files under the project's template directories.

```json pyeye-example tool=find_django_templates fixture=docs_examples_django
{}
```

```json pyeye-output
[{"name": "detail.html", "type": "template", "…": "<omitted>"}]
```

## find_django_migrations

The migration files, with the app each belongs to, so you can see each app's
migration history.

```json pyeye-example tool=find_django_migrations fixture=docs_examples_django
{}
```

```json pyeye-output
[{"name": "0001_initial", "app": "shop", "type": "migration", "…": "<omitted>"}]
```
