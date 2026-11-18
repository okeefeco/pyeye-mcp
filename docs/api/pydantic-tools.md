# Pydantic Tools

Tools for finding Pydantic models and what shapes them: fields, validators,
computed fields and model configuration.

The [plugin tools overview](README.md) says when these tools are available and
what every plugin tool shares: its parameters, its records and how the examples
work. Each tool's exact parameters are in
[MCP tools](../reference/tools.md#pydantic). `get_model_schema` and `trace_model_inheritance` also take the `model_name` to
look up. The examples below run against a small project with one model, `User`.

The tools: <!-- fact:begin tools.plugin.pydantic -->`find_computed_fields`, `find_field_validators`, `find_model_config`, `find_pydantic_models`, `find_validators`, `get_model_schema`, `trace_model_inheritance`<!-- fact:end -->.

Two fields of `trace_model_inheritance`'s result are known to come back empty
when they shouldn't (#870): `mro` and `fields_inherited`. The examples leave
them out.

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
