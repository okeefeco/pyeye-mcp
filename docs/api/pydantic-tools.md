# Pydantic Tools

Tools for finding Pydantic models and what shapes them: fields, validators,
computed fields and model configuration. They're available once Pydantic is
detected in the project or in one of its configured packages.

- **Parameters:** every tool takes `scope`, `envelope` and `project_path`
  ([Every plugin tool](README.md#every-plugin-tool)); `get_model_schema` and
  `trace_model_inheritance` also take the `model_name` to look up. The exact
  parameters and defaults are generated in
  [MCP tools](../reference/tools.md#pydantic).
- **Examples:** each example below runs in CI against a small project with one
  model, `User`, and its output is checked against the real response (`…` marks
  what's left out). A record that names a symbol carries a `handle` you can pass
  to `inspect`, `outline`, `expand` or `trace`.

The tools: <!-- fact:begin tools.plugin.pydantic -->`find_computed_fields`, `find_field_validators`, `find_model_config`, `find_pydantic_models`, `find_validators`, `get_model_schema`, `trace_model_inheritance`<!-- fact:end -->.

Two fields of `trace_model_inheritance`'s result are known to come back empty
when they shouldn't (#870): `mro` and `fields_inherited`. The examples leave
them out.

A model's configuration (`config` on a model or schema, `settings` from
`find_model_config`) is reported only when its `model_config` can be read in
full from source: a dict literal or a `ConfigDict(...)` /
`SettingsConfigDict(...)` call whose entries all have plain keys. When it can't
(a function call, a name, a `**` splat), the key is left out rather than shown
empty or partial (#870). A model with no configuration at all has `{}`.

## find_pydantic_models

Every model, with its fields, validators and base classes: the starting point
for understanding a project's data shapes.

```json pyeye-example tool=find_pydantic_models
{}
```

```json pyeye-output
[{"name": "User", "type": "pydantic_model", "handle": "myapp.schemas.User",
  "fields": [{"name": "name", "type": "str", "required": true, "…": "<omitted>"},
             {"name": "email", "type": "str", "required": true, "…": "<omitted>"}],
  "validators": ["email_has_at"], "base_classes": ["BaseModel"],
  "…": "<omitted>"}]
```

## get_model_schema

One model's fields, split into required and optional, with its validators.

```json pyeye-example tool=get_model_schema
{"model_name": "User"}
```

```json pyeye-output
{"found": true, "model": "User", "handle": "myapp.schemas.User",
 "required": [{"name": "name", "…": "<omitted>"}, {"name": "email", "…": "<omitted>"}],
 "optional": [], "validators": ["email_has_at"], "…": "<omitted>"}
```

## find_validators

Every validator on every model, with the fields it checks and when it runs.

```json pyeye-example tool=find_validators
{}
```

```json pyeye-output
[{"name": "email_has_at", "type": "field_validator", "fields": ["email"],
  "mode": "after", "handle": "myapp.schemas.User.email_has_at", "…": "<omitted>"}]
```

## find_field_validators

The field validators only, for when you want to know what checks a given field.

```json pyeye-example tool=find_field_validators
{}
```

```json pyeye-output
[{"name": "email_has_at", "fields": ["email"], "…": "<omitted>"}]
```

## find_model_config

The models that set a configuration, and where.

```json pyeye-example tool=find_model_config
{}
```

```json pyeye-output
[{"model": "User", "handle": "myapp.schemas.User", "…": "<omitted>"}]
```

## find_computed_fields

The computed fields: values a model derives rather than accepts.

```json pyeye-example tool=find_computed_fields
{}
```

```json pyeye-output
[{"name": "domain", "type": "computed_field", "return_type": "str",
  "handle": "myapp.schemas.User.domain", "…": "<omitted>"}]
```

## trace_model_inheritance

One model's parents and children, and which fields it defines itself.

```json pyeye-example tool=trace_model_inheritance
{"model_name": "User"}
```

```json pyeye-output
{"found": true, "model": "User", "parents": ["BaseModel"], "children": [],
 "fields_own": [{"name": "name", "…": "<omitted>"}, {"name": "email", "…": "<omitted>"}],
 "handle": "myapp.schemas.User", "…": "<omitted>"}
```
