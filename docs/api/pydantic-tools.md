# Pydantic Tools

Specialized tools for analyzing Pydantic models, validators, and schemas. These 7 tools are automatically activated when Pydantic is detected in your project.

## Table of Contents

1. [find_models](#find_models)
2. [get_model_schema](#get_model_schema)
3. [find_validators](#find_validators)
4. [find_field_validators](#find_field_validators)
5. [find_model_config](#find_model_config)
6. [trace_model_inheritance](#trace_model_inheritance)
7. [find_computed_fields](#find_computed_fields)

---

## find_models

Find all Pydantic models in the project.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  name: string;              // Model class name
  file: string;              // File path
  line: number;              // Line number of class definition
  base_class: string;        // Direct parent (BaseModel, etc.)
  fields: Array<{
    name: string;           // Field name
    type: string;           // Field type annotation
    required: boolean;      // Whether field is required
    default: any;           // Default value if set
    alias: string;          // Field alias if different
    description: string;    // Field description from Field()
  }>;
  validators: string[];      // List of validator method names
  config_class: boolean;     // Has Config inner class
  schema_extra: boolean;     // Has schema_extra defined
}>
```

### Examples

```python
# Find all Pydantic models
models = find_models()
# Returns: [
#   {
#     "name": "UserModel",
#     "file": "/project/models/user.py",
#     "line": 10,
#     "base_class": "BaseModel",
#     "fields": [
#       {
#         "name": "email",
#         "type": "EmailStr",
#         "required": true,
#         "default": null,
#         "alias": "email_address",
#         "description": "User's email address"
#       },
#       {
#         "name": "age",
#         "type": "Optional[int]",
#         "required": false,
#         "default": null,
#         "alias": "age",
#         "description": ""
#       }
#     ],
#     "validators": ["validate_email", "validate_age"],
#     "config_class": true,
#     "schema_extra": false
#   },
#   {
#     "name": "ProductModel",
#     "file": "/project/models/product.py",
#     "line": 5,
#     "base_class": "BaseModel",
#     "fields": [...],
#     "validators": [],
#     "config_class": false,
#     "schema_extra": true
#   }
# ]

# Filter models with validators
models_with_validators = [m for m in find_models() if m["validators"]]
```

### Error Conditions

- Returns empty array if no Pydantic models found
- Skips files with syntax errors
- May miss dynamically created models

### Performance Notes

- Scans all Python files in project
- Caches results until files change
- Auto-activated when Pydantic imported

### Use Cases

- Model inventory and documentation
- Finding models without validation
- Schema generation
- Migration planning
- Test coverage analysis

---

## get_model_schema

Get the complete schema for a specific Pydantic model.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `model_name` | string | ✅ | - | Name of the Pydantic model class |

### Returns

```typescript
{
  model_name: string;
  file: string;
  line: number;

  schema: {
    title: string;                    // Model title
    type: "object";
    description: string;              // Model description
    properties: {
      [field_name: string]: {
        title: string;               // Field title
        type: string | string[];     // JSON Schema type(s)
        description: string;         // Field description
        default: any;               // Default value
        examples: any[];            // Example values
        minimum: number;            // For numeric types
        maximum: number;            // For numeric types
        minLength: number;          // For string types
        maxLength: number;          // For string types
        pattern: string;            // Regex pattern
        enum: any[];               // Allowed values
        format: string;            // Format hint (email, date-time, etc.)
        $ref: string;              // Reference to another schema
      }
    };
    required: string[];              // Required field names
    additionalProperties: boolean;   // Allow extra fields
    examples: any[];                // Model-level examples
  };

  config: {
    frozen: boolean;                 // Immutable model
    validate_assignment: boolean;    // Validate on attribute assignment
    use_enum_values: boolean;       // Use enum values vs names
    arbitrary_types_allowed: boolean;
    orm_mode: boolean;              // Allow ORM object input
    allow_population_by_field_name: boolean;
    json_encoders: object;          // Custom JSON encoders
    schema_extra: object;           // Extra schema metadata
  };

  methods: Array<{
    name: string;
    type: "validator" | "root_validator" | "field_validator" | "model_validator";
    fields: string[];               // Fields this validator applies to
    pre: boolean;                  // Pre-validation
  }>;

  inheritance: {
    bases: string[];                // Parent models
    inherited_fields: string[];     // Fields from parents
    overridden_fields: string[];    // Fields overridden from parents
  };
}
```

### Examples

```python
# Get schema for a model
schema = get_model_schema("UserModel")
# Returns: {
#   "model_name": "UserModel",
#   "file": "/project/models/user.py",
#   "line": 10,
#
#   "schema": {
#     "title": "UserModel",
#     "type": "object",
#     "description": "Represents a system user",
#     "properties": {
#       "email": {
#         "title": "Email Address",
#         "type": "string",
#         "description": "User's primary email",
#         "format": "email",
#         "minLength": 5,
#         "maxLength": 255
#       },
#       "age": {
#         "title": "Age",
#         "type": ["integer", "null"],
#         "description": "User's age in years",
#         "minimum": 0,
#         "maximum": 150,
#         "default": null
#       },
#       "role": {
#         "title": "Role",
#         "type": "string",
#         "enum": ["admin", "user", "guest"],
#         "default": "user"
#       }
#     },
#     "required": ["email"],
#     "additionalProperties": false
#   },
#
#   "config": {
#     "frozen": false,
#     "validate_assignment": true,
#     "use_enum_values": true,
#     "orm_mode": true,
#     "allow_population_by_field_name": true
#   },
#
#   "methods": [
#     {
#       "name": "validate_email",
#       "type": "field_validator",
#       "fields": ["email"],
#       "pre": false
#     }
#   ],
#
#   "inheritance": {
#     "bases": ["BaseUser"],
#     "inherited_fields": ["id", "created_at"],
#     "overridden_fields": ["email"]
#   }
# }

# Generate OpenAPI schema
schema = get_model_schema("RequestModel")
openapi_schema = schema["schema"]  # Can be used directly in OpenAPI specs
```

### Error Conditions

- Raises error if model not found
- Returns partial schema for complex types
- May not capture runtime schema modifications

### Performance Notes

- Analyzes model definition and inheritance
- Caches schema per model
- More expensive than find_models

### Use Cases

- API documentation generation
- Schema validation
- OpenAPI/Swagger generation
- Model comparison
- Migration validation

---

## find_validators

Find all Pydantic validators in the project.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  model: string;             // Model class name
  file: string;              // File path
  validators: Array<{
    name: string;           // Validator method name
    line: number;           // Line number
    type: string;           // "validator", "root_validator", "field_validator", "model_validator"
    fields: string[];       // Fields being validated (empty for root/model)
    pre: boolean;           // Pre-validation flag
    always: boolean;        // Always run even if value not provided
    each_item: boolean;     // Validate each item in sequence
    check_fields: boolean;  // Check field existence (root_validator)
    mode: string;           // Validation mode (v2)
    decorator: string;      // Full decorator string
  }>;
}>
```

### Examples

```python
# Find all validators
validators = find_validators()
# Returns: [
#   {
#     "model": "UserModel",
#     "file": "/project/models/user.py",
#     "validators": [
#       {
#         "name": "validate_email",
#         "line": 25,
#         "type": "field_validator",
#         "fields": ["email"],
#         "pre": false,
#         "always": true,
#         "each_item": false,
#         "decorator": "@field_validator('email', mode='after')"
#       },
#       {
#         "name": "validate_age_range",
#         "line": 35,
#         "type": "field_validator",
#         "fields": ["age"],
#         "pre": true,
#         "always": false,
#         "decorator": "@field_validator('age', mode='before')"
#       },
#       {
#         "name": "validate_consistency",
#         "line": 45,
#         "type": "model_validator",
#         "fields": [],
#         "mode": "after",
#         "decorator": "@model_validator(mode='after')"
#       }
#     ]
#   }
# ]

# Find pre-validators only
pre_validators = []
for model_validators in find_validators():
    for v in model_validators["validators"]:
        if v["pre"]:
            pre_validators.append(v)
```

### Error Conditions

- Returns empty array if no validators found
- May miss dynamically added validators
- Handles both Pydantic v1 and v2 syntax

### Performance Notes

- Scans model definitions
- Lightweight operation
- Cached with model analysis

### Use Cases

- Validation audit
- Finding missing validators
- Documentation generation
- Migration from v1 to v2
- Test coverage planning

---

## find_field_validators

Find all field-specific validators across all models.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  field_name: string;        // Field being validated
  models: Array<{
    model_name: string;      // Model containing this field
    file: string;           // File path
    validators: Array<{
      name: string;         // Validator method name
      line: number;         // Line number
      pre: boolean;         // Pre-validation
      always: boolean;      // Always validate
      custom_message: string; // Custom error message if defined
    }>;
  }>;
  total_validators: number;  // Total validators for this field
  patterns: string[];       // Common validation patterns detected
}>
```

### Examples

```python
# Find all field validators grouped by field name
field_validators = find_field_validators()
# Returns: [
#   {
#     "field_name": "email",
#     "models": [
#       {
#         "model_name": "UserModel",
#         "file": "/project/models/user.py",
#         "validators": [
#           {
#             "name": "validate_email_format",
#             "line": 30,
#             "pre": false,
#             "always": true,
#             "custom_message": "Invalid email format"
#           },
#           {
#             "name": "validate_email_domain",
#             "line": 40,
#             "pre": false,
#             "always": true
#           }
#         ]
#       },
#       {
#         "model_name": "ContactModel",
#         "file": "/project/models/contact.py",
#         "validators": [...]
#       }
#     ],
#     "total_validators": 3,
#     "patterns": ["email_format", "domain_check"]
#   },
#   {
#     "field_name": "password",
#     "models": [...],
#     "total_validators": 5,
#     "patterns": ["length_check", "complexity", "common_password"]
#   }
# ]

# Find fields with most validators (complex validation)
complex_fields = sorted(
    field_validators,
    key=lambda x: x["total_validators"],
    reverse=True
)[:5]
```

### Error Conditions

- Returns empty array if no field validators found
- Groups by exact field name match
- May miss renamed/aliased fields

### Performance Notes

- Builds on find_validators results
- Groups and aggregates efficiently
- Useful for cross-model analysis

### Use Cases

- Validation consistency checks
- Finding under-validated fields
- Standardizing validation patterns
- Cross-model validation audit
- Validation refactoring

---

## find_model_config

Find all model configurations across Pydantic models.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  model: string;              // Model class name
  file: string;              // File path
  line: number;              // Line number of Config class
  config: {
    frozen: boolean;          // Immutable instances
    validate_assignment: boolean;
    use_enum_values: boolean;
    arbitrary_types_allowed: boolean;
    orm_mode: boolean;        // v1 compatibility
    from_attributes: boolean; // v2 equivalent of orm_mode
    populate_by_name: boolean;
    allow_population_by_field_name: boolean; // v1
    json_encoders: object;    // Custom encoders
    json_schema_extra: object;
    model_config: object;     // v2 style config dict
    extra: string;           // "allow", "forbid", "ignore"
    validate_default: boolean;
    strict: boolean;         // Strict mode (v2)
    frozen: boolean;
    ser_json_timedelta: string;
    ser_json_bytes: string;
    validate_return: boolean;
    revalidate_instances: string;
    title: string;           // Model title
    str_strip_whitespace: boolean;
    str_to_lower: boolean;
    str_to_upper: boolean;
  };
  version: "v1" | "v2";      // Pydantic version style
}>
```

### Examples

```python
# Find all model configurations
configs = find_model_config()
# Returns: [
#   {
#     "model": "UserModel",
#     "file": "/project/models/user.py",
#     "line": 50,
#     "config": {
#       "frozen": false,
#       "validate_assignment": true,
#       "use_enum_values": true,
#       "orm_mode": true,
#       "extra": "forbid",
#       "json_encoders": {
#         "datetime": "lambda dt: dt.isoformat()"
#       },
#       "str_strip_whitespace": true,
#       "validate_default": true
#     },
#     "version": "v1"
#   },
#   {
#     "model": "ProductModel",
#     "file": "/project/models/product.py",
#     "line": 30,
#     "config": {
#       "from_attributes": true,  // v2 style
#       "strict": true,
#       "frozen": true,
#       "extra": "allow",
#       "ser_json_timedelta": "iso8601"
#     },
#     "version": "v2"
#   }
# ]

# Find models with strict validation
strict_models = [c for c in configs if c["config"].get("strict") or c["config"].get("extra") == "forbid"]

# Find v1 models needing migration
v1_models = [c for c in configs if c["version"] == "v1"]
```

### Error Conditions

- Returns default config if none specified
- Handles both v1 Config class and v2 model_config
- May miss runtime config changes

### Performance Notes

- Lightweight parsing operation
- Cached with model analysis
- Detects Pydantic version automatically

### Use Cases

- Configuration audit
- v1 to v2 migration planning
- Standardizing model configs
- Security review (extra fields)
- Performance tuning

---

## trace_model_inheritance

Trace the inheritance hierarchy of a Pydantic model.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `model_name` | string | ✅ | - | Name of the Pydantic model class to trace |

### Returns

```typescript
{
  model: string;                    // Target model name
  file: string;                    // File containing model
  line: number;                    // Line number

  hierarchy: {
    parents: Array<{               // Direct parent classes
      name: string;
      file: string;
      line: number;
      is_pydantic: boolean;        // Is a Pydantic model
      fields: string[];            // Fields defined in parent
    }>;

    ancestors: Array<{             // All ancestors (recursive)
      name: string;
      file: string;
      level: number;               // Distance from target model
      path: string[];              // Inheritance path
    }>;

    children: Array<{              // Direct child classes
      name: string;
      file: string;
      line: number;
      fields_added: string[];      // New fields in child
      fields_overridden: string[];  // Overridden fields
    }>;

    descendants: Array<{           // All descendants (recursive)
      name: string;
      file: string;
      level: number;
      path: string[];
    }>;
  };

  field_inheritance: {
    inherited: Array<{             // Fields from parents
      field_name: string;
      from_model: string;
      type: string;
      overridden: boolean;
    }>;

    defined: string[];             // Fields defined in this model
    overridden: string[];          // Fields overridden from parents
    final_fields: string[];        // All fields after inheritance
  };

  method_inheritance: {
    validators: Array<{
      name: string;
      from_model: string;
      overridden: boolean;
    }>;

    methods: Array<{
      name: string;
      from_model: string;
      overridden: boolean;
    }>;
  };

  mro: string[];                   // Method Resolution Order
}
```

### Examples

```python
# Trace model inheritance
hierarchy = trace_model_inheritance("UserModel")
# Returns: {
#   "model": "UserModel",
#   "file": "/project/models/user.py",
#   "line": 20,
#
#   "hierarchy": {
#     "parents": [
#       {
#         "name": "BaseUser",
#         "file": "/project/models/base.py",
#         "line": 10,
#         "is_pydantic": true,
#         "fields": ["id", "created_at", "updated_at"]
#       },
#       {
#         "name": "TimestampMixin",
#         "file": "/project/models/mixins.py",
#         "line": 5,
#         "is_pydantic": true,
#         "fields": ["timestamp"]
#       }
#     ],
#
#     "ancestors": [
#       {"name": "BaseUser", "level": 1, "path": ["UserModel", "BaseUser"]},
#       {"name": "BaseModel", "level": 2, "path": ["UserModel", "BaseUser", "BaseModel"]}
#     ],
#
#     "children": [
#       {
#         "name": "AdminUser",
#         "file": "/project/models/admin.py",
#         "line": 15,
#         "fields_added": ["permissions", "admin_level"],
#         "fields_overridden": ["role"]
#       }
#     ],
#
#     "descendants": [
#       {"name": "AdminUser", "level": 1, "path": ["UserModel", "AdminUser"]},
#       {"name": "SuperAdmin", "level": 2, "path": ["UserModel", "AdminUser", "SuperAdmin"]}
#     ]
#   },
#
#   "field_inheritance": {
#     "inherited": [
#       {"field_name": "id", "from_model": "BaseUser", "type": "UUID", "overridden": false},
#       {"field_name": "created_at", "from_model": "BaseUser", "type": "datetime", "overridden": false}
#     ],
#     "defined": ["email", "username", "password"],
#     "overridden": ["updated_at"],
#     "final_fields": ["id", "created_at", "updated_at", "email", "username", "password", "timestamp"]
#   },
#
#   "mro": ["UserModel", "BaseUser", "TimestampMixin", "BaseModel", "object"]
# }

# Find all models in hierarchy
hierarchy = trace_model_inheritance("BaseModel")
all_descendants = hierarchy["hierarchy"]["descendants"]
print(f"BaseModel has {len(all_descendants)} descendant models")
```

### Error Conditions

- Raises error if model not found
- Handles multiple inheritance
- May miss dynamic class creation

### Performance Notes

- Recursively traces inheritance
- Can be slow for deep hierarchies
- Caches hierarchy per model

### Use Cases

- Understanding model relationships
- Impact analysis for changes
- Documentation generation
- Refactoring planning
- Finding common base classes

---

## find_computed_fields

Find all computed fields (properties, computed_field decorator) in Pydantic models.

### Parameters

None - searches entire project in current directory.

### Returns

```typescript
Array<{
  model: string;              // Model class name
  file: string;              // File path
  computed_fields: Array<{
    name: string;            // Field name
    line: number;            // Line number
    type: string;            // "property", "computed_field", "field_property"
    return_type: string;     // Return type annotation
    depends_on: string[];    // Fields this depends on
    cached: boolean;         // Whether result is cached
    decorator: string;       // Decorator used
    has_setter: boolean;     // Has setter method (for property)
    description: string;     // From docstring or field description
  }>;
}>
```

### Examples

```python
# Find all computed fields
computed = find_computed_fields()
# Returns: [
#   {
#     "model": "UserModel",
#     "file": "/project/models/user.py",
#     "computed_fields": [
#       {
#         "name": "full_name",
#         "line": 45,
#         "type": "property",
#         "return_type": "str",
#         "depends_on": ["first_name", "last_name"],
#         "cached": false,
#         "decorator": "@property",
#         "has_setter": false,
#         "description": "User's full name"
#       },
#       {
#         "name": "age",
#         "line": 55,
#         "type": "computed_field",
#         "return_type": "int",
#         "depends_on": ["birth_date"],
#         "cached": true,
#         "decorator": "@computed_field(cached=True)",
#         "has_setter": false,
#         "description": "Calculated age from birth date"
#       },
#       {
#         "name": "display_name",
#         "line": 65,
#         "type": "field_property",
#         "return_type": "str",
#         "depends_on": ["username", "full_name"],
#         "cached": false,
#         "decorator": "@field_property",
#         "has_setter": true,
#         "description": "Display name with fallback"
#       }
#     ]
#   }
# ]

# Find cached computed fields
cached_fields = []
for model in computed:
    for field in model["computed_fields"]:
        if field["cached"]:
            cached_fields.append({
                "model": model["model"],
                "field": field["name"]
            })

# Find computed fields with dependencies
dependent_fields = []
for model in computed:
    for field in model["computed_fields"]:
        if field["depends_on"]:
            dependent_fields.append(field)
```

### Error Conditions

- Returns empty array if no computed fields
- May miss complex property definitions
- Dependency detection is best-effort

### Performance Notes

- Analyzes property methods and decorators
- Lightweight operation
- Cached with model analysis

### Use Cases

- Performance optimization (caching)
- Dependency analysis
- API documentation
- Serialization planning
- Finding expensive computations

---

## Common Patterns

### Complete Model Analysis

```python
# Comprehensive model analysis
def analyze_pydantic_model(model_name):
    # Get basic schema
    schema = get_model_schema(model_name)

    # Trace inheritance
    hierarchy = trace_model_inheritance(model_name)

    # Find validators
    all_validators = find_validators()
    model_validators = [v for v in all_validators if v["model"] == model_name]

    # Find computed fields
    all_computed = find_computed_fields()
    model_computed = [c for c in all_computed if c["model"] == model_name]

    # Get config
    all_configs = find_model_config()
    model_config = [c for c in all_configs if c["model"] == model_name]

    return {
        "model": model_name,
        "schema": schema,
        "inheritance": hierarchy,
        "validators": model_validators,
        "computed_fields": model_computed,
        "config": model_config[0] if model_config else None,
        "total_fields": len(schema["schema"]["properties"]),
        "required_fields": len(schema["schema"]["required"]),
        "validation_count": len(model_validators[0]["validators"]) if model_validators else 0
    }
```

### Validation Coverage Report

```python
# Check validation coverage across models
def validation_coverage_report():
    models = find_models()
    field_validators = find_field_validators()

    report = []
    for model in models:
        validated_fields = set()
        for fv in field_validators:
            for m in fv["models"]:
                if m["model_name"] == model["name"]:
                    validated_fields.add(fv["field_name"])

        coverage = len(validated_fields) / len(model["fields"]) * 100 if model["fields"] else 0

        report.append({
            "model": model["name"],
            "total_fields": len(model["fields"]),
            "validated_fields": len(validated_fields),
            "coverage": f"{coverage:.1f}%",
            "unvalidated": [f["name"] for f in model["fields"] if f["name"] not in validated_fields]
        })

    return sorted(report, key=lambda x: float(x["coverage"][:-1]))
```

### Migration Helper (v1 to v2)

```python
# Help migrate from Pydantic v1 to v2
def migration_analysis():
    configs = find_model_config()
    validators = find_validators()

    v1_models = [c for c in configs if c["version"] == "v1"]

    migration_tasks = []
    for model in v1_models:
        tasks = []

        # Config changes
        if model["config"].get("orm_mode"):
            tasks.append("Change orm_mode to from_attributes")

        if model["config"].get("allow_population_by_field_name"):
            tasks.append("Change to populate_by_name")

        # Validator changes
        model_validators = [v for v in validators if v["model"] == model["model"]]
        for mv in model_validators:
            for v in mv["validators"]:
                if v["type"] == "validator":
                    tasks.append(f"Update {v['name']} to use @field_validator")
                if v["type"] == "root_validator":
                    tasks.append(f"Update {v['name']} to use @model_validator")

        migration_tasks.append({
            "model": model["model"],
            "file": model["file"],
            "tasks": tasks
        })

    return migration_tasks
```

### Schema Documentation Generator

```python
# Generate markdown documentation for models
def generate_model_docs(model_name):
    schema = get_model_schema(model_name)
    hierarchy = trace_model_inheritance(model_name)
    computed = find_computed_fields()

    doc = f"# {model_name}\n\n"

    # Description
    if schema["schema"].get("description"):
        doc += f"{schema['schema']['description']}\n\n"

    # Inheritance
    if hierarchy["hierarchy"]["parents"]:
        doc += "## Inheritance\n"
        doc += f"Extends: {', '.join([p['name'] for p in hierarchy['hierarchy']['parents']])}\n\n"

    # Fields
    doc += "## Fields\n\n"
    doc += "| Field | Type | Required | Description |\n"
    doc += "|-------|------|----------|-------------|\n"

    for field_name, field_schema in schema["schema"]["properties"].items():
        required = field_name in schema["schema"]["required"]
        doc += f"| {field_name} | {field_schema.get('type', 'any')} | {'✅' if required else '❌'} | {field_schema.get('description', '')} |\n"

    # Computed fields
    model_computed = [c for c in computed if c["model"] == model_name]
    if model_computed and model_computed[0]["computed_fields"]:
        doc += "\n## Computed Fields\n\n"
        for cf in model_computed[0]["computed_fields"]:
            doc += f"- **{cf['name']}** ({cf['type']}): {cf.get('description', '')}\n"

    return doc
```

## Related Tools

- **Navigation**: Use [Core Navigation Tools](./core-navigation.md) to navigate to model definitions
- **Module Analysis**: Use [Module Analysis Tools](./module-analysis.md) to analyze modules containing models
- **Framework Integration**: Models often used with [Flask Tools](./flask-tools.md) or [Django Tools](./django-tools.md)

## Best Practices

1. **Regular validation audits** - Use `find_field_validators` to ensure consistent validation
2. **Check inheritance** - Use `trace_model_inheritance` before modifying base models
3. **Document schemas** - Export schemas for API documentation
4. **Monitor complexity** - Watch for models with too many validators or computed fields
5. **Version compatibility** - Check configs when upgrading Pydantic versions
6. **Performance** - Review computed fields for expensive calculations
