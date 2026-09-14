# BIM Coder Kit

## Scope

- The extension lives in `BIM Coder Kit.extension/`.
- Ribbon buttons are pyRevit command folders containing `script.py`.
- Button metadata and links use `bundle.yaml`.
- Shared Python helpers live in `lib/` and should be reused when applicable.

## Conventions

- Preserve the existing Portuguese names and folder structure.
- Keep command scripts compatible with the pyRevit/Revit Python runtime.
- Keep edits focused; avoid changing unrelated buttons or bundle metadata.
- Use ASCII by default unless an existing file requires another character set.

## Validation

- Run Python syntax checks on changed `*.py` files when the local interpreter supports the syntax.
- Review changed YAML for valid indentation and quoting.
- pyRevit/Revit-specific behavior must be verified inside the host application.
