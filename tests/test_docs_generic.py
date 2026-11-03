"""`memory docs` in a project that is not cairnkit: source roots, components, imports, routes."""

from __future__ import annotations

import json
import re
from pathlib import Path

from cairnkit.cli import main

NODE = re.compile(r'^\s*(?:subgraph\s+)?([A-Za-z_][A-Za-z0-9_]*)\["((?:[^"]|#quot;)*)"\]')
EDGE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+-->\s+([A-Za-z_][A-Za-z0-9_]*)\s*$")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def state(repo: Path) -> Path:
    return repo / "docs" / "state"


def page(repo: Path, rel: str) -> str:
    return (state(repo) / rel).read_text(encoding="utf-8")


def pages(repo: Path) -> set[str]:
    return {p.relative_to(state(repo)).as_posix() for p in state(repo).rglob("*.md")}


def diagrams(text: str) -> list[str]:
    return re.findall(r"```mermaid\n(.*?)```", text, re.S)


def nodes(text: str) -> list[str]:
    """The label of each box in the page's diagrams, as a reader sees it."""
    found: list[str] = []
    for block in diagrams(text):
        for line in block.splitlines():
            match = NODE.match(line)
            if match and not line.lstrip().startswith("subgraph"):
                found.append(match.group(2))
    return found


def edges(text: str) -> set[tuple[str, str]]:
    """Each arrow in the page's diagrams, as (from label, to label)."""
    found: set[tuple[str, str]] = set()
    for block in diagrams(text):
        labels: dict[str, str] = {}
        for line in block.splitlines():
            match = NODE.match(line)
            if match:
                labels[match.group(1)] = match.group(2)
        for line in block.splitlines():
            match = EDGE.match(line)
            if match:
                found.add((labels[match.group(1)], labels[match.group(2)]))
    return found


def front(text: str) -> dict[str, object]:
    head = text.split("---\n", 2)[1]
    data: dict[str, object] = {}
    key = ""
    for line in head.splitlines():
        if line.startswith("  - "):
            data.setdefault(key, [])
            data[key].append(line[4:])  # type: ignore[union-attr]
        elif line.startswith("  ") and key == "diagramLinks":
            name, value = line.strip().split(": ", 1)
            data.setdefault(key, {})
            data[key][name] = value  # type: ignore[index]
        elif ":" in line:
            key, _, value = line.partition(":")
            value = value.strip()
            if value and value != "[]":
                data[key] = value.strip('"')
    return data


def all_sources(repo: Path) -> set[str]:
    found: set[str] = set()
    for rel in pages(repo):
        found.update(front(page(repo, rel)).get("sources", []))  # type: ignore[arg-type]
    return found


def plant_django(repo: Path) -> None:
    write(repo / "pyproject.toml", '[project]\nname = "shop"\ndescription = "A small shop."\n')
    write(
        repo / "backend" / "manage.py",
        '"""Django\'s command-line utility."""\nimport os\nimport sys\n\n\ndef main():\n'
        '    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")\n'
        "    from django.core.management import execute_from_command_line\n\n"
        "    execute_from_command_line(sys.argv)\n\n\n"
        'if __name__ == "__main__":\n    main()\n',
    )
    write(repo / "backend" / "pyproject.toml", '[project]\nname = "shop-backend"\n')
    write(repo / "backend" / "config" / "__init__.py", "")
    write(
        repo / "backend" / "config" / "settings.py",
        'ROOT_URLCONF = "config.urls"\nINSTALLED_APPS = ["shop"]\n',
    )
    write(
        repo / "backend" / "config" / "urls.py",
        "from django.urls import include, path\n\n"
        "from shop import views\nfrom shop.api import api\n\n"
        'urlpatterns = [\n    path("", views.home, name="home"),\n'
        '    path("shop/", include("shop.urls")),\n    path("api/", api.urls),\n]\n',
    )
    write(repo / "backend" / "shop" / "__init__.py", '"""Sell items to guests."""\n')
    write(
        repo / "backend" / "shop" / "apps.py",
        'from django.apps import AppConfig\n\n\nclass ShopConfig(AppConfig):\n    name = "shop"\n',
    )
    write(repo / "backend" / "shop" / "models.py", '"""Items and orders."""\n')
    write(
        repo / "backend" / "shop" / "views.py",
        '"""Pages for the shop."""\nfrom . import models\n\n\ndef home(request):\n'
        "    from shop.pricing import total\n\n    return total()\n",
    )
    write(repo / "backend" / "shop" / "pricing.py", "def total():\n    return 0\n")
    write(
        repo / "backend" / "shop" / "urls.py",
        "from django.urls import path\n\nfrom . import views\n\n"
        'urlpatterns = [path("items/<int:pk>/", views.home)]\n',
    )
    write(
        repo / "backend" / "shop" / "api.py",
        '"""The JSON API."""\nfrom ninja import NinjaAPI\n\napi = NinjaAPI()\n\n\n'
        '@api.get("/items")\ndef items(request):\n    return []\n\n\n'
        '@api.post(\n    "/orders",\n)\ndef order(request):\n    return {}\n\n\n'
        "from flask import Flask\n\napp = Flask(__name__)\n\n\n"
        '@app.route("/health", methods=["GET", "HEAD"])\ndef health():\n    return "ok"\n',
    )
    write(repo / "backend" / "shop" / "migrations" / "__init__.py", "")
    write(
        repo / "backend" / "shop" / "migrations" / "0001_initial.py",
        "from shop import models\n",
    )
    write(repo / "backend" / "tests" / "test_views.py", "from shop import views\n")
    write(repo / "tools" / "__init__.py", "")
    write(
        repo / "tools" / "seed.py",
        '"""Fill the database with sample items."""\n\nif __name__ == "__main__":\n    print(1)\n',
    )
    write(repo / "tools" / "wipe.py", 'if "__main__" == __name__:\n    print(0)\n')


def test_a_nested_django_backend_gets_a_page_per_app(mem: Path, repo: Path):
    plant_django(repo)
    assert main(["docs"]) == 0
    assert pages(repo) == {
        "README.md",
        "components/backend.md",
        "components/backend-config.md",
        "components/backend-shop.md",
        "components/tools.md",
    }
    system = page(repo, "README.md")
    assert front(system)["kind"] == "system"
    assert ("backend/config", "backend/shop") in edges(system)
    assert {"backend/config", "backend/shop", "backend", "tools"} <= set(nodes(system))
    links = front(system)["diagramLinks"]
    assert set(links.values()) == {"backend", "backend-config", "backend-shop", "tools"}  # type: ignore[union-attr]
    assert (
        "| Django manage.py | `manage.py` | `settings config.settings` | `backend/manage.py` |"
        in system
    )
    assert (
        "| Python script | 2 files | `__main__` blocks | [tools](components/tools.md) |" in system
    )
    assert "`tools/seed.py`" in page(repo, "components/tools.md")
    assert "`tools/wipe.py`" in page(repo, "components/tools.md")

    shop = page(repo, "components/backend-shop.md")
    meta = front(shop)
    assert meta["kind"] == "module"
    assert meta["parent"] == "shop"
    assert meta["summary"] == "Sell items to guests."
    assert "Django app" in shop
    assert ("views.py", "models.py") in edges(shop)
    assert ("views.py", "pricing.py") in edges(shop)
    assert "backend/shop/models.py" in meta["sources"]  # type: ignore[operator]
    assert "| GET | `/api/items` | `items` | `backend/shop/api.py` |" in shop
    assert "| POST | `/api/orders` | `order` | `backend/shop/api.py` |" in shop
    assert "| GET/HEAD | `/health` | `health` | `backend/shop/api.py` |" in shop
    assert "| ANY | `/shop/items/<int:pk>/` | `views.home` | `backend/shop/urls.py` |" in shop
    assert "`/items`" not in shop
    assert "[backend/config](backend-config.md)" in shop

    config = page(repo, "components/backend-config.md")
    assert "| ANY | `/` | `views.home` | `backend/config/urls.py` |" in config
    assert "api.urls" not in config
    assert ("urls.py", "backend/shop") in edges(config)

    sources = all_sources(repo)
    assert not any("migrations" in path or "tests/" in path for path in sources)


def plant_web(repo: Path) -> None:
    write(
        repo / "web" / "package.json",
        json.dumps(
            {
                "name": "web",
                "description": "Storefront.",
                "main": "src/main.tsx",
                "scripts": {"dev": "vite", "build": "tsc && vite build"},
            }
        ),
    )
    write(
        repo / "web" / "tsconfig.json",
        '{\n  // The app.\n  "$schema": "https://json.schemastore.org/tsconfig",\n'
        '  "compilerOptions": {\n    "baseUrl": ".",\n'
        '    "paths": { "@/*": ["src/*"], }, /* a trailing comma */\n  },\n}\n',
    )
    write(
        repo / "web" / "src" / "main.tsx", 'import { App } from "./App";\nimport "./styles.css";\n'
    )
    write(repo / "web" / "src" / "styles.css", "body {}\n")
    write(
        repo / "web" / "index.html",
        '<html><body><script type="module" src="/src/main.tsx"></script>\n'
        '<script src="https://cdn.example.com/x.js"></script></body></html>\n',
    )
    write(
        repo / "web" / "src" / "App.tsx",
        "/** The whole page. */\n"
        'import { fetchItems } from "@/lib/api";\nimport Button from "./components/Button";\n'
        "export function App() {}\n",
    )
    write(repo / "web" / "src" / "lazy.ts", 'export const load = () => import("./lib/api");\n')
    write(repo / "web" / "src" / "lib" / "api.ts", "export async function fetchItems() {}\n")
    write(repo / "web" / "src" / "lib" / "types.ts", "export type Item = { id: number };\n")
    write(
        repo / "web" / "src" / "components" / "Button.tsx",
        'import { fetchItems } from "../lib/api.js";\n'
        'import type { Item } from "@/lib/types";\nimport React from "react";\n',
    )
    write(repo / "web" / "src" / "components" / "Button.test.tsx", 'import B from "./Button";\n')
    write(repo / "web" / "src" / "components" / "Button.stories.tsx", 'import B from "./Button";\n')
    write(repo / "web" / "src" / "env.d.ts", "declare const x: number;\n")
    write(repo / "web" / "node_modules" / "react" / "index.js", "module.exports = {};\n")
    write(repo / "web" / "dist" / "assets" / "index.js", 'import "./chunk.js";\n')
    write(repo / "web" / "src" / "vendor" / "chart.js", "export default {};\n")
    write(repo / "web" / "src" / "registry.generated.ts", 'import "./lib/api";\n')


def test_a_typescript_app_follows_relative_and_alias_imports(mem: Path, repo: Path):
    plant_web(repo)
    assert main(["docs"]) == 0
    assert pages(repo) == {
        "README.md",
        "components/web-src.md",
        "components/web-src-components.md",
        "components/web-src-lib.md",
    }
    system = page(repo, "README.md")
    assert edges(system) >= {
        ("web/src", "web/src/lib"),
        ("web/src", "web/src/components"),
        ("web/src/components", "web/src/lib"),
    }
    assert "`dev`" in system and "`vite`" in system
    assert "| package main | `main` | `src/main.tsx` | `web/package.json` |" in system
    assert "| page script | `index.html` | `/src/main.tsx` | `web/index.html` |" in system
    assert "cdn.example.com" not in system

    top = page(repo, "components/web-src.md")
    assert edges(top) >= {
        ("main.tsx", "App.tsx"),
        ("App.tsx", "web/src/lib"),
        ("App.tsx", "web/src/components"),
        ("lazy.ts", "web/src/lib"),
    }
    assert "The whole page." in top
    assert ("Button.tsx", "web/src/lib") in edges(page(repo, "components/web-src-components.md"))

    sources = all_sources(repo)
    assert "web/src/lib/types.ts" in sources
    banned_parts = ("node_modules", "dist/", "vendor/", ".generated.", ".test.", ".stories.")
    for banned in (*banned_parts, ".d.ts", ".css"):
        assert not any(banned in path for path in sources), banned


def test_a_plain_python_package_maps_its_modules(mem: Path, repo: Path):
    write(
        repo / "pyproject.toml",
        '[project]\nname = "pkg"\ndescription = "Do one thing well."\n\n'
        '[project.scripts]\npkg = "pkg.cli:main"\n',
    )
    write(repo / "src" / "pkg" / "__init__.py", "")
    write(repo / "src" / "pkg" / "a.py", '"""First step."""\nfrom pkg import b\n')
    write(repo / "src" / "pkg" / "b.py", '"""Second step."""\n')
    write(repo / "src" / "pkg" / "cli.py", "from .a import run\nfrom . import b\n")
    write(repo / "src" / "pkg" / "sub" / "__init__.py", "")
    write(repo / "src" / "pkg" / "sub" / "c.py", "from ..a import run\n")
    assert main(["docs"]) == 0
    assert pages(repo) == {"README.md", "components/src-pkg.md"}
    system = page(repo, "README.md")
    assert front(system)["summary"] == "Do one thing well."
    assert "`pkg.cli:main`" in system
    comp = page(repo, "components/src-pkg.md")
    assert set(nodes(comp)) == {"a.py", "b.py", "cli.py", "sub/c.py"}
    assert edges(comp) == {("a.py", "b.py"), ("cli.py", "a.py"), ("sub/c.py", "a.py")}
    assert "| `b.py` | Second step. | 2 |" in comp
    assert "First step." in comp


def test_an_empty_project_gets_a_system_page_alone(mem: Path, repo: Path, capsys):
    assert main(["docs"]) == 0
    assert pages(repo) == {"README.md"}
    assert "No Python or TypeScript/JavaScript source" in page(repo, "README.md")
    capsys.readouterr()
    assert main(["docs", "--check"]) == 0
    assert capsys.readouterr().out == ""


def test_diagrams_stay_small_and_the_file_table_lists_every_file(mem: Path, repo: Path):
    count = 50
    write(repo / "big" / "__init__.py", "")
    for index in range(count):
        body = f"import big.m{(index + 1) % count:02d}\n"
        write(repo / "big" / f"m{index:02d}.py", body)
    assert main(["docs"]) == 0
    comp = page(repo, "components/big.md")
    assert 0 < len(nodes(comp)) <= 30
    for index in range(count):
        assert f"`m{index:02d}.py`" in comp
    assert len(front(comp)["sources"]) == count  # type: ignore[arg-type]


def test_rerun_is_byte_stable_and_check_sees_an_import_change(mem: Path, repo: Path, capsys):
    plant_django(repo)
    plant_web(repo)
    assert main(["docs"]) == 0
    first = {rel: page(repo, rel) for rel in pages(repo)}
    assert main(["docs", "--force"]) == 0
    assert {rel: page(repo, rel) for rel in pages(repo)} == first
    capsys.readouterr()
    assert main(["docs", "--check"]) == 0

    write(repo / "backend" / "shop" / "views.py", '"""Pages for the shop."""\n')
    capsys.readouterr()
    assert main(["docs", "--check"]) == 1
    assert "docs/state/components/backend-shop.md" in capsys.readouterr().out.splitlines()
