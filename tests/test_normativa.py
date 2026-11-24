from fastapi.testclient import TestClient


def test_paginas_normativa():
    import app.main as main
    c = TestClient(main.app)
    assert c.get("/normativa").status_code == 200
    r = c.get("/normativa/la-jonquera/zona-8")
    assert r.status_code == 200 and "15.000" in r.text and 'name="description"' in r.text
    assert c.get("/normativa/no-existe").status_code == 404
    assert "/normativa/granollers" in c.get("/sitemap.xml").text
