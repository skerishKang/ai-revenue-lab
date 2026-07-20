import sys

import app  # noqa: F401


def test_app_package_independent_of_siblings():
    # Importing the World Feed app must not pull in sibling product apps.
    forbidden = [
        "personal_edition",
        "living_travel",
        "living_fiction",
        "apps.personal_edition",
        "apps.living_travel",
        "apps.living_fiction",
    ]
    imported = [name for name in forbidden if name in sys.modules]
    assert imported == [], f"sibling imports detected: {imported}"


def test_app_modules_under_world_feed_namespace():
    assert app.__name__ == "app"
    # No cross-app repository imports.
    import app.service as svc

    assert "personal_edition" not in svc.__file__
    assert "living_travel" not in svc.__file__
    assert "living_fiction" not in svc.__file__
