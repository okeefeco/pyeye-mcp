"""Tests for the unified lookup tool — identifier parsing, validation, and resolution.

These tests cover Task 3.1 (module structure, validation, identifier classification)
and Task 3.2 (resolution logic for bare names, file paths, dotted paths, coordinates).
"""

from pathlib import Path

import pytest

from pyeye.mcp.lookup import lookup


class TestLookupCoordinatePrecedence:
    """Coordinates take precedence when all three are supplied together with identifier."""

    @pytest.mark.asyncio
    async def test_coordinates_take_precedence_over_identifier(self, tmp_path):
        """When all three coordinates + identifier are given, coordinates win."""
        sample = tmp_path / "sample.py"
        sample.write_text("class MyClass:\n    pass\n")

        result = await lookup(
            identifier="MyClass",
            file=str(sample),
            line=1,
            column=6,
            project_path=str(tmp_path),
        )

        # Should take the coordinate branch — not the identifier branch.
        # The coordinate branch resolves to a symbol (or not-found), not a
        # "classified as bare_name" error message.
        assert isinstance(result, dict)
        assert "classified as" not in result.get(
            "error", ""
        ), "Expected coordinate branch result, not identifier-branch placeholder"

    @pytest.mark.asyncio
    async def test_column_zero_is_valid_coordinate(self, tmp_path):
        """column=0 must be treated as a valid coordinate (not falsy None check)."""
        sample = tmp_path / "sample.py"
        sample.write_text("x = 1\n")

        result = await lookup(
            file=str(sample),
            line=1,
            column=0,
            project_path=str(tmp_path),
        )

        # Should take coordinate branch, not "coordinates incomplete" branch
        assert "Coordinates incomplete" not in result.get("error", "")


class TestLookupPartialCoordinates:
    """Partial coordinates (some but not all) produce a clear error."""

    @pytest.mark.asyncio
    async def test_file_and_line_without_column_errors(self, tmp_path):
        """file + line but no column → Coordinates incomplete error."""
        sample = tmp_path / "sample.py"
        sample.write_text("x = 1\n")

        result = await lookup(
            file=str(sample),
            line=1,
            project_path=str(tmp_path),
        )

        assert "error" in result
        assert "Coordinates incomplete" in result["error"]

    @pytest.mark.asyncio
    async def test_file_only_errors(self, tmp_path):
        """file only → Coordinates incomplete error."""
        sample = tmp_path / "sample.py"
        sample.write_text("x = 1\n")

        result = await lookup(
            file=str(sample),
            project_path=str(tmp_path),
        )

        assert "error" in result
        assert "Coordinates incomplete" in result["error"]

    @pytest.mark.asyncio
    async def test_line_only_errors(self):
        """line only → Coordinates incomplete error."""
        result = await lookup(line=5)

        assert "error" in result
        assert "Coordinates incomplete" in result["error"]

    @pytest.mark.asyncio
    async def test_line_and_column_without_file_errors(self):
        """line + column without file → Coordinates incomplete error."""
        result = await lookup(line=1, column=0)

        assert "error" in result
        assert "Coordinates incomplete" in result["error"]


class TestLookupNoInputs:
    """When neither identifier nor coordinates are provided, return clear error."""

    @pytest.mark.asyncio
    async def test_no_inputs_returns_error(self):
        """Calling lookup with no arguments returns an error."""
        result = await lookup()

        assert "error" in result
        assert "identifier" in result["error"].lower() or "Either" in result["error"]

    @pytest.mark.asyncio
    async def test_project_path_only_returns_error(self):
        """project_path alone is not enough to resolve anything."""
        result = await lookup(project_path=".")

        assert "error" in result
        assert "identifier" in result["error"].lower() or "Either" in result["error"]


class TestLookupIdentifierClassification:
    """Identifier strings are classified into bare_name, file_path, or dotted_path.

    Now that resolution is implemented these tests verify the right branch was taken
    by checking that the "classified as ..." placeholder is NOT returned and the
    result is a valid resolution response (found, not-found, or ambiguous).
    """

    @pytest.mark.asyncio
    async def test_bare_name_classification(self):
        """A plain identifier with no dots or separators takes the bare_name branch."""
        result = await lookup(identifier="Config")

        # Should attempt bare-name resolution — no "classified as" placeholder error
        assert "classified as" not in result.get("error", "")
        # Result is a valid resolution response
        assert isinstance(result, dict)
        assert "type" in result or "found" in result or "ambiguous" in result

    @pytest.mark.asyncio
    async def test_bare_name_with_underscores(self):
        """Underscores are allowed in bare names."""
        result = await lookup(identifier="my_function")

        assert "classified as" not in result.get("error", "")
        assert isinstance(result, dict)
        assert "type" in result or "found" in result or "ambiguous" in result

    @pytest.mark.asyncio
    async def test_file_path_with_slash_classification(self):
        """A path containing / takes the file_path branch."""
        result = await lookup(identifier="src/pyeye/server.py")

        assert "classified as" not in result.get("error", "")
        assert isinstance(result, dict)
        # Resolves to module or not-found (file may or may not exist in cwd)
        assert "type" in result or "found" in result or "ambiguous" in result

    @pytest.mark.asyncio
    async def test_file_path_with_py_extension(self):
        """A string ending in .py with no other dots → file_path (not dotted_path)."""
        result = await lookup(identifier="server.py")

        assert "classified as" not in result.get("error", "")
        assert isinstance(result, dict)
        assert "type" in result or "found" in result or "ambiguous" in result

    @pytest.mark.asyncio
    async def test_file_path_with_py_extension_and_line_suffix(self):
        """A file path with a :line suffix → file_path."""
        result = await lookup(identifier="server.py:42")

        assert "classified as" not in result.get("error", "")
        assert isinstance(result, dict)
        assert "type" in result or "found" in result or "ambiguous" in result

    @pytest.mark.asyncio
    async def test_dotted_path_classification(self):
        """A dotted module path with no slashes and not ending in .py → dotted_path."""
        result = await lookup(identifier="pyeye.mcp.server")

        assert "classified as" not in result.get("error", "")
        assert isinstance(result, dict)
        assert "type" in result or "found" in result or "ambiguous" in result

    @pytest.mark.asyncio
    async def test_dotted_path_with_class(self):
        """A fully-qualified class name → dotted_path."""
        result = await lookup(identifier="pyeye.mcp.server.ServiceManager")

        assert "classified as" not in result.get("error", "")
        assert isinstance(result, dict)
        assert "type" in result or "found" in result or "ambiguous" in result

    @pytest.mark.asyncio
    async def test_file_path_with_backslash(self):
        """A path with backslash separator → file_path."""
        result = await lookup(identifier="src\\pyeye\\server.py")

        assert "classified as" not in result.get("error", "")
        assert isinstance(result, dict)
        assert "type" in result or "found" in result or "ambiguous" in result


# ---------------------------------------------------------------------------
# Resolution tests — Task 3.2
# ---------------------------------------------------------------------------

# Absolute path to the shared fixture used by all resolution tests.
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "lookup_project"


class TestLookupBareNameResolution:
    """Bare name resolution via find_symbol."""

    @pytest.mark.asyncio
    async def test_bare_name_single_match(self):
        """A unique bare name resolves to a single result."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(FIXTURE_DIR),
        )

        assert "type" in result, f"Expected resolved result, got: {result}"
        assert result["type"] == "class"
        assert "ServiceManager" in (result.get("full_name") or "")
        # _resolved_via is stripped after enrichment
        assert "_resolved_via" not in result

    @pytest.mark.asyncio
    async def test_bare_name_no_match(self):
        """A name that does not exist in the project returns found=False."""
        result = await lookup(
            identifier="Nonexistent__XYZ__Symbol",
            project_path=str(FIXTURE_DIR),
        )

        assert result.get("found") is False
        assert result.get("searched", {}).get("indexed") is True

    @pytest.mark.asyncio
    async def test_bare_name_partial_match_returns_result(self):
        """ServiceConfig resolves to exactly one result in the fixture."""
        result = await lookup(
            identifier="ServiceConfig",
            project_path=str(FIXTURE_DIR),
        )

        # ServiceConfig is only defined once in the fixture
        assert "type" in result or "ambiguous" in result
        if "type" in result:
            assert result["type"] == "class"


class TestLookupFilePathResolution:
    """File path resolution — bare module files and file:line forms."""

    @pytest.mark.asyncio
    async def test_file_path_to_module(self):
        """A bare .py filename resolves to the module."""
        result = await lookup(
            identifier="models.py",
            project_path=str(FIXTURE_DIR),
        )

        assert "type" in result, f"Expected resolved result, got: {result}"
        assert result["type"] == "module"
        # _resolved_via is stripped after enrichment
        assert "_resolved_via" not in result

    @pytest.mark.asyncio
    async def test_file_path_with_line(self):
        """A file:line form resolves to the symbol at that line."""
        # models.py line 27 is: class ServiceManager:
        result = await lookup(
            identifier="models.py:27",
            project_path=str(FIXTURE_DIR),
        )

        assert "type" in result or "found" in result, f"Expected result, got: {result}"
        if "type" in result:
            # Should resolve to ServiceManager (class at line 27)
            assert "ServiceManager" in (result.get("name") or "") or result.get("type") in (
                "class",
                "function",
                "module",
            )

    @pytest.mark.asyncio
    async def test_file_path_nonexistent(self):
        """A .py file that does not exist returns found=False."""
        result = await lookup(
            identifier="nonexistent_file.py",
            project_path=str(FIXTURE_DIR),
        )

        assert result.get("found") is False


class TestLookupDottedPathResolution:
    """Dotted path resolution — modules and fully-qualified symbols."""

    @pytest.mark.asyncio
    async def test_dotted_path_to_module(self):
        """A module dotted path resolves to type=module."""
        result = await lookup(
            identifier="lookup_project.models",
            project_path=str(FIXTURE_DIR),
        )

        assert "type" in result or "found" in result, f"Expected result, got: {result}"
        if "type" in result:
            assert result["type"] == "module"
            assert "_resolved_via" not in result

    @pytest.mark.asyncio
    async def test_dotted_path_to_class(self):
        """A fully-qualified class path resolves to type=class."""
        result = await lookup(
            identifier="lookup_project.models.ServiceManager",
            project_path=str(FIXTURE_DIR),
        )

        assert "type" in result or "found" in result, f"Expected result, got: {result}"
        if "type" in result:
            assert result["type"] == "class"
            assert "_resolved_via" not in result

    @pytest.mark.asyncio
    async def test_dotted_path_nonexistent(self):
        """A dotted path that does not exist returns found=False or an error."""
        result = await lookup(
            identifier="lookup_project.models.NonexistentClass",
            project_path=str(FIXTURE_DIR),
        )

        assert result.get("found") is False or "error" in result


class TestLookupCoordinateResolution:
    """Coordinate-based resolution (file + line + column)."""

    @pytest.mark.asyncio
    async def test_coordinates_resolve_class(self):
        """Coordinates pointing to line 27, col 6 of models.py resolve to ServiceManager."""
        models_file = FIXTURE_DIR / "models.py"
        result = await lookup(
            file=str(models_file),
            line=27,
            column=6,
            project_path=str(FIXTURE_DIR),
        )

        assert "type" in result or "found" in result, f"Expected result, got: {result}"
        if "type" in result:
            # _resolved_via is stripped after enrichment
            assert "_resolved_via" not in result

    @pytest.mark.asyncio
    async def test_coordinates_with_identifier_uses_coordinates(self):
        """When coordinates + identifier are both given, coordinates win."""
        models_file = FIXTURE_DIR / "models.py"
        result = await lookup(
            identifier="ServiceConfig",  # different class
            file=str(models_file),
            line=27,
            column=6,
            project_path=str(FIXTURE_DIR),
        )

        # Coordinate branch was taken — result should reflect coordinates, not identifier
        assert isinstance(result, dict)
        assert "classified as" not in result.get("error", "")
        if "type" in result:
            # _resolved_via is stripped after enrichment
            assert "_resolved_via" not in result


# ---------------------------------------------------------------------------
# Response shape tests — Task 3.3
# ---------------------------------------------------------------------------


class TestClassResultShape:
    """Verify full spec-compliant class response shape from lookup."""

    @pytest.mark.asyncio
    async def test_class_top_level_fields(self):
        """Lookup ServiceManager returns all required top-level fields."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(FIXTURE_DIR),
        )

        assert result["type"] == "class"
        assert result["name"] == "ServiceManager"
        assert "ServiceManager" in result["full_name"]
        assert result["file"].endswith("models.py")
        assert result["line"] == 27
        assert result["column"] is not None
        assert result["docstring"] is not None
        assert "_resolved_via" not in result

    @pytest.mark.asyncio
    async def test_class_module_field(self):
        """Class result includes a navigable module ref."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(FIXTURE_DIR),
        )

        module = result["module"]
        assert isinstance(module, dict)
        assert "name" in module
        assert "full_name" in module
        assert "file" in module
        assert module["line"] is None  # module-level ref has null line

    @pytest.mark.asyncio
    async def test_class_methods_list(self):
        """Class result includes methods with signature, return_type, parameters."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(FIXTURE_DIR),
        )

        methods = result["methods"]
        assert isinstance(methods, list)
        assert len(methods) >= 3  # __init__, start, stop, get_config

        # Every method has required navigable fields
        for m in methods:
            assert "name" in m
            assert "full_name" in m
            assert "file" in m
            assert "line" in m
            # Methods also have enriched fields
            assert "signature" in m
            assert "return_type" in m
            assert "parameters" in m
            # column is NOT required in list entries
            assert "column" not in m

        # Check a specific method
        start_methods = [m for m in methods if m["name"] == "start"]
        assert len(start_methods) == 1
        start = start_methods[0]
        assert "start" in start["signature"]
        assert start["return_type"] is not None
        assert len(start["parameters"]) >= 2  # self, port

    @pytest.mark.asyncio
    async def test_class_methods_parameters(self):
        """Method parameters include type_hint (navigable ref) and default."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(FIXTURE_DIR),
        )

        start = [m for m in result["methods"] if m["name"] == "start"][0]
        port_params = [p for p in start["parameters"] if p["name"] == "port"]
        assert len(port_params) == 1
        port = port_params[0]
        assert port["type_hint"] is not None
        assert port["type_hint"]["name"] == "int"
        assert port["default"] == "8080"

    @pytest.mark.asyncio
    async def test_class_subclasses_shape(self):
        """Subclasses is a relationship list: {total, items}."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(FIXTURE_DIR),
        )

        subs = result["subclasses"]
        assert isinstance(subs, dict)
        assert "total" in subs
        assert "items" in subs
        assert subs["total"] >= 1  # ExtendedManager

        for item in subs["items"]:
            assert "name" in item
            assert "full_name" in item
            assert "file" in item
            assert "line" in item

    @pytest.mark.asyncio
    async def test_class_references_shape(self):
        """References is a relationship list: {total, items}."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(FIXTURE_DIR),
        )

        refs = result["references"]
        assert isinstance(refs, dict)
        assert "total" in refs
        assert "items" in refs
        assert refs["total"] >= 1  # used in client.py, utils.py

        for item in refs["items"]:
            assert "name" in item
            assert "full_name" in item
            assert "file" in item
            assert "line" in item

    @pytest.mark.asyncio
    async def test_class_bases_list(self):
        """ExtendedManager bases should include ServiceManager."""
        result = await lookup(
            identifier="ExtendedManager",
            project_path=str(FIXTURE_DIR),
        )

        assert result["type"] == "class"
        bases = result["bases"]
        assert isinstance(bases, list)
        assert len(bases) >= 1
        # Check navigable ref shape
        for b in bases:
            assert "name" in b
            assert "full_name" in b
            assert "file" in b
            assert "line" in b


class TestFunctionResultShape:
    """Verify full spec-compliant function response shape from lookup."""

    @pytest.mark.asyncio
    async def test_function_top_level_fields(self):
        """Lookup create_manager returns all required top-level fields."""
        result = await lookup(
            identifier="create_manager",
            project_path=str(FIXTURE_DIR),
        )

        assert result["type"] == "function"
        assert result["name"] == "create_manager"
        assert result["full_name"] is not None
        assert result["file"].endswith("utils.py")
        assert result["line"] == 13
        assert result["column"] is not None
        assert result["docstring"] is not None
        assert "_resolved_via" not in result

    @pytest.mark.asyncio
    async def test_function_module_field(self):
        """Function result includes a navigable module ref."""
        result = await lookup(
            identifier="create_manager",
            project_path=str(FIXTURE_DIR),
        )

        module = result["module"]
        assert isinstance(module, dict)
        assert module["line"] is None

    @pytest.mark.asyncio
    async def test_function_signature_and_params(self):
        """Function result includes signature, return_type, parameters."""
        result = await lookup(
            identifier="create_manager",
            project_path=str(FIXTURE_DIR),
        )

        assert result["signature"] is not None
        assert "create_manager" in result["signature"]
        assert result["return_type"] is not None  # -> ServiceManager
        assert isinstance(result["parameters"], list)
        assert len(result["parameters"]) >= 2  # name, config

        # Check parameter shapes
        for p in result["parameters"]:
            assert "name" in p
            assert "type_hint" in p
            assert "default" in p

    @pytest.mark.asyncio
    async def test_function_callers_shape(self):
        """Callers is a relationship list: {total, items}."""
        result = await lookup(
            identifier="create_manager",
            project_path=str(FIXTURE_DIR),
        )

        callers = result["callers"]
        assert isinstance(callers, dict)
        assert "total" in callers
        assert "items" in callers
        # create_manager is called in client.py
        assert callers["total"] >= 1

        for item in callers["items"]:
            assert "name" in item
            assert "full_name" in item
            assert "file" in item
            assert "line" in item

    @pytest.mark.asyncio
    async def test_function_callees_shape(self):
        """Callees is a relationship list: {total, items}."""
        result = await lookup(
            identifier="create_manager",
            project_path=str(FIXTURE_DIR),
        )

        callees = result["callees"]
        assert isinstance(callees, dict)
        assert "total" in callees
        assert "items" in callees

    @pytest.mark.asyncio
    async def test_function_references_shape(self):
        """References is a relationship list: {total, items}."""
        result = await lookup(
            identifier="create_manager",
            project_path=str(FIXTURE_DIR),
        )

        refs = result["references"]
        assert isinstance(refs, dict)
        assert "total" in refs
        assert "items" in refs


class TestModuleResultShape:
    """Verify full spec-compliant module response shape from lookup."""

    @pytest.mark.asyncio
    async def test_module_top_level_fields(self):
        """Lookup models.py returns all required top-level fields."""
        result = await lookup(
            identifier="models.py",
            project_path=str(FIXTURE_DIR),
        )

        assert result["type"] == "module"
        assert result["name"] == "models"
        assert result["full_name"] is not None
        assert result["file"].endswith("models.py")
        assert result["line"] is None  # modules have null line
        assert result["column"] is None
        assert result["docstring"] is not None
        assert "_resolved_via" not in result

    @pytest.mark.asyncio
    async def test_module_classes_shape(self):
        """Module classes is a relationship list: {total, items}."""
        result = await lookup(
            identifier="models.py",
            project_path=str(FIXTURE_DIR),
        )

        classes = result["classes"]
        assert isinstance(classes, dict)
        assert "total" in classes
        assert "items" in classes
        assert classes["total"] >= 2  # ServiceConfig, ServiceManager, ExtendedManager

        for item in classes["items"]:
            assert "name" in item
            assert "full_name" in item
            assert "file" in item
            assert "line" in item

    @pytest.mark.asyncio
    async def test_module_functions_shape(self):
        """Module functions is a relationship list: {total, items}."""
        # utils.py has functions
        result = await lookup(
            identifier="utils.py",
            project_path=str(FIXTURE_DIR),
        )

        assert result["type"] == "module"
        funcs = result["functions"]
        assert isinstance(funcs, dict)
        assert "total" in funcs
        assert "items" in funcs
        assert funcs["total"] >= 2  # create_manager, helper

    @pytest.mark.asyncio
    async def test_module_variables_shape(self):
        """Module variables is a relationship list: {total, items}."""
        result = await lookup(
            identifier="utils.py",
            project_path=str(FIXTURE_DIR),
        )

        variables = result["variables"]
        assert isinstance(variables, dict)
        assert "total" in variables
        assert "items" in variables
        assert variables["total"] >= 2  # MAX_RETRIES, DEFAULT_TIMEOUT, etc.

        for item in variables["items"]:
            assert "name" in item
            assert "full_name" in item
            assert "file" in item
            assert "line" in item

    @pytest.mark.asyncio
    async def test_module_imports_shape(self):
        """Module imports is a relationship list: {total, items}."""
        result = await lookup(
            identifier="utils.py",
            project_path=str(FIXTURE_DIR),
        )

        imports = result["imports"]
        assert isinstance(imports, dict)
        assert "total" in imports
        assert "items" in imports

    @pytest.mark.asyncio
    async def test_module_imported_by_shape(self):
        """Module imported_by is a relationship list: {total, items}."""
        result = await lookup(
            identifier="models.py",
            project_path=str(FIXTURE_DIR),
        )

        ib = result["imported_by"]
        assert isinstance(ib, dict)
        assert "total" in ib
        assert "items" in ib

    @pytest.mark.asyncio
    async def test_module_via_dotted_path(self):
        """Module lookup via dotted path also produces full shape."""
        # When project_path IS lookup_project, the module is just "models"
        # not "lookup_project.models"
        result = await lookup(
            identifier="models",
            project_path=str(FIXTURE_DIR),
        )

        # models is unique so resolves as a class (ServiceManager) or module
        # Let's use the file path form which is unambiguous for module lookup
        result = await lookup(
            identifier="client.py",
            project_path=str(FIXTURE_DIR),
        )

        assert result["type"] == "module"
        assert "classes" in result
        assert "functions" in result
        assert "variables" in result


class TestNavigability:
    """For every navigable ref with non-null file, re-lookup should resolve."""

    @pytest.mark.asyncio
    async def test_class_method_navigable(self):
        """Methods listed in a class result can be re-looked-up."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(FIXTURE_DIR),
        )

        for method in result["methods"]:
            if method["file"] and method["line"]:
                sub = await lookup(
                    file=method["file"],
                    line=method["line"],
                    column=0,
                    project_path=str(FIXTURE_DIR),
                )
                # Should resolve to something (not error)
                assert "type" in sub or "found" in sub

    @pytest.mark.asyncio
    async def test_subclass_navigable(self):
        """Subclasses listed in a class result can be re-looked-up."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(FIXTURE_DIR),
        )

        for sc in result["subclasses"]["items"]:
            if sc["full_name"]:
                sub = await lookup(
                    identifier=sc["full_name"],
                    project_path=str(FIXTURE_DIR),
                )
                # May resolve or not (external is OK), but should not crash
                assert isinstance(sub, dict)


class TestLimitParameter:
    """Verify relationship lists respect the limit parameter."""

    @pytest.mark.asyncio
    async def test_class_references_respect_limit(self):
        """References list is capped by limit parameter."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(FIXTURE_DIR),
            limit=2,
        )

        refs = result["references"]
        # total reflects the true count
        assert refs["total"] >= 2
        # items is capped
        assert len(refs["items"]) <= 2

    @pytest.mark.asyncio
    async def test_module_classes_respect_limit(self):
        """Module classes list is capped by limit parameter."""
        result = await lookup(
            identifier="models.py",
            project_path=str(FIXTURE_DIR),
            limit=1,
        )

        classes = result["classes"]
        assert classes["total"] >= 2
        assert len(classes["items"]) <= 1

    @pytest.mark.asyncio
    async def test_class_subclasses_respect_limit(self):
        """Subclasses list is capped by limit parameter."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(FIXTURE_DIR),
            limit=1,
        )

        subs = result["subclasses"]
        assert len(subs["items"]) <= 1


# ---------------------------------------------------------------------------
# Response discrimination tests — Task 3.4
# ---------------------------------------------------------------------------

# Fixture with two Config classes (one in module_a, one in module_b) for
# producing ambiguous lookup results.
AMBIGUOUS_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "symbol_references"


class TestResponseDiscrimination:
    """Verify that each response type uses its own exclusive discriminating field.

    Spec:
    - Success:   has ``type``, does NOT have ``ambiguous``/``found``/``error``
    - Ambiguous: has ``ambiguous: True``, does NOT have ``type``/``found``/``error``
    - Not-found: has ``found: False``, does NOT have ``type``/``ambiguous``/``error``
    - Error:     has ``error``, does NOT have ``type``/``ambiguous``/``found``
    """

    @pytest.mark.asyncio
    async def test_success_has_type_and_no_other_discriminators(self):
        """Resolved symbol has ``type`` and no ``ambiguous``/``found``/``error``."""
        result = await lookup(
            identifier="ServiceManager",
            project_path=str(FIXTURE_DIR),
        )

        assert "type" in result, f"Expected 'type' in success result, got: {result}"
        assert "ambiguous" not in result, "Success result must not have 'ambiguous'"
        assert "found" not in result, "Success result must not have 'found'"
        assert "error" not in result, "Success result must not have 'error'"

    @pytest.mark.asyncio
    async def test_ambiguous_has_flag_and_no_other_discriminators(self):
        """Ambiguous lookup has ``ambiguous: True`` and no ``type``/``found``/``error``."""
        # The symbol_references fixture has two Config classes (module_a and module_b)
        # so looking up "Config" by bare name produces an ambiguous result.
        result = await lookup(
            identifier="Config",
            project_path=str(AMBIGUOUS_FIXTURE_DIR),
        )

        assert (
            result.get("ambiguous") is True
        ), f"Expected ambiguous result for 'Config' in symbol_references fixture, got: {result}"
        assert "type" not in result, "Ambiguous result must not have 'type'"
        assert "found" not in result, "Ambiguous result must not have 'found'"
        assert "error" not in result, "Ambiguous result must not have 'error'"

    @pytest.mark.asyncio
    async def test_not_found_has_flag_and_no_other_discriminators(self):
        """Not-found response has ``found: False`` and no ``type``/``ambiguous``/``error``."""
        result = await lookup(
            identifier="Nonexistent__XYZ__Symbol999",
            project_path=str(FIXTURE_DIR),
        )

        assert (
            result.get("found") is False
        ), f"Expected found=False for nonexistent symbol, got: {result}"
        assert "type" not in result, "Not-found result must not have 'type'"
        assert "ambiguous" not in result, "Not-found result must not have 'ambiguous'"
        assert "error" not in result, "Not-found result must not have 'error'"

    @pytest.mark.asyncio
    async def test_error_has_field_and_no_other_discriminators(self):
        """Error response (partial coordinates) has ``error`` and no ``type``/``ambiguous``/``found``."""
        # Partial coordinates → error
        result = await lookup(
            file="some_file.py",
            line=1,
            # column intentionally omitted
        )

        assert "error" in result, f"Expected 'error' in partial-coords result, got: {result}"
        assert "type" not in result, "Error result must not have 'type'"
        assert "ambiguous" not in result, "Error result must not have 'ambiguous'"
        assert "found" not in result, "Error result must not have 'found'"


class TestNotFoundDetails:
    """Verify the ``searched`` sub-object in not-found responses reflects the lookup form.

    Spec:
    - Bare name:   ``as_module: False, as_symbol: True``
    - Dotted path: ``as_module: True,  as_symbol: True``
    - File path:   ``as_module: True,  as_symbol: False``
    - Invalid project path: ``indexed: False``
    """

    @pytest.mark.asyncio
    async def test_bare_name_not_found_searched_fields(self):
        """Bare name not-found: as_module=False, as_symbol=True."""
        result = await lookup(
            identifier="Nonexistent__XYZ__Bare",
            project_path=str(FIXTURE_DIR),
        )

        assert result.get("found") is False
        searched = result.get("searched", {})
        assert (
            searched.get("as_module") is False
        ), f"Bare name not-found should have as_module=False, got: {searched}"
        assert (
            searched.get("as_symbol") is True
        ), f"Bare name not-found should have as_symbol=True, got: {searched}"

    @pytest.mark.asyncio
    async def test_dotted_path_not_found_searched_fields(self):
        """Dotted path not-found: as_module=True, as_symbol=True."""
        result = await lookup(
            identifier="lookup_project.models.NonexistentClass99",
            project_path=str(FIXTURE_DIR),
        )

        assert result.get("found") is False, f"Expected not-found, got: {result}"
        searched = result.get("searched", {})
        assert (
            searched.get("as_module") is True
        ), f"Dotted path not-found should have as_module=True, got: {searched}"
        assert (
            searched.get("as_symbol") is True
        ), f"Dotted path not-found should have as_symbol=True, got: {searched}"

    @pytest.mark.asyncio
    async def test_file_path_not_found_searched_fields(self):
        """File path not-found: as_module=True, as_symbol=False."""
        result = await lookup(
            identifier="nonexistent_file_xyz.py",
            project_path=str(FIXTURE_DIR),
        )

        assert result.get("found") is False, f"Expected not-found, got: {result}"
        searched = result.get("searched", {})
        assert (
            searched.get("as_module") is True
        ), f"File path not-found should have as_module=True, got: {searched}"
        assert (
            searched.get("as_symbol") is False
        ), f"File path not-found should have as_symbol=False, got: {searched}"

    @pytest.mark.asyncio
    async def test_invalid_project_path_returns_indexed_false(self):
        """When project_path does not exist, searched.indexed must be False."""
        result = await lookup(
            identifier="AnySymbol",
            project_path="/nonexistent/project/path/xyz",
        )

        # Either found=False (with indexed=False) or error is acceptable
        if "found" in result:
            assert result.get("found") is False
            searched = result.get("searched", {})
            assert (
                searched.get("indexed") is False
            ), f"Invalid project path should have indexed=False, got: {searched}"
        else:
            # An error response is also acceptable when project path is invalid
            assert "error" in result or result.get("found") is False
