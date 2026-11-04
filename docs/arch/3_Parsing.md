# Parsing

## Overview

Parsing reads all files in the project and constructs an internal representation called the **Manifest**. The manifest contains all project resources models, tests, seeds, snapshots, sources, macros, docs, etc, and their relationships. Parsing captures dependencies (`ref()`, `source()`) and configuration, but does not compile SQL or execute anything against the database—those happen later during execution.

The manifest is written to `target/manifest.json` for external tooling and for stateful dbt behavior such as `state:modified` selection and deferral. It is also serialized to msgpack to `target/partial_parse.msgpack` for reuse on subsequent runs in partial parsing. Note that the manifest produced by parsing is not complete: fields like `compiled_code` are populated later during compilation, and graph validation (e.g., cycle detection) happens after parsing.

## Entry Point

The main entry point is `ManifestLoader.get_full_manifest()`, called from the `@requires.manifest` decorator. This method:

1. Loads project dependencies
2. Creates a `ManifestLoader` instance
3. Calls `loader.load()` to perform the actual parsing
4. Runs post-parse validation (`_check_manifest`—checks resource uniqueness, warns for unused configs)

## Parsing Phases

The `ManifestLoader.load()` method orchestrates parsing in several phases:

### 1. Read Files
Scan project directories and build `manifest.files`—a dictionary of file IDs to `SourceFile` objects containing paths, checksums, and metadata. This phase also checks for partial parsing opportunities (see [Partial Parsing](3.1_Partial_Parsing.md)).

### 2. Load Macros
Macros must be parsed first because they're needed for Jinja rendering during subsequent parsing. Additonally Generic Tests also get parsed at this time due to their similarity to macros. `MacroParser` processes `.sql` files in macro directories, and `GenericTestParser` handles generic test definitions. After loading, `build_macro_resolver()` creates the `MacroResolver` for looking up macros by name.

### 3. Parse Project Files
For each project (root + dependencies), run the appropriate parsers based on file type:

- `ModelParser` — SQL/Python models
- `SnapshotParser` — Snapshot definitions
- `AnalysisParser` — Analysis files
- `SingularTestParser` — Singular test SQL files
- `SeedParser` — CSV seed files
- `DocumentationParser` — Markdown docs
- `HookParser` — on-run-start/end hooks from `dbt_project.yml`
- `FixtureParser` — Unit test fixtures
- `FunctionParser` — Function definitions

### 4. Parse Schema Files
`SchemaParser` processes YAML files, extracting:
- Model/seed/snapshot/analysis/function patches (descriptions, configs, columns)
- Source definitions
- Exposures, metrics, semantic models, saved queries
- Generic tests attached to models/sources
- Groups and unit tests

### 5. Patch Sources
Note: The term 'patch' refers to the schema.yml contents corresponding to a particular resource in a dbt project.

`SourcePatcher.construct_sources()` converts unparsed source definitions into `SourceDefinition` nodes, applying any source patches (overrides).

### 6. Process References
Resolve symbolic references captured during parsing:
- `process_refs()` — Look up `ref()` targets and populate `depends_on.nodes`
- `process_sources()` — Look up `source()` targets
- `process_docs()` — Render `{{ doc() }}` blocks in descriptions
- `process_metrics()` — Resolve metric dependencies

### 7. Validation
- Check resource uniqueness (no duplicate names/aliases)
- Validate group and access configurations
- Validate snapshot and microbatch configs

## Key Classes

### `ManifestLoader` (`manifest.py`)

Orchestrates the entire parsing process. Key attributes:
- `root_project` / `all_projects` — Project configurations
- `manifest` — The manifest being built
- `saved_manifest` — Previous manifest for partial parsing
- `partial_parser` — `PartialParsing` instance if doing incremental parse

### Parser Hierarchy (`base.py`)

- `BaseParser` — Abstract base with `parse_file()` method and `resource_type` property
- `Parser` — Adds `root_project` reference for cross-project parsing
- `ConfiguredParser` — Handles config resolution, FQN generation, and relation name updates (database/schema/alias)
- `SimpleSQLParser` — Convenience class for straightforward SQL file parsing

Each parser reads `FileBlock` objects and adds parsed nodes to the manifest via `manifest.add_node()`.

### `SchemaParser` (`schemas.py`)

The most complex parser: handles YAML property files with multiple sub-parsers for different top-level keys (models, sources, exposures, etc.). Produces both nodes and "patches" that are applied to nodes parsed from SQL files.

## Parsing vs. Compilation vs. Runtime

See `docs/guides/parsing-vs-compilation-vs-runtime.md` for a detailed explanation of these distinctions.

- **Parsing** — Read files, construct manifest, capture `ref()`/`source()`/`config()` calls. No database connection required.
- **Compilation** — Render Jinja with `execute=True`, run introspective queries (requiring an adapter / warehouse connection), populate `compiled_code`. Happens at runtime, in DAG order.
- **Runtime** — Execute materializations, run tests, apply DDL/DML to the database.

## Static Jinja Context Functions

The initial static-function implementation covers `ref()` and `doc()` only.
Their Python entry points live in `core/dbt/context/static_functions/`, one
function per module. Context providers use `functools.partial` to bind the
current resolver or docs context before exposing these callables to Jinja.
They are not generated from macro text. Jinja expressions and control flow
(`if`, `for`, and variables) continue to execute normally.

- `resolve_ref()` handles call arguments and invokes the existing resolver's
  validation and resolution methods. Parse-time dependency recording and
  runtime Relation creation, access checks, ephemeral CTEs, operation behavior,
  and unit-test behavior stay with their existing resolver classes.
- `resolve_doc()` resolves the documentation block, records the consuming node
  on its source file for partial parsing, and returns the block contents.

The top-level `ref` and `builtins.ref` use the Python implementation even when a
project defines a macro named `ref`. This intentionally changes compatibility
for projects that previously used a top-level `ref` macro override. The macro
is still callable explicitly as `package_name.ref(...)`. All other macro
loading, lookup, overrides, and execution remain unchanged; this prototype does
not remove the general macro system.

When upgrading from the previous implementation, run `dbt build
--no-partial-parse` once (or use `dbt parse --no-partial-parse` before the next
build). The package version is unchanged, so an existing
`target/partial_parse.msgpack` may otherwise retain dependencies rewritten by
an old top-level `ref` macro and cause a dependency-inference compilation error.
The full parse regenerates the cache using the new ref behavior; subsequent
invocations can use normal partial parsing. Reusing an older cache across this
change is not supported.

Standalone YAML semantic model and exposure contexts retain their specialized
ref resolvers and validation. No semantic model schema, Manifest field, or
Relation representation changes are introduced here.

## Partial Parsing

To improve performance on subsequent invocations, dbt can reuse the previous manifest and only re-parse files that have changed. This is controlled by the `--partial-parse` flag (enabled by default). See [Partial Parsing](3.1_Partial_Parsing.md)
