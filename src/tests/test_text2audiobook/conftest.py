import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parents[2] / "tools" / "text2audiobook" / "src" / "text2audiobook"
INIT = PKG_DIR / "__init__.py"

if "epub2audiobook" not in sys.modules:
    spec = spec_from_file_location(
        "epub2audiobook",
        INIT,
        submodule_search_locations=[str(PKG_DIR)],
    )
    module = module_from_spec(spec)
    sys.modules["epub2audiobook"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
