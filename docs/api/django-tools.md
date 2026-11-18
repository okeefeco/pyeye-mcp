# Django Tools

Tools for finding the parts of a Django project: models, views (Django REST
framework's too), URL configurations, templates and migrations.

The [plugin tools overview](README.md) says when these tools are available and
what every plugin tool shares: its parameters, its records and how the examples
work. Each tool's exact parameters are in
[MCP tools](../reference/tools.md#django). The examples below run against a small Django project.

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

The views of Django and of Django REST framework. It reads each `views.py`,
`viewsets.py` and `api.py`, and every module of a `views`, `viewsets` or `api`
package, in files that import `django` or `rest_framework`. Each record's
`framework` says which: `"django"` or `"rest_framework"`.

- **class-based views**: classes with a base the module imports from `django`
  or `rest_framework` whose name contains `View`, such as `ListView`,
  `generic.ListView`, `APIView`, `generics.ListAPIView` or
  `viewsets.ModelViewSet`; and every project class that subclasses one of
  those, directly or through your own classes, in any module. A class with a
  `rest_framework` base or ancestor is `rest_framework`. A mixin alone isn't a
  view, and neither is a project class whose name merely contains `View`.
- **function views**: functions decorated with `rest_framework`'s `@api_view`
  (`rest_framework`), and functions, `async` or not, whose first parameter is
  `request` (`django`).

Following subclasses uses the project's class graph, which `expand` with the
`subclasses` edge and `find_pydantic_models` share. The first call that needs
it builds it by reading every file in scope, so it is slower on a large
project; later calls reuse it until a file changes. A project with no class
views never builds it.

```json pyeye-example tool=find_django_views fixture=docs_examples_django
{}
```

```json pyeye-output
[{"name": "ProductList", "type": "class_view", "framework": "django",
  "handle": "shop.views.ProductList", "…": "<omitted>"},
 {"name": "product_detail", "type": "function_view", "framework": "django",
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
