

from fastapi.testclient import TestClient

from ecos.main import app




    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ecos-backend",
        "version": "0.1.0",

    }
