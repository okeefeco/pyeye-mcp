# Pydantic Tools

Tools for finding Pydantic models and what shapes them: fields, validators,
computed fields and model configuration.

The [plugin tools overview](README.md) says when these tools are available and
what every plugin tool shares: its parameters, its records and how the examples
work. Each tool's exact parameters are in
[MCP tools](../reference/tools.md#pydantic). `get_model_schema` and `trace_model_inheritance` also take the `model_name` to
look up. The examples below run against a small project with one model, `User`.

The tools: <!-- fact:begin tools.plugin.pydantic -->`find_computed_fields`, `find_field_validators`, `find_model_config`, `find_pydantic_models`, `find_validators`, `get_model_schema`, `trace_model_inheritance`<!-- fact:end -->.

Each model's fields follow its own pydantic API: models built on
`pydantic.v1` (the v1 API that pydantic 2 ships) use v1 rules, and models
built on `pydantic.BaseModel` use the rules of the installed major version.
Under v1, a public attribute without an annotation (`x = 1`) is a field. Its
record has no `type`: `type` is absent when the field has no annotation. When
the rules can't be known (the version can't be read, or a v1 value can't be
classified), `fields` is left out rather than shown partial (#913, #935).

A model's configuration (`config` on a model or schema, `settings` from
`find_model_config`) is reported only when its `model_config` can be read in
full from source: a dict literal or a `ConfigDict(...)` /
`SettingsConfigDict(...)` call whose entries all have plain keys. When it can't
(a function call, a name, a `**` splat), the key is left out rather than shown
empty or partial (#870). A model with no configuration at all has `{}`.

## find_pydantic_models

Every model, with its fields, validators and base classes: the starting point
for understanding a project's data shapes.

A class whose base is an expression (`class M(make_base())`) can't be placed,
so pyeye can't tell whether it's a model and doesn't list it. Call with
`envelope=true` to see such classes: the envelope's `unplaced_classes` lists
every one in the searched scope (#921). That list is capped by `max_unplaced`;
`results` never is.

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

One model's parents and children, which fields it defines itself, and which it
inherits. This example shows a model whose only base is pydantic's `BaseModel`,
which declares no fields of its own.

```json pyeye-example tool=trace_model_inheritance
{"model_name": "User"}
```

```json pyeye-output
{"found": true, "model": "User", "parents": ["BaseModel"], "children": [],
 "fields_own": [{"name": "name", "…": "<omitted>"}, {"name": "email", "…": "<omitted>"}],
 "fields_inherited": [],
 "mro": ["myapp.schemas.User", "pydantic.main.BaseModel", "builtins.object"],
 "handle": "myapp.schemas.User", "…": "<omitted>"}
```
