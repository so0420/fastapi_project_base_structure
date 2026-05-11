async def test_hello_world(client):
    response = await client.get("/hello-world")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello World!"}


async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
