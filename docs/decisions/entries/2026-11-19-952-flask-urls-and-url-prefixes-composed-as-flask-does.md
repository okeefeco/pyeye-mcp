---
date: "2026-11-19"
title: "Flask routes' urls and blueprints' url_prefixes are composed as Flask does, as lists, present only when every registration is known (#952)"
issues: [952, 951, 568, 910]
anchors: ["pyeye.plugins.flask._UrlRegistry", "pyeye.plugins.flask._prefix_option", "pyeye.plugins.flask._join", "pyeye.plugins.flask.FlaskPlugin._url_registry", "pyeye.plugins.flask.FlaskPlugin._owner_key", "pyeye.plugins.flask.FlaskPlugin.find_routes", "pyeye.plugins.flask.FlaskPlugin.find_blueprints"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-19 — Flask routes' urls and blueprints' url_prefixes are composed as Flask does, as lists, present only when every registration is known (#952)

**Friction:** `find_flask_routes` reported a route's decorator literal as `path`. So a route under `Blueprint(url_prefix="/admin")`, or one registered with `register_blueprint(bp, url_prefix="/api")`, read as `/` rather than the URL it serves, and `find_flask_blueprints` showed a register-time prefix as `None`. #951 reworded the docs to say `path` is the route's own; this adds the served URLs.

**Decision** (rules approved by the coordinator, field shape the maintainer's, 2026-11-19):

- **New fields, additive.** Each route gains **`urls`** and each blueprint gains **`url_prefixes`**. Both are sorted, deduplicated lists, with one element in the common single-registration case. The existing `path` and `url_prefix` are unchanged. On an app, a route's `urls` is `[path]`.
- **Flask's composition.** A `register_blueprint(bp, url_prefix=Y)` prefix **overrides** the blueprint's constructor prefix; it isn't concatenated. A nested blueprint's prefix is its parent's effective prefix joined with its own, as `parent.rstrip("/") + "/" + own.lstrip("/")`. A route's rule is joined to its blueprint's prefix the same way, and the empty rule `""` is the prefix itself (`BlueprintSetupState.add_url_rule`). A blueprint with no prefix at all shows `""` in `url_prefixes`.
- **Present only when EVERY registration is known; omitted otherwise, never partial.** Both fields are omitted when any of these holds:
  - a prefix isn't a string literal;
  - a registration has a `subdomain` or a `**` splat;
  - a registration's receiver can't be placed as a `Flask(...)` or `Blueprint(...)`;
  - the blueprint isn't registered in the searched scope;
  - registrations form a cycle.

  If any `register_blueprint` argument in scope can't be identified, every answer is unknown, because it might be any blueprint.
- **Identity by definition site** (module plus binding name). Imported apps and blueprints are placed through the file's imports, as #910 does. The resolver is consulted only for a re-export, once per path per call, so #910's cost guarantees hold.
- Classified `added`, for v2.2.0.

**Anchor:** `pyeye.plugins.flask._UrlRegistry`, `_prefix_option`, `_join`; `FlaskPlugin._url_registry`, `_owner_key`, `find_routes`, `find_blueprints`; #952, #951, #568, #910.
**Applies-to:**

- the composition and the unknown rules: `pyeye.plugins.flask._UrlRegistry`, `pyeye.plugins.flask._prefix_option`, `pyeye.plugins.flask._join`;
- gathering apps, blueprints and registrations: `pyeye.plugins.flask.FlaskPlugin._url_registry`, `pyeye.plugins.flask.FlaskPlugin._owner_key`;
- the fields: `pyeye.plugins.flask.FlaskPlugin.find_routes` (`urls`), `pyeye.plugins.flask.FlaskPlugin.find_blueprints` (`url_prefixes`).

**Verify:** GOLD. `uv run pytest tests/unit/plugins/test_flask_urls.py tests/unit/plugins/test_flask_imported_owners.py` covers:

- an app route;
- the constructor prefix;
- a register-time override with an empty rule;
- a nested blueprint;
- a blueprint registered twice;
- omission for a dynamic prefix, an unregistered blueprint, a mix of known and unknown registrations, a subdomain, a splat and a cycle;
- `path` and `url_prefix` unchanged;
- #910's one-resolve and no-resolve guarantees, and its cost bound.
